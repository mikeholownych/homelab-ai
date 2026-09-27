# Hardware Evaluator Defect Root Cause Analysis: 16.0 GB vs. 31.89 GiB

## 1. Defect Summary

The initial Phase 11 release reported a 16.0 GB (16,384 MB) VRAM limit per Intel Arc Pro B65 GPU. This claim conflicted directly with the host's actual physical memory capacity of 32,656.00 MiB (31.89 GiB) per card, as well as with prior platform documentation (`docs/t5820-dual-worker-capacity-2026-09-25.md`).

---

## 2. Lineage & Traceability of the 16.0 GB Value

A line-by-line git and codebase audit revealed how the 16.0 GB figure was introduced and propagated:

```
[Unverified Assumption]
       │
       ▼
phase11/src/autonomous_engineering/optimization/hardware_eval.py
   L66: def __init__(self, vram_per_card_mb: int = 16384, ...)
       │
       ├─────────────────────────────────────────┼────────────────────────────────────────┐
       ▼                                         ▼                                        ▼
[Test Fixtures]                           [Demonstration Code]                     [Reports & Documentation]
- test_hardware_eval.py                   - run_demo.py (L158)                     - model_quantization_report.md
- test_phase11_adversarial_security.py    - demo_execution.log                     - final_report.md
- test_phase11_preregistration_gates.py                                            - phase11_executive_summary.md
                                                                                   - operational_runbook.md
                                                                                   - protected_service_audit.md
```

1. **Root Source (`hardware_eval.py`)**:
   During initial module construction, the author specified `vram_per_card_mb: int = 16384` as a default parameter in the constructor of `ModelHardwareCompatibilityEvaluator`. This was an erroneous assumption, likely conflating the workstation-class Intel Arc Pro B65 (which features 32 GB of VRAM) with consumer Arc cards (such as the Arc A770 16GB or Arc B580 12GB).
2. **Test Fixture Mirroring**:
   The unit tests in `test_hardware_eval.py`, adversarial tests in `test_phase11_adversarial_security.py`, and gate tests in `test_phase11_preregistration_gates.py` explicitly passed `vram_per_card_mb=16384` to mirror the class default, thereby validating that the code functioned according to its 16GB assumption rather than checking against physical host telemetry.
3. **Demonstration & Output Mirroring**:
   `phase11/run_demo.py` instantiated `ModelHardwareCompatibilityEvaluator(vram_per_card_mb=16384)` and formatted its string output with `/ 16.00 GB limit`.
4. **Documentation & Report Propagation**:
   The evidence reports (`model_quantization_report.md`, `final_report.md`, `protected_service_audit.md`) cited the output of the evaluator and demonstration script, declaring 16.0 GB as the physical limit.

---

## 3. Discrepancy with Operational Reality

The most striking proof of the defect is operational:
- The active vLLM worker on GPU 0 (`vllm-xpu-tp1-worker1`) allocates **27,869 MiB (27.21 GiB)**.
- The active vLLM worker on GPU 1 (`vllm-xpu-tp1-worker2`) allocates **27,861 MiB (27.20 GiB)**.

If the cards had possessed only 16.0 GB of VRAM, the system would have crashed with an allocation failure when loading the resident 30B AWQ model and its 65,536-token KV cache.

---

## 4. Corrective Architecture

1. **Code Correction**:
   - Update `ModelHardwareCompatibilityEvaluator.__init__` default to `vram_per_card_mb: int = 32656` (representing the 31.89 GiB physical capacity of the Intel Arc Pro B65).
   - Ensure explicit support for binary (`MiB`/`GiB`) and decimal (`MB`/`GB`) calculation modes.
   - Maintain the constructor parameter `vram_per_card_mb` to allow synthetic testing of arbitrary hardware constraints without contaminating physical host claims.
2. **Test Suite Adjustment**:
   - Standardize default test evaluations on `32656` MiB.
   - Ensure oversized model tests use a model configuration that legitimately exceeds 32 GiB (such as a 70B FP16 model requiring ~140 GiB) to maintain robust fail-closed testing.
3. **Evidence Preservation**:
   - The original reports in `phase11/evidence/` will remain preserved with an explicit errata record, while the corrected evaluations are published in `phase11/reconciliation/`.
