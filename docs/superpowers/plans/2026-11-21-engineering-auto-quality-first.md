# Engineering/Auto Quality-First Routing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clients call `engineering/auto` (or omit model) on the ai-5820-01 gateway and get quality-first routing across lead/deep/rocm with ordered failover; pins stay hard; MS-S1 gets vllm-top; obs gaps verified.

**Architecture:** Add a `quality_first` strategy to `Router.decide` that ranks the rule’s candidate pools (primary + fallbacks) by request-shape fit, then pool quality weight, then EWMA latency, skipping open circuit breakers. Inventory adds an `engineering-auto` rule only (does not widen the catch-all default). Normalize omitted/empty model to `engineering/auto` inside `Router.decide`.

**Tech Stack:** Python (`orchestrator_runtime`), Ansible inventory, JSON Schema, Grafana dashboard builder, pytest, gateway release pin.

**Spec:** `docs/superpowers/specs/2026-11-21-engineering-auto-quality-first-design.md`

**Plan-locked names:**

| Item | Value |
| --- | --- |
| Route id | `engineering-auto` |
| Strategy | `quality_first` |
| Match model | `engineering/auto` |
| Candidate pools | `lead` primary; fallback `[deep, rocm]` (reordered at decide time) |
| Quality env | `ORCHESTRATOR_POOL_QUALITY_WEIGHTS` |
| Default weights | `lead: 2.0`, `deep: 3.0`, `rocm: 2.5` |

---

## File Map

| Path | Responsibility |
| --- | --- |
| `orchestrator_runtime/smart_router.py` | `QualityModel` + `preferred_pool_order` / rank helper |
| `orchestrator_runtime/routing.py` | `quality_first` in strategies + decide branch; omit→auto normalize |
| `schemas/gateway-routes.schema.json` | Allow `quality_first` in strategy enum |
| `tests/test_smart_gateway_enterprise.py` | Unit tests for ranking / failover / pins |
| `tests/test_ms_s1_max_promotion_contract.py` | Auto rule + pin contracts; allow rocm only on auto |
| `inventory/production/host_vars/ai-5820-01.yml` | Route + weights + release bump |
| `inventory/production/host_vars/ai-ms-s1-max-01.yml` | `vllm_top_console_enabled: true` |
| `roles/orchestrator_gateway/templates/gateway.env.j2` | Export quality weights |
| `orchestrator_gateway/__main__.py` | Pass quality weights into Router |
| `observability/tools/build_dashboards.py` (+ rebuild JSON/j2) | Confirm/add rocm-visible route panels if idle fallbacks omit rocm |
| `docs/commissioning.md` | Short client note for `engineering/auto` |

---

### Task 1: Failing tests for `quality_first` ranking

**Files:**
- Modify: `tests/test_smart_gateway_enterprise.py`
- Modify: `schemas/gateway-routes.schema.json` (enum only — needed so schema tests don’t block later)

- [ ] **Step 1: Add failing unit tests**

Append to `tests/test_smart_gateway_enterprise.py`:

```python
from orchestrator_runtime.smart_router import QualityModel, preferred_pool_order
from orchestrator_runtime.smart_router import PromptComplexityAnalyzer, LatencyTracker
from orchestrator_runtime import Router
from orchestrator_runtime.circuit_breaker import CircuitBreakerRegistry


AUTO_RULES = [
    {
        "id": "engineering-auto",
        "match": {"model": ["engineering/auto"]},
        "pool": "lead",
        "fallback": ["deep", "rocm"],
        "strategy": "quality_first",
        "fallback_on_saturation": True,
        "reasoning": {"mode": "off", "answer_allowance": 8192},
    },
    {"id": "default", "match": {}, "pool": "lead", "fallback": ["deep"]},
]
AUTO_ALIASES = {
    "engineering/lead": {"pool": "lead", "reasoning": {"mode": "off", "answer_allowance": 8192}},
    "engineering/deep": {"pool": "deep", "reasoning": {"mode": "on", "budget": 4096, "answer_allowance": 8192}},
    "engineering/interactive-rocm": {"pool": "rocm", "reasoning": {"mode": "off", "answer_allowance": 8192}},
}


def test_quality_first_strategy_is_accepted():
    Router.from_config(AUTO_RULES, AUTO_ALIASES)


def test_omitted_model_normalizes_to_engineering_auto():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    d = router.decide(model=None, task_class=None, has_tools=False, prompt_tokens=20,
                      request={"messages": [{"role": "user", "content": "hi"}]})
    assert d.rule_id == "engineering-auto"


def test_quality_first_prefers_deep_for_complex_reasoning():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    req = {"messages": [{"role": "user", "content": "step-by-step analyze root cause of this architecture deadlock"}]}
    d = router.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=800, request=req)
    assert d.pool == "deep"
    assert d.fallback[0:2] == ("lead", "rocm") or set(d.fallback) == {"lead", "rocm"}
    assert "quality_first" in d.reason or "quality first" in d.reason.lower()


def test_quality_first_prefers_rocm_for_code_tools():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    req = {
        "messages": [{"role": "user", "content": "```python\ndef foo():\n    pass\n``` fix this function"}],
        "tools": [{"type": "function", "function": {"name": "read_file", "parameters": {}}}],
    }
    d = router.decide(model="engineering/auto", task_class=None, has_tools=True, prompt_tokens=400, request=req)
    assert d.pool == "rocm"
    assert "lead" in d.fallback and "deep" in d.fallback


def test_quality_first_prefers_lead_for_simple():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    req = {"messages": [{"role": "user", "content": "hi"}]}
    d = router.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=5, request=req)
    assert d.pool == "lead"


def test_quality_first_skips_open_circuit_breaker_then_failover_order():
    cbs = CircuitBreakerRegistry(worker_failure_threshold=2, pool_failure_threshold=2)
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES, circuit_breakers=cbs)
    cbs.record_failure("deep1", pool_name="deep", error="500")
    cbs.record_failure("deep1", pool_name="deep", error="500")
    assert not cbs.is_pool_available("deep")
    req = {"messages": [{"role": "user", "content": "step-by-step analyze root cause architecture"}]}
    d = router.decide(model="engineering/auto", task_class=None, has_tools=False, prompt_tokens=800, request=req)
    assert d.pool != "deep"
    assert d.pool in ("lead", "rocm")
    assert "deep" in d.fallback


def test_pin_aliases_still_bypass_quality_first():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    d = router.decide(model="engineering/interactive-rocm", task_class=None, has_tools=False, prompt_tokens=5)
    assert d.rule_id == "alias:engineering/interactive-rocm"
    assert d.pool == "rocm"
    assert d.fallback == ()


def test_unknown_model_does_not_use_engineering_auto_rule():
    router = Router.from_config(AUTO_RULES, AUTO_ALIASES)
    d = router.decide(model="engineering/other", task_class=None, has_tools=False, prompt_tokens=5,
                      request={"messages": [{"role": "user", "content": "hi"}]})
    assert d.rule_id == "default"
    assert d.pool == "lead"
    assert "rocm" not in d.fallback
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/pytest tests/test_smart_gateway_enterprise.py::test_quality_first_strategy_is_accepted tests/test_smart_gateway_enterprise.py::test_omitted_model_normalizes_to_engineering_auto tests/test_smart_gateway_enterprise.py::test_quality_first_prefers_deep_for_complex_reasoning -v`

Expected: FAIL (`quality_first` not in `ROUTING_STRATEGIES` and/or ImportError for `QualityModel`)

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_smart_gateway_enterprise.py
git commit -m "test: add failing coverage for quality_first auto routing"
```

---

### Task 2: Implement `QualityModel` and preferred order

**Files:**
- Modify: `orchestrator_runtime/smart_router.py`

- [ ] **Step 1: Add helpers after `CostModel`**

```python
class QualityModel:
    """Relative quality weights (higher = stronger). Used as a tie-breaker inside a fit band."""

    DEFAULT_POOL_QUALITY = {
        "lead": 2.0,
        "deep": 3.0,
        "rocm": 2.5,
        "aux": 1.0,
        "candidate": 1.0,
    }

    def __init__(self, pool_weights: dict[str, float] | None = None) -> None:
        self.weights = dict(self.DEFAULT_POOL_QUALITY)
        if pool_weights:
            self.weights.update({k: float(v) for k, v in pool_weights.items()})

    def quality_weight(self, pool: str) -> float:
        return float(self.weights.get(pool, 1.0))


def preferred_pool_order(
    complexity: ComplexityReport | None,
    *,
    has_tools: bool,
) -> list[str]:
    """Fleet fit order for lead/deep/rocm (spec Section 2). Lower index = better fit."""
    if complexity is None:
        return ["lead", "rocm", "deep"]
    factors = complexity.factors or {}
    reasoning = float(factors.get("reasoning_score", 0.0) or 0.0)
    code = float(factors.get("code_score", 0.0) or 0.0)
    if complexity.tier == "complex" or reasoning >= 0.3:
        return ["deep", "lead", "rocm"]
    if has_tools or code >= 0.2:
        return ["rocm", "lead", "deep"]
    return ["lead", "rocm", "deep"]


def quality_first_rank_key(
    pool: str,
    *,
    order: list[str],
    quality: QualityModel,
    latency_tracker: LatencyTracker | None,
) -> tuple:
    try:
        fit = order.index(pool)
    except ValueError:
        fit = len(order)
    # Ascending: better fit first; higher quality weight wins ties; lower latency wins remaining ties.
    latency = latency_tracker.pool_duration(pool) if latency_tracker is not None else 1.0
    return (fit, -quality.quality_weight(pool), latency)
```

Ensure `ComplexityReport` is already imported/defined above in the same module.

- [ ] **Step 2: Run a tiny import check**

Run: `.venv/bin/python -c "from orchestrator_runtime.smart_router import QualityModel, preferred_pool_order; print(preferred_pool_order(None, has_tools=False))"`

Expected: `['lead', 'rocm', 'deep']`

- [ ] **Step 3: Commit**

```bash
git add orchestrator_runtime/smart_router.py
git commit -m "feat(router): add QualityModel and preferred pool order helpers"
```

---

### Task 3: Wire `quality_first` into `Router.decide`

**Files:**
- Modify: `orchestrator_runtime/routing.py`
- Modify: `schemas/gateway-routes.schema.json`

- [ ] **Step 1: Extend imports and constants**

In `routing.py`:

```python
from .smart_router import (
    CostModel,
    LatencyTracker,
    PromptComplexityAnalyzer,
    ComplexityReport,
    QualityModel,
    preferred_pool_order,
    quality_first_rank_key,
)

ROUTING_STRATEGIES = ("first_match", "least_latency", "least_busy", "cost_optimized", "quality_first")
```

In `Router.__init__`, after `self.cost_model = ...`:

```python
self.quality_model = quality_model or QualityModel()
```

Add parameter `quality_model: QualityModel | None = None` to `__init__` and `from_config`, pass through like `cost_model`.

In `schemas/gateway-routes.schema.json` strategy enum, add `"quality_first"`.

- [ ] **Step 2: Normalize omitted model + implement strategy branch**

At the start of `decide`, after the signature:

```python
if model is None or (isinstance(model, str) and not model.strip()):
    model = "engineering/auto"
```

Keep alias bypass **after** this normalization (pins are never empty).

After the existing `cost_optimized` branch, add:

```python
elif rule.strategy == "quality_first":
    all_candidate_pools = [target_pool, *fallback_pools]
    if self.circuit_breakers is not None:
        healthy = [p for p in all_candidate_pools if self.circuit_breakers.is_pool_available(p)]
        unhealthy = [p for p in all_candidate_pools if p not in healthy]
    else:
        healthy, unhealthy = list(all_candidate_pools), []
    order = preferred_pool_order(complexity, has_tools=has_tools)
    healthy.sort(
        key=lambda p: quality_first_rank_key(
            p,
            order=order,
            quality=self.quality_model,
            latency_tracker=self.latency_tracker,
        )
    )
    ranked = healthy + unhealthy
    if ranked:
        target_pool = ranked[0]
        fallback_pools = ranked[1:]
        reason += f"; optimized for quality_first (fit order {order})"
```

- [ ] **Step 3: Run the new unit tests**

Run: `.venv/bin/pytest tests/test_smart_gateway_enterprise.py -k "quality_first or omitted_model or pin_aliases_still or unknown_model_does_not" -v`

Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add orchestrator_runtime/routing.py schemas/gateway-routes.schema.json tests/test_smart_gateway_enterprise.py
git commit -m "feat(router): implement quality_first strategy for engineering/auto"
```

---

### Task 4: Inventory contract tests for 5820 auto rule

**Files:**
- Modify: `tests/test_ms_s1_max_promotion_contract.py`

- [ ] **Step 1: Update the “no Intel fallback to rocm” assertion and add auto contract**

Replace the loop that forbids rocm in every non-`interactive-rocm` fallback with:

```python
    for route in routes.values():
        if route["id"] in ("interactive-rocm", "engineering-auto"):
            continue
        assert "rocm" not in route.get("fallback", []), route["id"]
```

Add:

```python
def test_5820_engineering_auto_quality_first_across_peers():
    hv = load("inventory/production/host_vars/ai-5820-01.yml")
    routes = {r["id"]: r for r in hv["orchestrator_gateway_routes"]}
    auto = routes["engineering-auto"]
    assert auto["match"] == {"model": ["engineering/auto"]}
    assert auto["strategy"] == "quality_first"
    assert auto["pool"] == "lead"
    assert set(auto["fallback"]) == {"deep", "rocm"}
    assert auto.get("fallback_on_saturation") is True
    ids = [r["id"] for r in hv["orchestrator_gateway_routes"]]
    assert ids.index("engineering-auto") < ids.index("default")
    # Pins unchanged and not aliases for auto
    aliases = hv["orchestrator_gateway_model_aliases"]
    assert "engineering/auto" not in aliases
    for name in ("engineering/lead", "engineering/deep", "engineering/lead-reasoning", "engineering/interactive-rocm"):
        assert name in aliases
    assert hv["orchestrator_gateway_pool_quality_weights"] == {
        "lead": 2.0, "deep": 3.0, "rocm": 2.5,
    }
```

Also change `test_ms_s1_monitoring_matches_the_5820_peer_subset` so vllm-top is expected on:

```python
    assert hv.get("vllm_top_console_enabled") is True
```

- [ ] **Step 2: Run contract tests (expect fail on missing inventory)**

Run: `.venv/bin/pytest tests/test_ms_s1_max_promotion_contract.py::test_5820_engineering_auto_quality_first_across_peers tests/test_ms_s1_max_promotion_contract.py::test_5820_advertises_ms_s1_rocm_worker_as_parallel_alias tests/test_ms_s1_max_promotion_contract.py::test_ms_s1_monitoring_matches_the_5820_peer_subset -v`

Expected: FAIL (no `engineering-auto` route; vllm-top still false)

- [ ] **Step 3: Commit tests**

```bash
git add tests/test_ms_s1_max_promotion_contract.py
git commit -m "test: contract engineering/auto quality_first and MS-S1 vllm-top"
```

---

### Task 5: Inventory + gateway env wiring

**Files:**
- Modify: `inventory/production/host_vars/ai-5820-01.yml`
- Modify: `inventory/production/host_vars/ai-ms-s1-max-01.yml`
- Modify: `roles/orchestrator_gateway/templates/gateway.env.j2`
- Modify: `roles/orchestrator_gateway/defaults/main.yml`
- Modify: `orchestrator_gateway/__main__.py`

- [ ] **Step 1: Add route and weights on 5820**

In `ai-5820-01.yml`, **before** the `default` route (and after `interactive-rocm` is fine), insert:

```yaml
  - id: engineering-auto
    match: {model: [engineering/auto]}
    pool: lead
    fallback: [deep, rocm]
    strategy: quality_first
    fallback_on_saturation: true
    reasoning: {mode: "off", answer_allowance: 8192}
```

Near gateway vars (after aliases or workers), add:

```yaml
orchestrator_gateway_pool_quality_weights:
  lead: 2.0
  deep: 3.0
  rocm: 2.5
```

Do **not** add `engineering/auto` to `orchestrator_gateway_model_aliases`.

- [ ] **Step 2: Enable vllm-top on MS-S1**

In `ai-ms-s1-max-01.yml`:

```yaml
vllm_top_console_enabled: true
```

- [ ] **Step 3: Template + defaults + loader**

`roles/orchestrator_gateway/defaults/main.yml`:

```yaml
orchestrator_gateway_pool_quality_weights: {}
```

`gateway.env.j2` (after aliases line):

```jinja
ORCHESTRATOR_POOL_QUALITY_WEIGHTS={{ orchestrator_gateway_pool_quality_weights | default({}) | to_json(separators=(',', ':')) }}
```

In `orchestrator_gateway/__main__.py` `load_router`:

```python
from orchestrator_runtime.smart_router import QualityModel

quality_raw = os.environ.get("ORCHESTRATOR_POOL_QUALITY_WEIGHTS", "{}")
quality_model = QualityModel(json.loads(quality_raw) if quality_raw else None)
router = Router.from_config(
    json.loads(raw_routes),
    json.loads(os.environ.get("ORCHESTRATOR_MODEL_ALIASES", "{}")),
    quality_model=quality_model,
)
```

(Keep existing pool/candidate validation after construction.)

- [ ] **Step 4: Run contracts**

Run: `.venv/bin/pytest tests/test_ms_s1_max_promotion_contract.py -v`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add inventory/production/host_vars/ai-5820-01.yml inventory/production/host_vars/ai-ms-s1-max-01.yml roles/orchestrator_gateway/templates/gateway.env.j2 roles/orchestrator_gateway/defaults/main.yml orchestrator_gateway/__main__.py
git commit -m "feat(gateway): wire engineering/auto quality_first and MS-S1 vllm-top"
```

---

### Task 6: Observability verify + dashboard idle fallback for rocm

**Files:**
- Modify: `observability/tools/build_dashboards.py` only if idle fallbacks hard-code `pool=lead`
- Run: `python3 observability/tools/build_dashboards.py` when templates change
- Read: `inventory/production/host_vars/grafana.yml` (confirm MS-S1 scrape still present)

- [ ] **Step 1: Confirm scrape + route panels**

Verify `grafana.yml` still has `observability_scrape_aihost_extra_targets` entry for `10.0.8.6:9100` / `ai-ms-s1-max-01`.

Inspect route-decision panel expr in `build_dashboards.py` — it already aggregates `sum by (rule, pool)`; with `aihost_worker_info` including `rocm`, duration panels that use `0 * sum by (pool) (aihost_worker_info)` already show rocm when the worker is registered. **No dashboard change required** unless a panel hard-codes only `lead`.

If any panel’s `or label_replace(..., "pool", "lead", ...)` is the sole idle series and hides multi-pool structure, leave it (idle placeholder only); do not invent new panels unless a gap is found.

- [ ] **Step 2: Document verification checklist in commissioning**

Add a short subsection to `docs/commissioning.md` under Phase 3 / client usage:

```markdown
### Client routing (engineering/auto)

- Front door: `ai-5820-01` gateway only.
- `model: "engineering/auto"` (or omit model) → quality-first among lead / deep / rocm.
- Pins: `engineering/lead`, `engineering/deep`, `engineering/lead-reasoning`, `engineering/interactive-rocm`.
- Confirm: Grafana scrapes MS-S1 `:9100`; vllm-top console enabled on both hosts; route decisions show rule `engineering-auto`.
```

- [ ] **Step 3: Commit if docs/dashboards changed**

```bash
git add docs/commissioning.md observability/grafana/dashboards/*.json roles/observability/templates/*.json.j2 observability/tools/build_dashboards.py
git commit -m "docs(obs): engineering/auto client routing and dual-host ops notes"
```

(Skip empty commit if only verification, no file changes.)

---

### Task 7: Gateway release bump + quality gate

**Files:**
- Modify: `inventory/production/host_vars/ai-5820-01.yml` (`orchestrator_gateway_release_id` + `orchestrator_gateway_release_dir`)
- Modify: `inventory/production/host_vars/ai-ms-s1-max-01.yml` (same commit SHA suffix if both ship the artifact — see `tests/test_gateway_release_identity.py` / commissioning note that both gateways share the artifact)

- [ ] **Step 1: Bump release ids to the commit that contains the router changes**

After Tasks 1–5 are on the branch tip:

```bash
SHA=$(git rev-parse HEAD)
# 5820
# orchestrator_gateway_release_id: t5820-gateway-$SHA
# orchestrator_gateway_release_dir: /var/lib/aihost/releases/t5820-gateway-$SHA
# MS-S1
# orchestrator_gateway_release_id: ms-s1-gateway-$SHA
# orchestrator_gateway_release_dir: /var/lib/aihost/releases/ms-s1-gateway-$SHA
```

- [ ] **Step 2: Run targeted gates**

```bash
.venv/bin/pytest tests/test_smart_gateway_enterprise.py tests/test_orchestrator_routing.py tests/test_ms_s1_max_promotion_contract.py tests/test_gateway_release_identity.py -q
# If present and fast enough:
scripts/check-gateway-quality || .venv/bin/pytest tests/test_gateway_platform.py tests/test_cais.py -q --maxfail=5
```

Expected: PASS

- [ ] **Step 3: Commit release pins**

```bash
git add inventory/production/host_vars/ai-5820-01.yml inventory/production/host_vars/ai-ms-s1-max-01.yml
git commit -m "chore(gateway): bump release ids for quality_first auto routing"
```

---

### Task 8: Deploy and live probe

**Files:**
- Evidence under `evidence/ai-5820-01/<ts>/engineering-auto/` (create as part of probe)

- [ ] **Step 1: Deploy 5820 gateway + MS-S1 vllm-top**

Use the repo’s normal reconcile/ansible path for `ai-5820-01` (orchestrator_gateway) and `ai-ms-s1-max-01` (`vllm_top_console`). After deploy:

```bash
ssh ai-5820-01 'systemctl status aihost-orchestrator-gateway --no-pager | head -20'
ssh ai-5820-01 'journalctl -u aihost-orchestrator-gateway -n 30 --no-pager'
ssh ai-ms-s1-max-01 'systemctl status vllm-top-console --no-pager | head -20'
```

- [ ] **Step 2: Live probes through 5820 front door**

Using an existing workload client token and TLS CA as in commissioning:

1. `model=engineering/auto`, short prompt → expect route pool `lead` (or `rocm` if ranked so); header/evidence rule `engineering-auto`.
2. Code+tools prompt → may select `rocm`.
3. Complex reasoning prompt → prefer `deep`.
4. `model=engineering/interactive-rocm` → pool `rocm` only.
5. With remote worker stopped briefly → auto still succeeds on Intel; restore worker after.

Save curl/`X-AIHost-Route` / evidence snippets under `evidence/ai-5820-01/<ts>/engineering-auto/`.

- [ ] **Step 3: Commit evidence + open PR if working on a feature branch**

```bash
git add evidence/ai-5820-01/*/engineering-auto/
git commit -m "evidence: qualify engineering/auto quality_first on 5820 front door"
```

---

## Self-review vs spec

| Spec requirement | Task |
| --- | --- |
| Client contract / pins / single front door | 5, 6, 8 |
| `quality_first` ranking + failover | 1–3 |
| Do not widen catch-all default / unknown ≠ auto | 1, 3, 4, 5 |
| CAIS unchanged when header set | no code change (existing path) |
| MS-S1 vllm-top | 4, 5, 8 |
| Monitoring verify / dashboards | 6 |
| Release bump + deploy + probes | 7, 8 |
| Out of scope (CAIS grant, non-blocking start) | omitted intentionally |
