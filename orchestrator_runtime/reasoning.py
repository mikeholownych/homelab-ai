"""Bounded reasoning (Design 02 / R8): one mechanism, layered, monotonic, fail closed.

L1 the worker's hard ``--reasoning-budget`` (inventory, rendered into the worker unit) always applies.
L2 the route policy picks thinking on/off and a budget within the worker cap; a client profile may only lower it.
L3 the total generation bound (budget + answer allowance) applies to every request, including ones with no max_tokens.
L4 every completion is classified (reasoning budget exhausted, output limit, normal stop, ...) for telemetry.
Every layer takes min(); a client can ask for less, never more, and attempts to raise are overwritten and evidenced.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

DEFAULT_BUDGET_MESSAGE = "Reasoning budget exhausted. Stop reasoning now and write the final answer in the required format."
# Client reasoning profiles map to a fraction of the route budget (off = no thinking at all).
PROFILES = {"off": 0.0, "low": 0.25, "standard": 0.5, "max": 1.0}
_BUDGET_FIELDS = ("thinking_budget_tokens", "reasoning_budget_tokens")


class ProfileError(ValueError):
    pass


@dataclass(frozen=True)
class RoutePolicy:
    """Reasoning/output policy of a route. ``mode`` on|off|default (default = model template default)."""

    mode: str = "default"
    budget: int = 0
    answer_allowance: int = 8192

    @classmethod
    def from_config(cls, raw: Any, *, default_answer_allowance: int = 8192) -> "RoutePolicy":
        if raw is None:
            return cls(answer_allowance=default_answer_allowance)
        if not isinstance(raw, dict):
            raise ValueError("route reasoning policy must be an object")
        mode = raw.get("mode", "default")
        if mode not in ("on", "off", "default"):
            raise ValueError(f"reasoning mode must be on|off|default, got {mode!r}")
        budget = int(raw.get("budget", 0))
        allowance = int(raw.get("answer_allowance", default_answer_allowance))
        if budget < 0 or allowance < 1:
            raise ValueError("reasoning budget must be >= 0 and answer_allowance >= 1")
        if mode == "on" and budget < 1:
            raise ValueError("reasoning mode 'on' requires a positive budget")
        return cls(mode, budget, allowance)

    def describe(self) -> dict[str, Any]:
        return {"mode": self.mode, "budget": self.budget, "answer_allowance": self.answer_allowance}


@dataclass(frozen=True)
class AppliedReasoning:
    request: dict[str, Any]
    thinking: bool
    budget: int
    output_cap: int
    clamped: tuple[str, ...]


def apply(request: dict[str, Any], policy: RoutePolicy, *, worker_cap: int | None, worker_reasons: bool,
          profile: str | None) -> AppliedReasoning:
    """Rewrite the request's reasoning controls to the effective (monotonic) policy and return the output cap."""
    if profile is not None and profile not in PROFILES:
        raise ProfileError(f"unknown reasoning profile {profile!r}; use one of {sorted(PROFILES)}")
    clamped: list[str] = []
    out = dict(request)
    kwargs = dict(out["chat_template_kwargs"]) if isinstance(out.get("chat_template_kwargs"), dict) else {}

    # Effective budget: route budget (or the worker cap when the route leaves it to the model), never above the
    # worker's hard cap, scaled down by the client's profile.
    budget = 0
    if worker_reasons:
        budget = policy.budget or (worker_cap or 0)
        if worker_cap is not None:
            budget = min(budget, worker_cap)
        if profile is not None:
            budget = int(budget * PROFILES[profile])
    thinking = worker_reasons and policy.mode != "off" and profile != "off" and budget > 0

    # A client may ask for a smaller budget than the effective one (honoured), never a larger one (overwritten).
    requested = [out.get(name) for name in _BUDGET_FIELDS if isinstance(out.get(name), int) and not isinstance(out.get(name), bool)]
    if thinking and requested:
        lowest = min(requested)
        if lowest > budget:
            clamped.append("reasoning_budget")
        elif lowest >= 0:
            budget = lowest
            thinking = budget > 0
    elif requested and any(r > 0 for r in requested):
        clamped.append("reasoning_budget")
    if kwargs.get("enable_thinking") is True and not thinking:
        clamped.append("enable_thinking")

    if worker_reasons:
        kwargs["enable_thinking"] = thinking
    else:
        kwargs.pop("enable_thinking", None)
    if kwargs:
        out["chat_template_kwargs"] = kwargs
    else:
        out.pop("chat_template_kwargs", None)
    for name in _BUDGET_FIELDS:
        if thinking:
            out[name] = budget
        else:
            out.pop(name, None)
    effective_budget = budget if thinking else 0
    return AppliedReasoning(out, thinking, effective_budget, effective_budget + policy.answer_allowance, tuple(clamped))


def classify(output: dict[str, Any], *, budget: int, budget_message: str = DEFAULT_BUDGET_MESSAGE,
             reasoning_tokens: int | None = None) -> tuple[str, bool]:
    """(termination class, reasoning_budget_exhausted) for a completed provider call."""
    finish = output.get("provider_finish_reason")
    reasoning = output.get("reasoning_content") or ""
    exhausted = bool(budget) and (
        (budget_message and budget_message in reasoning)
        or (reasoning_tokens is not None and reasoning_tokens >= budget)
    )
    if finish == "length":
        return "output_limit", exhausted
    if output.get("tool_calls"):
        return "tool_calls", exhausted
    return "stop", exhausted
