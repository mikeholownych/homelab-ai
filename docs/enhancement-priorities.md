# Intelligent Gateway — Enhancement Priorities

**Generated:** 2026-06-14  
**Repository:** `/home/mike/Projects/aihost`  
**Local HEAD:** `bf12c89` — *feat(inventory): declare hermes as authorized orchestrator gateway client*  
**Origin main:** `5b83ac6` — *docs(release): certify v1.0.0 readiness with all 17 gates passing*  
**Divergence:** Local is **73 commits ahead** of origin/main  

---

## 1. Current State Assessment

### What's Already Implemented (R1–R12)

All 12 smart-routing capabilities are marked complete in `tasks/todo.md`:

| Capability | Status | Key Files |
|---|---|---|
| **R1** Cancellation | ✅ Complete | `server.py:531-535` — `cancel.set()` signal propagation |
| **R2** Priority routing | ✅ Complete | `routing.py:33-56` — RouteRule with priority fields |
| **R3** Prompt complexity analysis | ✅ Complete | `smart_router.py:1-232` — `PromptComplexityAnalyzer`, `CODE_PATTERNS`, `REASONING_PATTERNS` |
| **R4** Canary & shadow routing | ✅ Complete | `routing.py:20-23` — `canary`, `shadow` in RULE_KEYS |
| **R5** Drain/swap | ✅ Complete | `server.py:433-439` — CAIS rebalance, suspend, revoke |
| **R6** Per-worker quotas | ✅ Complete | `server.py:391-393` — scope validation |
| **R7** Deadlines | ✅ Complete | `routing.py:20-23` — `max_queue_wait_ms` in RULE_KEYS |
| **R8** Reasoning control | ✅ Complete | `reasoning.py:1-126` — 4-layer bounded reasoning (worker cap → route policy → client profile → total bound) |
| **R9** Capability-checked routing | ✅ Complete | `routing.py:358-456` — `Router.decide()` with MATCH_KEYS |
| **R10** Feedback loop / outcomes | ✅ Complete | `server.py:344` — `/v1/outcomes` endpoint |
| **R11** Evidence integrity | ✅ Complete | Hash-chained evidence log, prompt hash-only policy |
| **R12** Graceful restart | ✅ Complete | Drain in-flight streams on restart |

### Supporting Infrastructure

| Component | Status | Key Files |
|---|---|---|
| Circuit breakers | ✅ Complete | `circuit_breaker.py:1-285` — sliding window error rate, consecutive failure thresholds, fast failover |
| Latency tracking | ✅ Complete | `smart_router.py` — `LatencyTracker` with EWMA duration/TTFT |
| Cost model | ✅ Complete | `smart_router.py` — `CostModel` for cost-optimized strategy |
| Reasoning policy | ✅ Complete | `reasoning.py` — 4-layer monotonic bounded reasoning |
| Routing strategies | ✅ Complete | `routing.py:26` — `first_match`, `least_latency`, `least_busy`, `cost_optimized` |

---

## 2. Enhancement Priorities (Ranked by ROI)

### P0 — Immediate (Pre-v1.0.0 Release Blockers)

These items block the v1.0.0 release and must be completed before tagging.

#### 2.1 Gateway Release Deployment (M2)
**Priority:** CRITICAL — blocks v1.0.0  
**Effort:** Medium (4-8 hours)  
**Impact:** High — production gateway is 73 commits behind HEAD

**What:** Deploy release candidate `t5820-gateway-b72a4f5` to production on `ai-5820-01`.

**Steps:**
1. Stage gateway on candidate port (:8002) via `playbooks/candidate.yml`
2. Execute candidate qualification: Q-TOOLS, Q-LONGCTX, Q-BUDGET, Q-CONTRACT
3. Promote to production via `playbooks/inference.yml`
4. Update controller reconciliation snapshot to git HEAD
5. Verify: systemd status, journal logs, `/health`, `/v1/models`, W3C trace to Tempo

**Evidence:** `docs/v1.0.0/V1.0.0-ROADMAP.md` lines 115-128

---

#### 2.2 Documentation Reconciliation (M3)
**Priority:** CRITICAL — blocks v1.0.0  
**Effort:** Medium (4-6 hours)  
**Impact:** High — documentation currently claims vLLM as primary serving engine; reality is dual-llama.cpp SYCL

**What:** Rewrite architecture docs to match the actual dual-llama.cpp SYCL deployment.

**Steps:**
1. Revise `README.md` sections 2-3: retire vLLM primary claim
2. Update `docs/architecture.md`: document dual-worker llama.cpp SYCL (GPU 0 lead, GPU 1 deep)
3. Update `docs/operations.md`, `docs/commissioning.md`, `docs/model-catalog.md`
4. Verify `pytest tests/test_documentation_contract.py` passes

**Evidence:** `docs/v1.0.0/V1.0.0-ROADMAP.md` lines 132-145

---

### P1 — High Value (Post-v1.0.0, Pre-v1.1.0)

These deliver significant user value and improve the gateway's intelligence.

#### 2.3 Queueing as a First-Class Gateway Function
**Priority:** HIGH — enables batch/async workloads  
**Effort:** High (2-3 days)  
**Impact:** High — currently clients hold HTTP connections for long tasks; no job API exists

**What:** Implement per-class queues (interactive / batch / background) with an async job API.

**Design points from `tasks/todo.md:380-383`:**
- Per-class queues with deadlines and fair share
- Async job API: `submit → id → poll/stream/callback`
- Queue state exposure (depth, wait estimates)
- Builds on: R1 cancel, R2 priority, R5 drain/swap, R7 deadlines, R10 outcomes

**Key design decisions needed:**
- Queue persistence: in-memory vs. on-disk (survive gateway restart)
- Backpressure: reject vs. queue when all classes saturated
- Callback mechanism: webhook, SSE, or polling

**Evidence:** `tasks/todo.md:377-399`

---

#### 2.4 Demand-Driven Model Loading/Unloading
**Priority:** HIGH — optimizes GPU utilization  
**Effort:** High (2-3 days)  
**Impact:** High — enables running more models than GPU memory allows

**What:** Hot/warm/cold model lifecycle management with hysteresis to prevent thrash.

**Design points from `tasks/todo.md:390-395`:**
- Warm set (resident) vs. cold set (on-disk GGUF)
- Swap cost ~30-90 seconds → add hysteresis/minimum residency
- Queue-aware: switch only when backlog justifies cold load
- Several small models per 32 GB card where they fit
- Route table resolves to "model capability"; scheduler decides placement

**Key design decisions needed:**
- Trigger: time-based idle eviction vs. demand-driven preload
- Preload strategy: predictive (based on route patterns) vs. reactive
- Swap coordination with circuit breakers (don't swap a worker that's tripping)

**Evidence:** `tasks/todo.md:390-395`, `docs/v1.0.0/V1.0.0-ROADMAP.md:191-193`

---

#### 2.5 Efficient Worker Use — Packing & Affinity
**Priority:** HIGH — improves throughput  
**Effort:** Medium-High (1-2 days)  
**Impact:** Medium-High — prefix-cache locality dominates cost on this stack

**What:** Smart packing of work to free slots, with prefix-cache affinity awareness.

**Design points from `tasks/todo.md:384-389`:**
- Pack work to free slots rather than spreading across workers
- Decide per-model: parallel slots (llama.cpp `-np` with kv-unified) vs. one large-context slot
- Keep prefix-cache affinity as a scheduling input
- Evidence: "fairer" scheduler that breaks cache locality can cost more than it saves

**Key design decisions needed:**
- How to measure prefix-cache hit rate per worker
- Whether to expose KV cache size as a routing signal
- Interaction with `least_busy` strategy

**Evidence:** `tasks/todo.md:384-389`

---

### P2 — Medium Value (v1.2.0+)

These are valuable but lower priority given the single-node homelab context.

#### 2.6 Batch Windows
**Priority:** MEDIUM — replaces ad-hoc evaluation runs  
**Effort:** Medium (1-2 days)  
**Impact:** Medium — eliminates manual "stop the workers" evaluation runs

**What:** Scheduled low-priority windows for benchmarking, qualification, and background jobs.

**Design points from `tasks/todo.md:396-397`:**
- Run benchmark/qualification during low interactive demand
- Replaces ad-hoc evaluation runs (e.g., 2026-10-06)
- Integrates with queue system (P2.3)

---

#### 2.7 Multi-Node Cluster Orchestration
**Priority:** MEDIUM — future-proofing  
**Effort:** High (1-2 weeks)  
**Impact:** Low currently (single-node meets all requirements)

**What:** Ray / Fleet API for multi-node cluster support.

**Evidence:** `docs/v1.0.0/V1.0.0-ROADMAP.md:191`

---

#### 2.8 In-Engine SYCL Kernel-Level Trace Propagation
**Priority:** LOW — blocked on upstream  
**Effort:** Unknown  
**Impact:** Medium — would enable deeper observability into GPU kernel execution

**What:** OpenTelemetry span injectors into llama.cpp SYCL engine.

**Evidence:** `docs/v1.0.0/V1.0.0-ROADMAP.md:193` — blocked on upstream llama.cpp

---

### P3 — Deferred / Out of Scope

| Feature | Target | Rationale |
|---|---|---|
| Physical commissioning of `ai-p620-01` | v1.1.0 | Dependent on physical workstation availability |
| Automated CMDB export & ITSM webhooks | v1.2.0 | Requires external service endpoints |
| Dual-GPU tensor-parallel split for 70B+ | v1.3.0 | Dual TP=1 independent workers provide superior concurrency for 30B-class |
| LLM-based prompt classifier | — | Breaks deterministic/auditable routing; R3 covers most value |
| On-demand model loading per request | — | 30-90s load time makes per-request impractical |
| Embeddings/rerank endpoints | — | No client demand yet |

---

## 3. Architecture Gaps & Technical Debt

### 3.1 Hardcoded Route Mapping in Gateway Server
**File:** `server.py:362-365`  
**Issue:** POST route mapping is hardcoded (`/v1/chat/completions`, `/v1/tokenize`, `/v1/outcomes`, `/admin/workers/*`, `/v1/admin/cais/*`), limiting extensibility.

**Recommendation:** Parameterize route registration to allow dynamic route discovery and plugin-based route handlers.

### 3.2 Global Worker Pin State
**File:** `server.py:448`, `asgi.py:311`  
**Issue:** Worker pinning is decided per-request from a module-level `allow_worker_pinning` value plus the
`ORCHESTRATOR_ALLOW_WORKER_PINNING` environment variable. The value is read-only after start-up, so there is no
data race today, but the parameter was typed `bool = False` while callers passed `None`, and `__main__.py` carried
dead `x if x is not None else True` expressions that could never take the `else` branch.

**Status:** Partially addressed — the parameter is now typed `bool | None = None` in `create_gateway` and
`create_asgi_gateway`, and the unreachable conditional expressions in `__main__.py` were removed. The remaining
work is to make the pinning decision a per-request, thread-safe value (e.g. `ContextVar`) if pinning ever becomes
mutable at runtime.

**Recommendation:** Move to a thread-safe `ContextVar` or `asyncio.Lock`-protected state machine when pinning
becomes dynamically configurable.

### 3.3 Circuit Breaker Evidence/Metrics Not Exposed
**File:** `circuit_breaker.py:194-195`  
**Issue:** `CircuitBreakerRegistry.__init__` accepts `evidence` and `metrics` arguments but only uses them internally in `_on_state_change` callback — not exposed for external inspection or configuration changes.

**Recommendation:** Expose breaker state for external monitoring and dynamic threshold adjustment.

### 3.4 No Prefix-Cache Metrics
**Issue:** The routing system has no visibility into prefix-cache hit rates, which evidence shows dominate cost on this stack.

**Recommendation:** Add prefix-cache hit/miss metrics from llama.cpp to the telemetry pipeline.

---

## 4. Recommended Execution Order

```
Phase 1 (Immediate, blocks v1.0.0):
  1.1  Gateway release deployment (M2) — 4-8 hours
  1.2  Documentation reconciliation (M3) — 4-6 hours

Phase 2 (Post-v1.0.0, high ROI):
  2.1  Queueing as first-class gateway function — 2-3 days
  2.2  Demand-driven model loading/unloading — 2-3 days
  2.3  Efficient worker packing & affinity — 1-2 days

Phase 3 (v1.2.0+, medium ROI):
  3.1  Batch windows — 1-2 days
  3.2  Multi-node cluster orchestration — 1-2 weeks

Technical Debt (parallel, low effort):
  D.1  Parameterize route registration — 2-4 hours
  D.2  Thread-safe worker pin state — 2-4 hours
  D.3  Expose circuit breaker state — 2-4 hours
  D.4  Add prefix-cache metrics — 4-8 hours
```

---

## 5. Key Design Principles (from `tasks/todo.md:136-137`)

> **Governing principle:** "Own what you control. Report what you observe."
>
> Gateway responsibility: "enforce limits and safety, route based on capability, report state."

All enhancements should respect these principles:
- The gateway/scheduler owns placement and admission
- It reports queue/placement state
- Clients own their intent (class, deadline)
- The scheduler never guesses intent it cannot know
