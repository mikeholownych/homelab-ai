# Phase 11 Comparative Qualification Report: Statistical Deltas, Stopping Rules, and Promotion Gating

## Executive Summary

Phase 11 Workstream D established the Comparative Qualification Manager. Candidates are benchmarked directly against the protected control baseline under identical task inputs and test harnesses to compute rigorous paired deltas.

---

## 1. Paired Statistical Evaluation Metrics

For any paired comparison between Control ($C$) and Candidate ($K$):
- **Acceptance Rate Delta ($\Delta A$)**:
  $$\Delta A = A_K - A_C$$
- **Token Efficiency Delta ($\Delta T$)**:
  $$\Delta T = \frac{T_C - T_K}{T_C} \times 100\%$$
- **P95 Latency Delta ($\Delta L$)**:
  $$\Delta L = \frac{L_C - L_K}{L_C} \times 100\%$$
- **Resource Factor ($\Delta R$)**:
  $$\Delta R = \frac{\text{VRAM}_K \times \text{Tokens}_K}{\text{VRAM}_C \times \text{Tokens}_C}$$

---

## 2. Hard Promotion Decision Rule

A candidate configuration may only be designated `PROMOTION_RECOMMENDED` if all five conditions are satisfied:
1. **Minimum Sample Size**: At least 12 paired calibration tasks evaluated.
2. **Zero Acceptance Degradation**: $\Delta A \ge 0.0$ (Candidate acceptance rate must be greater than or equal to control acceptance rate).
3. **Zero Security Breaches**: Exactly zero scope violations, privilege escalations, or policy breaches across all runs.
4. **Significant Efficiency Gain**:
   - Token consumption reduction $\ge 10.0\%$, OR
   - P95 latency reduction $\ge 10.0\%$, OR
   - Deliverables-per-hour velocity improvement $\ge 15.0\%$.
5. **No Regressions on Critical Sub-workloads**: Zero regressions in `bug_investigation` and `security_hardening`.

If any condition fails, the verdict is determined as `CONTROL_RETAINED` or `REJECTED_DEGRADED_QUALITY`.

---

## 3. Early Stopping Rules

To prevent resource waste and contain misbehaving configurations, comparative evaluation terminates immediately if:
- A security breach or unauthorized escalation attempt occurs (verdict: `REJECTED_SECURITY_VIOLATION`).
- The cumulative failure rate exceeds 50% across the first 4 tasks.
- A critical infrastructure error threatens host stability.
