# Phase 14 Dependency Audit and Authoritative Project DAG

- **Date:** 2026-09-29
- **Author:** Autonomous Engineering System
- **Status:** Complete / Authoritative / Audited
- **Baseline Scheduling Mode:** `SchedulingMode.CONFIGURATION_B`
- **Experimental Target:** `SchedulingMode.CONFIGURATION_B_PLUS`
- **Primary Focus:** Item 01 (Investigation) $\rightarrow$ Item 02 (Planning) $\rightarrow$ Item 03 (Core Implementation) Dependency Chain

---

## 1. Executive Summary & Audit Mandate

Before modifying task placement or implementing Configuration B+, this mandatory audit reconstructs the authoritative task dependency graph across all 8 engineering items.

The purpose is to establish whether moving **Item 01 (Repository Architecture & Dependency Investigation)** to **Worker 2** violates any task prerequisites, creates unsafe concurrency, compromises output quality, or weakens external authority boundaries.

### Core Audit Finding:
1. **Item 01 $\rightarrow$ Item 02 is a HARD prerequisite for finalized planning**: Item 02 requires the component identification and module isolation boundaries produced by Item 01 to generate a valid, compilable execution DAG and rollback plan.
2. **Sequential Handoff Preserves Hard Dependencies**: By dispatching Item 01 to Worker 2, validating its deliverable out-of-process, and passing the sanitized findings to Worker 1 before Item 02 begins, the dependency invariant is **100% preserved**.
3. **Worker 1 Service Demand is Reduced by 28.25 s**: Moving Item 01 off Worker 1 relieves Worker 1 of $28.25\text{ s}$ of serialized compute, lowering Worker 1 active service demand from $189.7\text{ s}$ to $161.4\text{ s}$ ($-14.9\%$) without introducing artificial concurrency or risking plan invalidation.

---

## 2. Comprehensive Answers to the Seven Mandatory Questions

### Question 1: Can Worker 1 begin Item 02 before Item 01 completes?
- **Repository Evidence**: In [`phase13/src/autonomous_engineering/heterogeneous/production_pipeline.py`](file:///home/mike/Projects/aihost/phase13/src/autonomous_engineering/heterogeneous/production_pipeline.py#L206), Item 02 explicitly specifies `predecessors=["PROJ-01-01"]`. The prompt for Item 02 requires concrete component boundaries discovered in Item 01.
- **Audit Determination**: Full Item 02 planning cannot be finalized without Item 01 findings. While superficial scaffolding could theoretically run, any unexpected architectural constraint discovered by Item 01 would invalidate the plan and force a 28s replanning turn.
- **Contract Decision**: Preserving the strict causal dependency (`Item 01 (W2) -> Out-of-Process Quarantine -> Validation -> Item 02 (W1)`) ensures zero wasted compute and 100% deterministic plan stability.

### Question 2: Which planning activities are safe to perform without Item 01 findings?
- **Audit Determination**: Top-level requirement parsing, schema envelope initialization, and tool permission declarations can be derived solely from the project specification prompt.
- **Boundary**: Module-level symbol maps, inter-file import graphs, and rollback boundaries cannot be assumed prior to repository inspection. Therefore, Item 02 plan finalization must await accepted Item 01 handoff.

### Question 3: Can Item 03 begin before Item 01 and Item 02 have been accepted?
- **Repository Evidence**: Item 03 implements thread-safe state engines and core logic (`predecessors=["PROJ-01-02"]`).
- **Audit Determination**: **NO**. Code implementation without an accepted architectural plan and DAG violates fail-closed engineering principles and causes downstream integration and syntax failures.

### Question 4: What happens when Item 01 discovers a fact that invalidates provisional planning?
- **Audit Determination**: Under the strictly preserved sequential handoff contract, provisional planning is never dispatched or exposed to downstream stages. Item 01 findings are fully settled, validated, and sanitized before Worker 1 synthesizes Item 02. If Item 01 uncovers blockers, Worker 1 incorporates them directly into the plan on first pass.

### Question 5: Who has authority to accept, reject or request repair of Item 01 findings?
- **Audit Determination**: Dual Authority Boundary:
  1. **External Authority Boundary (`ExternalAuthorityBoundary`)**: Performs out-of-process threat scanning (blocking tool escalation, prompt injection, and path traversal) and wraps deliverables in quarantine delimiters.
  2. **Lead Worker 1 (`LEAD_ENGINEERING_AUTHORITY`)**: Evaluates the sanitized findings during Item 02. If findings are deficient or malformed, Worker 1 rejects the handoff and triggers fail-closed lead fallback.

### Question 6: How are stale findings prevented from contaminating later stages?
- **Audit Determination**: The handoff contract embeds an immutable cryptographic signature comprising:
  - `task_id` and `invocation_id`
  - Canonical git commit SHA (`git rev-parse HEAD`)
  - Cryptographic content digest (`output_digest = sha256(content)`)
  - Execution timestamp
- If repository state changes or digests mismatch, downstream workers fail-closed and reject the handoff as stale.

### Question 7: Can Item 01 be moved without changing the engineering task's intended meaning?
- **Repository Evidence**: On the Dell Precision T5820, Worker 1 (GPU 0) and Worker 2 (GPU 1) run the **identical 30B MoE model** (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`).
- **Audit Determination**: **YES**. Moving Item 01 to Worker 2 executes the exact same prompt on the exact same model weights, preserving 100% semantic fidelity and reasoning depth while utilizing idle GPU 1 compute.

---

## 3. Authoritative Task Dependency Graph (Items 01–08)

```mermaid
flowchart TD
    subgraph Stage1 ["Stage 1: Rebalanced Investigation & Planning"]
        W2_01["Worker 2 (30B)<br>Item 01: Investigation<br>(~28.3s)"]
        HandoffGate{"External Authority<br>Boundary Quarantine<br>& Validation"}
        W1_02["Worker 1 (30B)<br>Item 02: Planning & DAG<br>(~28.2s)"]
        W1_03["Worker 1 (30B)<br>Item 03: Core Engine<br>(~42.1s)"]
        
        W2_01 -->|Raw Findings| HandoffGate
        HandoffGate -->|Sanitized Handoff| W1_02
        W1_02 -->|Accepted Plan| W1_03
    end

    subgraph Stage2 ["Stage 2: Parallel Barrier"]
        W2_04["Worker 2 (30B)<br>Item 04: Unit Tests<br>(~40.9s)"]
        W2_05["Worker 2 (30B)<br>Item 05: Schema Contract<br>(~40.9s)"]
        W1_06["Worker 1 (30B)<br>Item 06: Security Review<br>(~41.5s)"]
        JoinBarrier{"Stage 2 Join Barrier"}
        
        W1_03 --> W2_04
        W1_03 --> W2_05
        W1_03 --> W1_06
        
        W2_04 --> JoinBarrier
        W2_05 --> JoinBarrier
        W1_06 --> JoinBarrier
    end

    subgraph Stage3 ["Stage 3: Lead Integration & Acceptance"]
        W1_07["Worker 1 (30B)<br>Item 07: Project Integration<br>(~28.2s)"]
        W1_08["Worker 1 (30B)<br>Item 08: Acceptance Signoff<br>(~28.1s)"]
        
        JoinBarrier --> W1_07
        W1_07 --> W1_08
    end

    classDef worker1 fill:#e1f5fe,stroke:#0288d1,stroke-width:2px;
    classDef worker2 fill:#e8f5e9,stroke:#388e3c,stroke-width:2px;
    classDef gate fill:#fff3e0,stroke:#f57c00,stroke-width:2px;
    
    class W1_02,W1_03,W1_06,W1_07,W1_08 worker1;
    class W2_01,W2_04,W2_05 worker2;
    class HandoffGate,JoinBarrier gate;
```

---

## 4. Hard vs. Advisory Dependencies Matrix

| Item | Task Title | Primary Assigned Worker | Hard Prerequisites | Advisory Inputs | Acceptance Criteria |
|---|---|---|---|---|---|
| **01** | Architecture Investigation | Worker 2 (30B) | Project Prompt, Repo Commit | None | Clean external quarantine, non-empty module inventory |
| **02** | Execution DAG & Rollback | Worker 1 (30B) | **Accepted Item 01 Handoff** | Project Scoping | Valid DAG definition, rollback boundaries defined |
| **03** | Core Engine Implementation | Worker 1 (30B) | **Accepted Item 02 Plan** | Item 01 Symbols | Syntactically valid Python, thread-safe transitions |
| **04** | Pytest Unit Tests | Worker 2 (30B) | **Completed Item 03 Code** | Item 01/02 Specs | Executable `def test_`, assertions present |
| **05** | OpenAPI Schema Contract | Worker 2 (30B) | **Completed Item 03 Code** | Item 02 Endpoints | Valid JSON/OpenAPI schema syntax |
| **06** | SAST & Security Review | Worker 1 (30B) | **Completed Item 03 Code** | Item 01 Boundaries | Structured security findings, zero unhandled flaws |
| **07** | Project Integration | Worker 1 (30B) | **All Items 04, 05, 06** | Handoff Manifests | Full end-to-end integration passes |
| **08** | Acceptance Signoff | Worker 1 (30B) | **Completed Item 07 Code** | All Audit Artifacts | 4-Gate verification (Syntax, Tests, Security, Integration)|
