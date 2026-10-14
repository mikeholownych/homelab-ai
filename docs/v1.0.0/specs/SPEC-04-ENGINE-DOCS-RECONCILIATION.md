# Technical Specification: SPEC-04 - Serving Engine Architecture & Documentation Alignment

- **Specification ID**: `SPEC-04`
- **Related Findings**: `F-03` (Serving engine documentation mismatch), `F-09` (Dead vLLM variables in host_vars)
- **Related Requirements**: `REQ-PROV-01` (Accurate Serving Stack Declaration)
- **Target Milestone**: `M3` (Architecture & Serving Engine Documentation Reconciliation)
- **Status**: Ready for Implementation

---

## 1. Problem Statement & Evidence
- **Documentation Inaccuracy**: Core platform documentation (`README.md`, `docs/architecture.md`, `docs/commissioning.md`, `docs/operations.md`) repeatedly asserts that vLLM 0.7.3 with Intel XPU backend is the primary inference runtime across both GPUs (TP=2), with llama.cpp SYCL as a fallback.
- **Operational Reality**: vLLM has been retired on `ai-5820-01` (`vllm_xpu_install_enabled: false`, `vllm_xpu_service_enabled: false`). Two independent llama.cpp SYCL container instances (TP=1 on GPU 0, TP=1 on GPU 1) are the authoritative production workers managed via `orchestrator_gateway`.
- **Impact**: New operators are given false information; troubleshooting steps cite obsolete vLLM logs and units (`aihost-vllm-worker1.service`), creating confusion and operational hazard.

---

## 2. Desired Behavior & Scope
- **Scope**:
  - Update `README.md` Section 2 ("Supported Host Profile") and Section 3 to document the dual-B65 dual-worker llama.cpp SYCL serving stack.
  - Update `docs/architecture.md` Section 3 ("Inference Software Stack") to declare dual-llama.cpp SYCL orchestrated via `orchestrator_gateway` as primary.
  - Update `docs/operations.md` and `docs/commissioning.md` to reference llama worker units (`aihost-llama-worker1.service`, `aihost-llama-worker2.service`) and GGUF model handling.
  - Reconcile `docs/model-catalog.md` to reflect promoted GGUF artifacts (`Qwen3.6-35B-A3B-UD-Q4_K_M` and `Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M`).
  - Clean up dead vLLM variable stubs in `inventory/production/host_vars/ai-5820-01.yml` where safe, retaining only documented retirement markers.
  - Verify `pytest tests/test_documentation_contract.py` passes.
- **Non-Goals**:
  - Deleting historical closeout reports or phase evidence manifests that reference vLLM.

---

## 3. Detailed Document Diffs & Changes
- **`README.md` Section 2 Update**:
  - Replace "Primary Serving: vLLM on dual B65" with "Serving Architecture: Two independent llama.cpp SYCL workers (one per Arc Pro B65 GPU) coordinated by an intelligent reverse proxy (`orchestrator_gateway`)."
  - Clarify VRAM allocation: Worker 1 (GPU 0) runs `Qwen3.6-35B-A3B` for rapid coding; Worker 2 (GPU 1) runs `Qwen3.8-Flash-Next` for deep reasoning.
- **`docs/architecture.md` Section 3 Update**:
  - Define the serving stack: Ubuntu 26.04 LTS, Linux 7.0+ HWE kernel, Intel OMIX 0.3.0 Level Zero compute stack, Podman rootless container runtime, llama.cpp SYCL engine b11347, orchestrator gateway with dynamic admission control.

---

## 4. Verification & Testing
- Run `pytest tests/test_documentation_contract.py` to ensure required topic coverage remains satisfied.
- Execute full text search to verify no active instructions direct operators to run retired vLLM units.

---

## 5. Acceptance Criteria
1. `README.md` and `docs/architecture.md` describe the dual-llama.cpp SYCL architecture as primary.
2. `pytest tests/test_documentation_contract.py` passes with zero failures.
3. No active operational playbook depends on `roles/vllm_xpu`.
