"""Deterministic, auditable model routing for the orchestrator gateway.

Routing is a first-match rule table over request features (model alias, task class, tool use,
prompt size) that selects a *pool* of workers plus an explicit fallback list. The table is
validated when the gateway starts and an invalid table prevents start-up (fail closed). Every
decision records the rule that matched and why, so a response can always be traced to a rule.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

MATCH_KEYS = {"model", "task_class", "has_tools", "min_prompt_tokens", "max_prompt_tokens"}
RULE_KEYS = {"id", "match", "pool", "fallback"}


class RouteConfigError(ValueError):
    pass


@dataclass(frozen=True)
class RouteRule:
    rule_id: str
    pool: str
    fallback: tuple[str, ...] = ()
    models: frozenset[str] | None = None
    task_classes: frozenset[str] | None = None
    has_tools: bool | None = None
    min_prompt_tokens: int | None = None
    max_prompt_tokens: int | None = None

    def matches(self, *, model: str | None, task_class: str | None, has_tools: bool, prompt_tokens: int) -> bool:
        if self.models is not None and model not in self.models:
            return False
        if self.task_classes is not None and task_class not in self.task_classes:
            return False
        if self.has_tools is not None and has_tools != self.has_tools:
            return False
        if self.min_prompt_tokens is not None and prompt_tokens < self.min_prompt_tokens:
            return False
        if self.max_prompt_tokens is not None and prompt_tokens > self.max_prompt_tokens:
            return False
        return True

    def describe(self) -> dict[str, Any]:
        match: dict[str, Any] = {}
        if self.models is not None:
            match["model"] = sorted(self.models)
        if self.task_classes is not None:
            match["task_class"] = sorted(self.task_classes)
        if self.has_tools is not None:
            match["has_tools"] = self.has_tools
        if self.min_prompt_tokens is not None:
            match["min_prompt_tokens"] = self.min_prompt_tokens
        if self.max_prompt_tokens is not None:
            match["max_prompt_tokens"] = self.max_prompt_tokens
        return {"id": self.rule_id, "match": match, "pool": self.pool, "fallback": list(self.fallback)}


@dataclass(frozen=True)
class RouteDecision:
    rule_id: str
    pool: str
    fallback: tuple[str, ...]
    reason: str

    @property
    def pools(self) -> tuple[str, ...]:
        return (self.pool, *self.fallback)


def _strings(value: Any, field: str, rule_id: str) -> frozenset[str]:
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not items or not all(isinstance(i, str) and i for i in items):
        raise RouteConfigError(f"rule '{rule_id}': '{field}' must be a non-empty string or list of strings")
    return frozenset(items)


def _int(value: Any, field: str, rule_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RouteConfigError(f"rule '{rule_id}': '{field}' must be a non-negative integer")
    return value


class Router:
    """First-match rule table. The last rule must be an unconditional default."""

    def __init__(self, rules: list[RouteRule], aliases: dict[str, str] | None = None) -> None:
        if not rules:
            raise RouteConfigError("route table must contain at least one rule")
        ids = [r.rule_id for r in rules]
        if len(set(ids)) != len(ids):
            raise RouteConfigError("route rule ids must be unique")
        last = rules[-1]
        if (last.models, last.task_classes, last.has_tools, last.min_prompt_tokens, last.max_prompt_tokens) != (None,) * 5:
            raise RouteConfigError("the last route rule must be an unconditional default (empty match)")
        self.rules = tuple(rules)
        self.aliases = dict(aliases or {})

    @classmethod
    def from_config(cls, rules_cfg: Any, aliases: Any = None) -> "Router":
        if not isinstance(rules_cfg, list):
            raise RouteConfigError("routes must be a list of rules")
        if aliases is not None and not (isinstance(aliases, dict) and all(isinstance(k, str) and isinstance(v, str) for k, v in aliases.items())):
            raise RouteConfigError("aliases must map model names to pool names")
        rules: list[RouteRule] = []
        for index, raw in enumerate(rules_cfg):
            if not isinstance(raw, dict):
                raise RouteConfigError(f"rule #{index} must be an object")
            rule_id = raw.get("id") or f"rule-{index}"
            unknown = set(raw) - RULE_KEYS
            if unknown:
                raise RouteConfigError(f"rule '{rule_id}': unknown keys {sorted(unknown)}")
            pool = raw.get("pool")
            if not isinstance(pool, str) or not pool:
                raise RouteConfigError(f"rule '{rule_id}': 'pool' is required")
            fallback = raw.get("fallback", [])
            if not isinstance(fallback, list) or not all(isinstance(p, str) and p for p in fallback) or pool in fallback:
                raise RouteConfigError(f"rule '{rule_id}': 'fallback' must be a list of other pool names")
            match = raw.get("match", {})
            if not isinstance(match, dict) or set(match) - MATCH_KEYS:
                raise RouteConfigError(f"rule '{rule_id}': match keys must be within {sorted(MATCH_KEYS)}")
            has_tools = match.get("has_tools")
            if has_tools is not None and not isinstance(has_tools, bool):
                raise RouteConfigError(f"rule '{rule_id}': 'has_tools' must be a boolean")
            lo = _int(match["min_prompt_tokens"], "min_prompt_tokens", rule_id) if "min_prompt_tokens" in match else None
            hi = _int(match["max_prompt_tokens"], "max_prompt_tokens", rule_id) if "max_prompt_tokens" in match else None
            if lo is not None and hi is not None and lo > hi:
                raise RouteConfigError(f"rule '{rule_id}': min_prompt_tokens exceeds max_prompt_tokens")
            rules.append(RouteRule(
                rule_id=rule_id, pool=pool, fallback=tuple(fallback),
                models=_strings(match["model"], "model", rule_id) if "model" in match else None,
                task_classes=_strings(match["task_class"], "task_class", rule_id) if "task_class" in match else None,
                has_tools=has_tools, min_prompt_tokens=lo, max_prompt_tokens=hi,
            ))
        return cls(rules, aliases)

    def referenced_pools(self) -> set[str]:
        pools = set(self.aliases.values())
        for rule in self.rules:
            pools.add(rule.pool)
            pools.update(rule.fallback)
        return pools

    def decide(self, *, model: str | None, task_class: str | None, has_tools: bool, prompt_tokens: int) -> RouteDecision:
        # A model name that is an alias for a pool is an explicit client choice and bypasses the table.
        if model is not None and model in self.aliases:
            return RouteDecision(f"alias:{model}", self.aliases[model], (), f"model alias '{model}'")
        for rule in self.rules:
            if rule.matches(model=model, task_class=task_class, has_tools=has_tools, prompt_tokens=prompt_tokens):
                return RouteDecision(rule.rule_id, rule.pool, rule.fallback, f"matched rule '{rule.rule_id}'")
        raise RouteConfigError("no route rule matched")  # unreachable: the last rule is unconditional

    def describe(self) -> dict[str, Any]:
        return {"aliases": dict(self.aliases), "rules": [r.describe() for r in self.rules]}
