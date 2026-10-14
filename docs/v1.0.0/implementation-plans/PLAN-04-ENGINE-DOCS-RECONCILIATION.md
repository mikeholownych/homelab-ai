# Implementation Plan: PLAN-04 - Documentation & Serving Architecture Alignment

- **Plan ID**: `PLAN-04`
- **Specification Ref**: `SPEC-04`
- **Milestone**: `M3`
- **Target Components**: `README.md`, `docs/architecture.md`, `docs/commissioning.md`, `docs/operations.md`, `docs/model-catalog.md`
- **Estimated Effort**: 4-6 hours (Technical Writer & Systems Engineer)

---

## 1. Concrete Tasks & Execution Sequence

### Task 4.1: Revise `README.md`
- Update Section 2 ("Supported Host Profile"):
  - State clearly: "Serving Architecture: Two independent llama.cpp SYCL container instances (one per Arc Pro B65 GPU) coordinated by an intelligent reverse proxy (`orchestrator_gateway`)."
  - Document the lead pool (`Qwen3.6-35B-A3B`) on GPU 0 and deep pool (`Qwen3.8-Flash-Next`) on GPU 1.
  - Explain why vLLM was retired on this platform (measured 4x higher throughput and lower memory overhead under llama.cpp SYCL on Battlemage architecture).

### Task 4.2: Revise `docs/architecture.md`
- Update Section 3 ("Inference Software Stack"):
  - Primary Serving: "llama.cpp with SYCL acceleration (Level Zero backend), running containerized via rootless Podman, pinned to commit `b11347-5fc4f3c8c`."
  - Orchestration: "Authenticated `orchestrator_gateway` handling route matching, reasoning budget enforcement, dynamic queueing, and W3C distributed tracing."
  - Remove assertions that vLLM 0.7.3 TP=2 is the primary serving path.

### Task 4.3: Update Operations & Commissioning Runbooks
- In `docs/operations.md` and `docs/commissioning.md`:
  - Replace `systemctl status vllm` / `aihost-vllm-worker1` commands with `systemctl status aihost-llama-worker1.service aihost-llama-worker2.service`.
  - Update model inspection commands from Hugging Face hub paths to GGUF storage paths (`/var/lib/local-ai/models/gguf/`).

### Task 4.4: Reconcile `docs/model-catalog.md`
- Update table to emphasize evaluated GGUF models:
  - `Qwen3.6-35B-A3B-UD-Q4_K_M` (Lead Pool, GPU 0)
  - `Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M` (Deep Pool, GPU 1)
  - `Qwen3.5-27B-UD-Q4_K_M` (Rollback Target)

### Task 4.5: Validate Documentation Contract
- **Command**:
  ```bash
  .venv/bin/pytest tests/test_documentation_contract.py -v
  ```
- **Success Criteria**: All 4 tests pass.

---

## 2. Rollback & Precautionary Steps
- Changes are strictly documentation files. Revert via git if any contract assertion fails.
