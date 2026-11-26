# Three-Worker Local Inference for Nexus Engineering Task Accuracy

**Date:** 2026-11-24  
**Status:** Approved 2026-11-24 (design only — no runtime / inventory / routing changes until a stage is explicitly authorized)  
**Controller constraint:** mike-dev for repository work; Ansible for hosts  
**Depends on:**
- `docs/design/07-capability-aware-scheduling.md`
- `docs/superpowers/specs/2026-11-21-engineering-auto-quality-first-design.md`
- `docs/superpowers/specs/2026-11-22-fleet-auto-cais-routing-design.md`
- `docs/superpowers/specs/2026-11-22-lead-rocm-capability-mix-design.md`
- Inventory: `inventory/production/host_vars/ai-5820-01.yml`, `ai-ms-s1-max-01.yml`
- Eval substrate: `evaluations/engx/`, `evaluations/cais/`

---

## 1. Current-state facts (verified vs assumed)

### 1.1 Verified from repository configuration

| Fact | Evidence |
|------|----------|
| T5820 runs **two independent TP=1** llama.cpp SYCL workers, one GPU each — **not** pooled VRAM / not TP=2 for one larger model | `ai-5820-01.yml`: `dual_gpu_inference: "no tensor parallelism…"`, `worker1.gpu: 0`, `worker2.gpu: 1` |
| Lead worker: `b0-live-llama-worker1`, Qwen3.8-27B-UD-Q4_K_M, SYCL, `context: 65536`, `max_concurrency: 1`, port 8000 | `llama_cpp_container_workers.worker1`, `orchestrator_gateway_workers[0]` |
| Deep worker: `b0-live-llama-deep-worker2`, Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M, SYCL, `context: 65536`, `max_concurrency: 1`, port 8001 | `worker2` + gateway worker record; capabilities include `review` label |
| MS-S1 production worker: `ms-s1-hip-qwen38-27b` / `llama-hip-qwen3-8-27b`, **same GGUF digest as lead** (`sha256:322e194f…`), HIP/`gfx1151`, `context: 65536`, `-np 1`, port 8101 | `ai-ms-s1-max-01.yml` `llama_cpp_hip_workers`; 5820 gateway remote worker entry |
| Cluster front door for clients: `ai-5820-01` gateway (TLS `:8443`); MS-S1 gateway is host-local / pin parallel, **not** the auto front door | quality-first + fleet-auto specs; `orchestrator_gateway_remote_*` |
| Production worker count on 5820 gateway: **3** (lead, deep, remote rocm) | `orchestrator_gateway_production_worker_count: 3` |
| Routing today is **one request → one worker**; `quality_first` / CAIS choose among pools; pins bypass | Design 03/07; `orchestrator_gateway_routes` |
| **Workers only generate tokens**; Nexus owns task decomposition and final acceptance | Design 07 §2 / §15 |
| Gateway never routes outside the cluster; cloud escalation is a **Nexus** decision | Design 07 §15 |
| CAIS defines `coding.routine` / `coding.complex` with sandboxed hidden tests; **`review.*` classes deliberately undefined** (no oracle; second-model agreement is not one) | Design 07 §4 |
| engx `qualify.py` grades multi-turn tool loops by **hidden tests**, not by model self-judgment | `evaluations/engx/qualify.py`, `engx.py` |
| Deep historically strongest on eng-hard bounded reasoning (e.g. Flash-Next ~90% validated at budget 4096 in Q-BUDGET runs) | `evaluations/engx/results/qbudget-20261008/eng-hard-flashnext-deep-bounded-4096.json` |
| InferSSD on MS-S1 is **experimental**, not a production worker; stable filled integrity ~48k under its default `-b/-ub=n_ctx` | `reports/ms-s1-inferssd-qualification/20261123T170851Z/REPORT.md` |

### 1.2 Verified from host evidence (prior Ansible qualifications)

| Fact | Evidence |
|------|----------|
| MS-S1 has ~122–128 GiB **system** RAM and ~61 GiB **GTT/TTM** APU pool — **not** 128 GiB dedicated VRAM | Memory qualification report; `rocminfo` / drm GTT totals in that campaign |
| Production MS-S1 context **65536** is inventory/`-c` config, not a hard hardware ceiling for all models | Memory qual: Qwen3-4B filled through 262144 on isolated probe |
| Lead and rocm currently share artifact identity → **same model weights**, different `hardware_class` / `topology` / runtime image | Inventory digests + `profile_identity` definition in Design 07 |

### 1.3 Assumptions (not treated as facts)

| Assumption | Why unresolved |
|------------|----------------|
| Nexus Code’s in-product orchestration can host a multi-call collaboration loop without gateway changes | Nexus is an external client; no Nexus source tree in this repo |
| Three concurrent roles will improve **accepted** outcomes vs best single worker | Must be measured; Design 07 already warns shared failure modes |
| Deep’s inventory `review` label implies useful adversarial review | Label is asserted, not CAIS-evidenced; no `review.*` oracle |
| ROCm peer adds value beyond capacity/failover while serving the **same** GGUF as lead | May only diversify hardware/runtime bugs unless model mix changes |
| engx corpora are a sufficient proxy for “real Nexus engineering tasks” | Necessary Stage-0 substrate; full Nexus tasks need a separate sealed set |

---

## 2. Revised system objective and non-goals

### 2.1 Objective

**Build and operate a coordinated three-worker local inference system whose success is measured by end-to-end Nexus engineering task completion: correct repository outcomes, inspectable evidence, and regression control.**

Primary metrics (in order):

1. **Task acceptance rate** under fixed criteria (hidden/deterministic checks + human/operator gate where required).
2. **Correctness / defect escape** (failures that would have shipped).
3. **Regression rate** on previously passing tasks.
4. **Review defect detection** (true findings that change the repair path) and **false-finding rate**.
5. **Repair success** and **evidence completeness** (diff, commands, test logs, worker identities).
6. **Repeatability** across controlled re-runs.

Secondary (reported, not optimized as goals): wall time, tokens, GPU/memory pressure, queue wait.

### 2.2 Non-goals

- Optimizing individual model leaderboard scores, TTFT, or tok/s as the system objective.
- Treating majority agreement among models as acceptance.
- Claiming a larger model or three-model consensus guarantees higher quality.
- Pooling T5820 B65 memories or treating MS-S1 system RAM as dedicated VRAM.
- Promoting InferSSD or changing production model pins in this design pass.
- Moving auto front door off `ai-5820-01` or relaxing local-gateway-first (cloud remains a separately controlled Nexus exception).
- Implementing runtime/routing/host changes in this pass.

---

## 3. Control-plane vs execution-plane (who coordinates)

```
Nexus / evaluation harness (orchestration + acceptance)
        │  multiple OpenAI calls, artifacts, tools, tests
        ▼
 ai-5820-01 gateway (single front door; one call → one worker)
        │
   ┌────┼────┐
   ▼    ▼    ▼
 lead  deep  rocm   (token generation only)
```

**Decision (proposed):** Collaboration, handoff, repair loops, and termination live in the **orchestration plane** (Nexus product and/or a mike-dev evaluation harness that mirrors Nexus contracts). The gateway remains a **per-call router + CAIS gate + evidence logger**. That matches Design 07 and avoids inventing multi-agent semantics inside llama.cpp workers.

Gateway still contributes: pin/auto/CAIS selection per call, identity headers, outcomes ingestion, saturation failover. It does **not** vote, merge patches, or declare task success.

---

## 4. Proposed three-worker collaboration and handoff

### 4.1 Candidate roles (to validate, not freeze)

| Role | Intent | Prefer pool (candidate) | Why distinct? |
|------|--------|-------------------------|---------------|
| **Implementer** | Produce patches / tool actions against the task | `deep` for hard coding; `lead` for routine | Deep has strongest eng-hard evidence historically |
| **Adversarial reviewer** | Attack the change: missing tests, regressions, unsafe edits | Different **model** than implementer when possible | Findings only; never acceptance |
| **Disagreement / hard-reasoning analyst** | When implementer↔reviewer conflict or task is under-specified | Remaining peer or pinned reasoning alias | Separate prompt: adjudicate claims against repo evidence |

**Critical constraint:** Today **lead and rocm share the same GGUF**. A lead↔rocm “review” is **not** model-diverse. Until measured otherwise, treat that pairing as:

- useful for **capacity / hardware diversity / failover**, and
- **weak** for independent judgment diversity.

Prefer implementer/reviewer pairs that differ in **artifact_digest** (e.g. deep Flash-Next vs Qwen3.8-27B) before burning a third call.

### 4.2 Handoff artifacts (inspectable)

Each stage writes a structured artifact (paths under the task worktree or harness evidence dir):

1. **Task brief** — criteria, allowed files, stop conditions.
2. **Implementation attempt** — diff/patch, tool traces, worker `X-AIHost-*` identity, self-report.
3. **Deterministic check result** — lint/test/hidden suite stdout (oracle).
4. **Review findings** — list of claims with file:line anchors; each claim status: `unverified` → `supported` | `refuted` | `dropped`.
5. **Repair attempt(s)** — linked to specific supported findings.
6. **Acceptance packet** — pass/fail, criteria map, digests, attempt graph.

### 4.3 Acceptance rule (no majority vote)

A task is **accepted** only when:

1. Required deterministic checks pass (hidden tests / agreed suite / Nexus verifier).
2. Repository state matches task criteria (diff scope, no forbidden paths).
3. Evidence packet is complete and references real worker identities.
4. Any reviewer findings that remain `supported` are either fixed or explicitly waived by operator policy (not by another model saying “LGTM”).

A reviewer’s claim is a **finding to investigate**. Investigation uses tools, tests, and repo inspection — not peer models counting votes.

### 4.4 When to use one, two, or three workers

| Mode | Condition (proposed policy) | Calls |
|------|-----------------------------|-------|
| **Solo** | Routine task; clear tests; low blast radius; prior peer known-good on this class | 1 implementer |
| **Dual** | Complex coding, multi-file, security-sensitive, or first failure on solo | Implementer + reviewer (**different artifact** preferred) |
| **Triple** | Dual ends in unresolved disagreement, or task class marked `debug-hard` / architecture with conflicting criteria | Dual + analyst focused on contested claims only |

Do **not** call a third worker “for completeness” when dual already has passing checks and zero supported findings.

### 4.5 Failure / edge handling

| Situation | Handling |
|-----------|----------|
| Disagreement | Analyst or harness re-checks claims against repo/tests; no vote |
| Unsupported finding | Drop; do not repair |
| Reviewer miss (checks fail after “clean” review) | Count as review escape; escalate to dual/triple or operator |
| Repeated repair loops | Cap attempts (suggest 3); escalate or fail with evidence |
| Context limit | Shrink artifact handoff (diff hunks + failing tests only); pin higher-context peer only if measured envelope allows |
| Worker failure / saturation | Gateway failover within call; orchestration retries role on next eligible **different** worker when possible |
| Local-only constraint | All calls through 5820 gateway; cloud only via explicit Nexus exception path |

---

## 5. Design decisions that require measurement

1. Does dual (deep implement + 27B review, or reverse) beat best solo on **accepted** rate?
2. Does a third call ever improve acceptance enough to justify cost, once dual exists?
3. While lead≡rocm weights, does using rocm as reviewer add any non-zero true-finding rate vs calling lead twice?
4. Should ROCm primary remain same-as-lead (capacity) or regain a **distinct** artifact for collaboration diversity (capability-mix tension)?
5. What task set represents “real Nexus engineering” beyond engx hidden tests?
6. Where should the orchestrator live long-term: Nexus product vs harness-first prototype in homelab-ai?

---

## 6. Recommended repository changes (later authorized implementation only)

Identify only — **do not implement in this pass**:

| Area | Candidate change |
|------|------------------|
| `evaluations/` | New E2E collaboration harness (solo/dual/triple drivers, evidence schema, baselines) |
| `docs/operations/` | Operator runbook for collaboration modes and acceptance packets |
| Nexus client config (external) | Role prompts, attempt caps, gateway aliases / capability headers |
| Optional later | Distinct rocm artifact if measurement shows same-model review is worthless |
| Optional later | CAIS `review.*` only after an oracle exists (Design 07 already forbids premature class) |
| Gateway | Likely **no** multi-agent merge logic; maybe richer outcome fields for role tags |

---

## 7. Success definition for the overall program

The system is successful when a controlled evaluation shows the **collaboration policy** improves accepted task outcomes and/or reduces defect escape versus the best single-worker baseline on the same tasks, harness, and criteria — with evidence packets complete — without relying on majority vote or speed optimizations that reduce accuracy.
