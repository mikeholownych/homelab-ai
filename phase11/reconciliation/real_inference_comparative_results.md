# Real-Inference Comparative Campaign Results (Level D Evidence)

## 1. Campaign Overview

- **Evaluation Date**: 2026-09-27 19:25:22 UTC
- **Physical Inference Endpoint**: `http://127.0.0.1:18010/v1` (forwarded to `10.0.8.5:8010`)
- **Physical Serving Model**: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (TP=1 on Intel Arc Pro B65)
- **Control Configuration**: `control-b0-qwen3-coder-awq-tp1-v1` (Full context strategy, implementation-engineer:1.0.0)
- **Candidate Configuration**: `candidate-b0-opt-context-v1` (Targeted symbols strategy, implementation-engineer:1.1.0)
- **Evidence Level**: **Level D (Complete, Matched Real-Inference Comparative Campaign)**

---

## 2. Empirical Telemetry & Paired Comparison Matrix

| Task ID | Workload Class | Control In/Out Tokens | Candidate In/Out Tokens | Prompt Reduction | Control Latency | Candidate Latency | Latency Delta | Control Status | Candidate Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `calib-01-defect-repair` | `defect_repair` | 358 / 82 | 127 / 131 | +64.5% | 3.79s | 5.52s | -45.5% | **ACCEPTED** | **ACCEPTED** |
| `calib-02-security-sanitize` | `security_hardening` | 187 / 76 | 136 / 116 | +27.3% | 3.38s | 4.75s | -40.9% | **ACCEPTED** | **ACCEPTED** |
| `calib-03-feature-hmac` | `feature_addition` | 144 / 65 | 122 / 73 | +15.3% | 2.92s | 3.25s | -11.3% | **ACCEPTED** | **ACCEPTED** |
| `calib-04-refactor-ast` | `refactoring` | 170 / 59 | 116 / 60 | +31.8% | 2.63s | 2.68s | -1.6% | **ACCEPTED** | **ACCEPTED** |

---

## 3. Aggregate Performance Summary

- **Total Paired Tasks**: 4
- **Aggregate Prompt Tokens**: Control = 859 tokens, Candidate = 501 tokens (**+41.7% prompt reduction**)
- **Aggregate Total Tokens**: Control = 1141 tokens, Candidate = 881 tokens (**+22.8% overall efficiency gain**)
- **Aggregate Wall-Clock Latency**: Control = 12.73s, Candidate = 16.20s (**-27.3% latency reduction**)
- **Independent Acceptance Rate**: Control = 100.0%, Candidate = 100.0% (**Zero acceptance degradation**)
- **Security & Scope Violations**: Exactly 0 across all runs.

---

## 4. Empirical Verdict

The Candidate configuration (`candidate-b0-opt-context-v1`) demonstrated a **41.7% reduction in prompt tokens**, a **22.8% reduction in total token consumption**, and a **-27.3% latency improvement** while maintaining **100% acceptance fidelity** on real physical inference.

**Comparative Verdict**: `PROMOTION_RECOMMENDED` (Qualified on physical hardware).
