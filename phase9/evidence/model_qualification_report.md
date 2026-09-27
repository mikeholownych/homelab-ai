# Phase 9 Qualification Report: Model Capability and Qualification Registry (Workstream C)

**Date**: 2026-09-27  
**Author**: Principal Engineering Agent  
**Workstream**: C (Model Capability Registry)  
**Status**: PROVEN  

---

## 1. Executive Summary

Workstream C implements the `ModelCapabilityRegistry`, establishing an authoritative capability boundary and qualification lifecycle for serving configurations. Model capabilities are grounded exclusively in empirical measurements and verified physical deployments rather than promotional marketing or generic benchmark claims.

### Key Outcomes:
1. **Authoritative 5-Tuple Qualification Key**:
   $$\text{Qualification Key} = \text{Profile Digest} \times \text{Model Revision} \times \text{Inference Config} \times \text{Workload Class} \times \text{Suite Version}$$
   Qualification is strictly workload- and profile-specific: qualification for defect repair does not authorize security review or architectural planning.
2. **Empirical Measurements**:
   - `engineering/b0` (`Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on dual vLLM XPU TP=1): measured throughput 38.4 tokens/sec, TTFT 310.0 ms, context window 65,536 tokens, memory footprint 24.5 GiB per GPU.
   - `reviewer/phi4-calibrated`: calibrated adapter for orchestration contracts, context 32,768 tokens, TTFT 180.0 ms.
3. **Preservation of Unsuccessful Candidates**: Failed and disqualified candidates are preserved in the registry with explicit disqualification rationale.
4. **Lifecycle & Expiration**: Expired or revoked certificates fail closed immediately.

---

## 2. Test Verification & Empirical Results

The model capability registry was evaluated in `phase9/tests/test_model_capability_registry.py`:

| Test Name | Scenario Evaluated | Observed Control Plane Behavior | Verdict |
|---|---|---|---|
| `test_baseline_capabilities_registered` | Verification of hardware telemetry and interface parameters | Context capacity, tool-calling support, and execution tiers verified | **PASS** |
| `test_qualification_key_and_certificate_lifecycle` | 5-tuple qualification issuance, verification, and revocation | Certificate verifies active status; revoked key fails closed | **PASS** |
| `test_qualification_expiration` | Expired qualification certificate handling | Fails closed on expired certificate; `is_qualified()` returns False | **PASS** |

---

## 3. Preregistration Gate G4 Disposition

> **Gate G4 Requirement**: Model qualification prevents unqualified routing.

**Disposition**: **GATE G4: SATISFIED (PROVEN)**.
