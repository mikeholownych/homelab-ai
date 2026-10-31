"""Deterministic, auditable model routing for the orchestrator gateway.

Routing is a first-match rule table over request features (model alias, task class, tool use,
prompt size, prompt complexity) that selects a *pool* of workers plus an explicit fallback list.
Supports smart multi-factor optimization (EWMA latency, cost, load) and circuit breaker fast failover.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .circuit_breaker import CircuitBreakerRegistry
from .reasoning import RoutePolicy
from .smart_router import CostModel, LatencyTracker, PromptComplexityAnalyzer, ComplexityReport

MATCH_KEYS = {
    "model", "task_class", "has_tools", "min_prompt_tokens", "max_prompt_tokens",
    "attempt_gte", "previous_outcome", "min_complexity", "max_complexity", "complexity_tier",
}
RULE_KEYS = {
    "id", "match", "pool", "fallback", "reasoning", "fallback_on_saturation",
    "canary", "shadow", "evidence", "strategy", "cost_weight", "max_queue_wait_ms",
}
OUTCOMES = ("pass", "fail", "partial")
COMPLEXITY_TIERS = ("simple", "medium", "complex")
ROUTING_STRATEGIES = ("first_match", "least_latency", "least_busy", "cost_optimized")


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
    attempt_gte: int | None = None
    previous_outcomes: frozenset[str] | None = None
    min_complexity: float | None = None
    max_complexity: float | None = None
    complexity_tiers: frozenset[str] | None = None
    strategy: str = "first_match"
    cost_weight: float = 1.0
    policy: RoutePolicy = field(default_factory=RoutePolicy)
    fallback_on_saturation: bool = False
    max_queue_wait_ms: int | None = None
    canary: tuple[str, float] | None = None
    shadow: tuple[str, float] | None = None
    evidence: tuple[str, ...] = ()

    def unconditional(self) -> bool:
        return (
            self.models, self.task_classes, self.has_tools, self.min_prompt_tokens, self.max_prompt_tokens,
            self.attempt_gte, self.previous_outcomes, self.min_complexity, self.max_complexity,
            self.complexity_tiers
        ) == (None,) * 10

    def matches(
        self,
        *,
        model: str | None,
        task_class: str | None,
        has_tools: bool,
        prompt_tokens: int,
        attempt: int = 1,
        previous_outcome: str | None = None,
        complexity_score: float | None = None,
        complexity_tier: str | None = None,
    ) -> bool:
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
        if self.attempt_gte is not None and attempt < self.attempt_gte:
            return False
        if self.previous_outcomes is not None and previous_outcome not in self.previous_outcomes:
            return False
        if self.min_complexity is not None:
            if complexity_score is None or complexity_score < self.min_complexity:
                return False
        if self.max_complexity is not None:
            if complexity_score is None or complexity_score > self.max_complexity:
                return False
        if self.complexity_tiers is not None:
            if complexity_tier is None or complexity_tier not in self.complexity_tiers:
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
        if self.attempt_gte is not None:
            match["attempt_gte"] = self.attempt_gte
        if self.previous_outcomes is not None:
            match["previous_outcome"] = sorted(self.previous_outcomes)
        if self.min_complexity is not None:
            match["min_complexity"] = self.min_complexity
        if self.max_complexity is not None:
            match["max_complexity"] = self.max_complexity
        if self.complexity_tiers is not None:
            match["complexity_tier"] = sorted(self.complexity_tiers)
        out: dict[str, Any] = {
            "id": self.rule_id,
            "match": match,
            "pool": self.pool,
            "fallback": list(self.fallback),
            "reasoning": self.policy.describe(),
            "fallback_on_saturation": self.fallback_on_saturation,
            "strategy": self.strategy,
        }
        if self.max_queue_wait_ms is not None:
            out["max_queue_wait_ms"] = self.max_queue_wait_ms
        if self.canary:
            out["canary"] = {"pool": self.canary[0], "percent": self.canary[1]}
        if self.shadow:
            out["shadow"] = {"pool": self.shadow[0], "percent": self.shadow[1]}
        if self.evidence:
            out["evidence"] = list(self.evidence)
        return out


@dataclass(frozen=True)
class Alias:
    """An explicit pool choice by model name. ``scope`` restricts who may use it (candidate aliases: qualification)."""

    pool: str
    policy: RoutePolicy = field(default_factory=RoutePolicy)
    scope: str = "workload"


@dataclass(frozen=True)
class RouteDecision:
    rule_id: str
    pool: str
    fallback: tuple[str, ...]
    reason: str
    policy: RoutePolicy = field(default_factory=RoutePolicy)
    fallback_on_saturation: bool = False
    max_queue_wait_ms: int | None = None
    canary: tuple[str, float] | None = None
    shadow: tuple[str, float] | None = None
    scope: str = "workload"
    strategy: str = "first_match"
    complexity: ComplexityReport | None = None

    @property
    def pools(self) -> tuple[str, ...]:
        return (self.pool, *self.fallback)


def _strings(value: Any, field: str, rule_id: str) -> frozenset[str]:
    items = [value] if isinstance(value, str) else value
    if not isinstance(items, list) or not items or not all(isinstance(i, str) and i for i in items):
        raise RouteConfigError(f"rule '{rule_id}': '{field}' must be a non-empty string or list of strings")
    return frozenset(items)


def _split(value: Any, key: str, rule_id: str) -> tuple[str, float] | None:
    if value is None:
        return None
    if not isinstance(value, dict) or not isinstance(value.get("pool"), str) or not value["pool"]:
        raise RouteConfigError(f"rule '{rule_id}': '{key}' must be {{pool, percent}}")
    percent = value.get("percent")
    if isinstance(percent, bool) or not isinstance(percent, (int, float)) or not 0 < percent <= 100:
        raise RouteConfigError(f"rule '{rule_id}': '{key}.percent' must be in (0, 100]")
    return value["pool"], float(percent)


def _policy(raw: Any, where: str) -> RoutePolicy:
    try:
        return RoutePolicy.from_config(raw)
    except (ValueError, TypeError) as error:
        raise RouteConfigError(f"{where}: {error}") from error


def _int(value: Any, field: str, rule_id: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise RouteConfigError(f"rule '{rule_id}': '{field}' must be a non-negative integer")
    return value


def _float_range(value: Any, field: str, rule_id: str, low: float = 0.0, high: float = 1.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not (low <= float(value) <= high):
        raise RouteConfigError(f"rule '{rule_id}': '{field}' must be a number between {low} and {high}")
    return float(value)


class Router:
    """First-match rule table with multi-factor optimization and circuit breaker failover."""

    def __init__(
        self,
        rules: list[RouteRule],
        aliases: dict[str, str] | None = None,
        *,
        circuit_breakers: CircuitBreakerRegistry | None = None,
        latency_tracker: LatencyTracker | None = None,
        cost_model: CostModel | None = None,
    ) -> None:
        if not rules:
            raise RouteConfigError("route table must contain at least one rule")
        ids = [r.rule_id for r in rules]
        if len(set(ids)) != len(ids):
            raise RouteConfigError("route rule ids must be unique")
        if not rules[-1].unconditional():
            raise RouteConfigError("the last route rule must be an unconditional default (empty match)")
        self.rules = tuple(rules)
        self.alias_specs: dict[str, Alias] = {}
        for name, spec in (aliases or {}).items():
            self.alias_specs[name] = spec if isinstance(spec, Alias) else Alias(spec)
        # name -> pool, kept for callers that only need the mapping
        self.aliases = {name: spec.pool for name, spec in self.alias_specs.items()}
        self.circuit_breakers = circuit_breakers
        self.latency_tracker = latency_tracker or LatencyTracker()
        self.cost_model = cost_model or CostModel()

    def update_rules(self, rules: list[RouteRule], aliases: dict[str, str] | None = None) -> None:
        """Atomically update rules and aliases while preserving tracker and circuit breaker state."""
        if not rules:
            raise RouteConfigError("route table must contain at least one rule")
        ids = [r.rule_id for r in rules]
        if len(set(ids)) != len(ids):
            raise RouteConfigError("route rule ids must be unique")
        if not rules[-1].unconditional():
            raise RouteConfigError("the last route rule must be an unconditional default (empty match)")
        new_alias_specs: dict[str, Alias] = {}
        for name, spec in (aliases or {}).items():
            new_alias_specs[name] = spec if isinstance(spec, Alias) else Alias(spec)
        self.rules = tuple(rules)
        self.alias_specs = new_alias_specs
        self.aliases = {name: spec.pool for name, spec in new_alias_specs.items()}

    @classmethod
    def from_config(
        cls,
        rules_cfg: Any,
        aliases: Any = None,
        *,
        circuit_breakers: CircuitBreakerRegistry | None = None,
        latency_tracker: LatencyTracker | None = None,
        cost_model: CostModel | None = None,
    ) -> "Router":
        if not isinstance(rules_cfg, list):
            raise RouteConfigError("routes must be a list of rules")
        parsed_aliases: dict[str, Alias] = {}
        if aliases is not None:
            if not isinstance(aliases, dict):
                raise RouteConfigError("aliases must map model names to pool names")
            for name, spec in aliases.items():
                if not isinstance(name, str) or not name:
                    raise RouteConfigError("alias names must be non-empty strings")
                if isinstance(spec, str) and spec:
                    parsed_aliases[name] = Alias(spec)
                elif isinstance(spec, dict) and isinstance(spec.get("pool"), str) and spec["pool"]:
                    scope = spec.get("scope", "workload")
                    if scope not in ("workload", "qualification"):
                        raise RouteConfigError(f"alias '{name}': scope must be workload|qualification")
                    parsed_aliases[name] = Alias(spec["pool"], _policy(spec.get("reasoning"), f"alias '{name}'"), scope)
                else:
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
            attempt_gte = _int(match["attempt_gte"], "attempt_gte", rule_id) if "attempt_gte" in match else None
            previous = _strings(match["previous_outcome"], "previous_outcome", rule_id) if "previous_outcome" in match else None
            if previous is not None and not previous <= set(OUTCOMES):
                raise RouteConfigError(f"rule '{rule_id}': previous_outcome must be within {list(OUTCOMES)}")

            min_complexity = _float_range(match["min_complexity"], "min_complexity", rule_id) if "min_complexity" in match else None
            max_complexity = _float_range(match["max_complexity"], "max_complexity", rule_id) if "max_complexity" in match else None
            if min_complexity is not None and max_complexity is not None and min_complexity > max_complexity:
                raise RouteConfigError(f"rule '{rule_id}': min_complexity exceeds max_complexity")

            complexity_tiers = _strings(match["complexity_tier"], "complexity_tier", rule_id) if "complexity_tier" in match else None
            if complexity_tiers is not None and not complexity_tiers <= set(COMPLEXITY_TIERS):
                raise RouteConfigError(f"rule '{rule_id}': complexity_tier must be within {list(COMPLEXITY_TIERS)}")

            strategy = raw.get("strategy", "first_match")
            if strategy not in ROUTING_STRATEGIES:
                raise RouteConfigError(f"rule '{rule_id}': strategy must be one of {list(ROUTING_STRATEGIES)}")

            cost_weight = float(raw.get("cost_weight", 1.0))
            saturation = raw.get("fallback_on_saturation", False)
            if not isinstance(saturation, bool):
                raise RouteConfigError(f"rule '{rule_id}': 'fallback_on_saturation' must be a boolean")
            queue_wait = raw.get("max_queue_wait_ms")
            if queue_wait is not None and (isinstance(queue_wait, bool) or not isinstance(queue_wait, int) or not 1 <= queue_wait <= 120000):
                raise RouteConfigError(f"rule '{rule_id}': max_queue_wait_ms must be an integer from 1 to 120000")
            evidence = raw.get("evidence", [])
            if not isinstance(evidence, list) or not all(isinstance(e, str) and e for e in evidence):
                raise RouteConfigError(f"rule '{rule_id}': 'evidence' must be a list of evidence ids")
            lo = _int(match["min_prompt_tokens"], "min_prompt_tokens", rule_id) if "min_prompt_tokens" in match else None
            hi = _int(match["max_prompt_tokens"], "max_prompt_tokens", rule_id) if "max_prompt_tokens" in match else None
            if lo is not None and hi is not None and lo > hi:
                raise RouteConfigError(f"rule '{rule_id}': min_prompt_tokens exceeds max_prompt_tokens")
            rules.append(RouteRule(
                rule_id=rule_id, pool=pool, fallback=tuple(fallback),
                models=_strings(match["model"], "model", rule_id) if "model" in match else None,
                task_classes=_strings(match["task_class"], "task_class", rule_id) if "task_class" in match else None,
                has_tools=has_tools, min_prompt_tokens=lo, max_prompt_tokens=hi,
                attempt_gte=attempt_gte, previous_outcomes=previous,
                min_complexity=min_complexity, max_complexity=max_complexity, complexity_tiers=complexity_tiers,
                strategy=strategy, cost_weight=cost_weight, max_queue_wait_ms=queue_wait,
                policy=_policy(raw.get("reasoning"), f"rule '{rule_id}'"), fallback_on_saturation=saturation,
                canary=_split(raw.get("canary"), "canary", rule_id), shadow=_split(raw.get("shadow"), "shadow", rule_id),
                evidence=tuple(evidence),
            ))
        return cls(rules, parsed_aliases, circuit_breakers=circuit_breakers, latency_tracker=latency_tracker, cost_model=cost_model)

    def referenced_pools(self) -> set[str]:
        pools = set(self.aliases.values())
        for rule in self.rules:
            pools.add(rule.pool)
            pools.update(rule.fallback)
            for split in (rule.canary, rule.shadow):
                if split:
                    pools.add(split[0])
        return pools

    def decide(
        self,
        *,
        model: str | None,
        task_class: str | None,
        has_tools: bool,
        prompt_tokens: int,
        attempt: int = 1,
        previous_outcome: str | None = None,
        request: dict[str, Any] | None = None,
        complexity_score: float | None = None,
    ) -> RouteDecision:
        # A model name that is an alias for a pool is an explicit client choice and bypasses the table.
        if model is not None and model in self.alias_specs:
            spec = self.alias_specs[model]
            return RouteDecision(f"alias:{model}", spec.pool, (), f"model alias '{model}'", spec.policy, scope=spec.scope)

        # 1. Compute complexity report if request or score is available
        complexity: ComplexityReport | None = None
        if request is not None:
            complexity = PromptComplexityAnalyzer.analyze(request, prompt_tokens)
        elif complexity_score is not None:
            tier = "simple" if complexity_score < 0.3 else ("medium" if complexity_score < 0.7 else "complex")
            complexity = ComplexityReport(score=complexity_score, tier=tier)

        c_score = complexity.score if complexity else None
        c_tier = complexity.tier if complexity else None

        for rule in self.rules:
            if rule.matches(
                model=model,
                task_class=task_class,
                has_tools=has_tools,
                prompt_tokens=prompt_tokens,
                attempt=attempt,
                previous_outcome=previous_outcome,
                complexity_score=c_score,
                complexity_tier=c_tier,
            ):
                target_pool = rule.pool
                fallback_pools = list(rule.fallback)
                reason = f"matched rule '{rule.rule_id}'"

                # 2. Circuit Breaker Fast-Failover: if target pool is OPEN, immediately promote first healthy fallback
                if self.circuit_breakers is not None and not self.circuit_breakers.is_pool_available(target_pool):
                    available_fallback = None
                    for fb in fallback_pools:
                        if self.circuit_breakers.is_pool_available(fb):
                            available_fallback = fb
                            break
                    if available_fallback:
                        fallback_pools.remove(available_fallback)
                        fallback_pools.append(target_pool)
                        reason = f"matched rule '{rule.rule_id}' (pool '{target_pool}' circuit breaker open; fast failover to '{available_fallback}')"
                        target_pool = available_fallback

                # 3. Strategy Optimization
                if rule.strategy == "least_latency" and self.latency_tracker is not None:
                    # Sort available pools by EWMA duration
                    all_candidate_pools = [target_pool, *fallback_pools]
                    if self.circuit_breakers is not None:
                        healthy_candidates = [p for p in all_candidate_pools if self.circuit_breakers.is_pool_available(p)]
                    else:
                        healthy_candidates = all_candidate_pools

                    if healthy_candidates:
                        healthy_candidates.sort(key=lambda p: self.latency_tracker.pool_duration(p))
                        best_pool = healthy_candidates[0]
                        if best_pool != target_pool:
                            fallback_pools = [p for p in all_candidate_pools if p != best_pool]
                            target_pool = best_pool
                            reason += f"; optimized for least latency ({self.latency_tracker.pool_duration(best_pool)*1000:.0f}ms)"

                elif rule.strategy == "cost_optimized" and self.cost_model is not None and complexity is not None:
                    # For simple tasks, prefer the lower-cost pool
                    if complexity.tier == "simple":
                        all_candidate_pools = [target_pool, *fallback_pools]
                        all_candidate_pools.sort(key=lambda p: self.cost_model.cost_weight(p))
                        cheapest_pool = all_candidate_pools[0]
                        if cheapest_pool != target_pool:
                            fallback_pools = [p for p in all_candidate_pools if p != cheapest_pool]
                            target_pool = cheapest_pool
                            reason += f"; optimized for cost (simple tier task routed to '{cheapest_pool}')"

                return RouteDecision(
                    rule_id=rule.rule_id,
                    pool=target_pool,
                    fallback=tuple(fallback_pools),
                    reason=reason,
                    policy=rule.policy,
                    fallback_on_saturation=rule.fallback_on_saturation,
                    max_queue_wait_ms=rule.max_queue_wait_ms,
                    canary=rule.canary,
                    shadow=rule.shadow,
                    strategy=rule.strategy,
                    complexity=complexity,
                )

        raise RouteConfigError("no route rule matched")  # unreachable: the last rule is unconditional

    def describe(self) -> dict[str, Any]:
        aliases = {name: {"pool": a.pool, "scope": a.scope, "reasoning": a.policy.describe()} for name, a in self.alias_specs.items()}
        res: dict[str, Any] = {
            "aliases": aliases,
            "rules": [r.describe() for r in self.rules],
        }
        if self.circuit_breakers is not None:
            res["circuit_breakers"] = self.circuit_breakers.snapshot()
        if self.latency_tracker is not None:
            res["latency"] = self.latency_tracker.snapshot()
        return res
