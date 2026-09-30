# Phase 14 Experiment 02: Queue Stability Reassessment

- **Date:** 2026-09-29
- **Scope:** Mathematical queue stability analysis, finite-window vs. steady-state behavior, and queue wait growth reconciliation.

---

## 1. Mathematical Queue Stability Foundations

In queuing theory ($G/G/1$ or pipeline queue models), an engineering pipeline with arrival rate $\lambda$ and stage service demands $D_1$ (Worker 1) and $D_2$ (Worker 2) is stable in the steady state if and only if:
$$\rho_1 = \lambda \cdot D_1 < 1.0 \quad \text{and} \quad \rho_2 = \lambda \cdot D_2 < 1.0$$

At the capacity-stress offered rate $\lambda = 19.5\text{ projects/hour}$ ($1 \text{ project per } 184.62\text{ seconds}$):

### Control Arm (Configuration B):
- Measured $D_1 = 194.86\text{ seconds}$.
- $\rho_1 = \frac{194.86}{184.62} = \mathbf{1.055} > 1.0$.
- **Mathematical Verdict:** Strictly **UNSTABLE**.
- **Empirical Confirmation:** The queue wait for Configuration B grew continuously across all six projects:
  $$W_q = [0.0\text{s}, 39.2\text{s}, 71.7\text{s}, 111.2\text{s}, 150.4\text{s}, 189.7\text{s}]$$
  The wait growth rate was $+39.3\text{ seconds per project}$. Configuration B queue backlog diverges towards infinity.

### Candidate Arm (Configuration B+):
- Measured uncontended $D_1 = 164.80\text{ seconds}$ (Projects 1-4).
- $\rho_1 = \frac{164.80}{184.62} = \mathbf{0.893} < 1.0$.
- In the absence of external interference, Configuration B+ operates at $\rho_1 \approx 89\%$, which is mathematically sub-saturated.
- **Empirical Confirmation:** For Projects 1 through 4, queue wait was strictly $0.00\text{ seconds}$.

---

## 2. Resolving the Apparent Discrepancy

The original Phase 14 Experiment 02 report labeled Configuration B+ "stable" at 19.5 proj/hr while simultaneously recording a throughput of 17.79 proj/hr and positive queue wait growth on Projects 5 and 6 ($12.2\text{s} \rightarrow 25.5\text{s}$).

Forensic analysis resolves this discrepancy completely:

1. **Root Cause of Wait Growth:**
   - The queue wait on Projects 5 and 6 was **not** caused by internal pipeline saturation ($\rho_1 < 1.0$).
   - It was directly triggered by the **41,853 tokens of concurrent OpenCode traffic** that hit Worker 1 at $06:19 - 06:26$.
   - This external load temporarily pushed Worker 1 instantaneous utilization above 100%, causing a transient accumulation of queue delay.
2. **Finite-Cohort Limitation:**
   - A finite 6-project cohort over 20 minutes is insufficient to mathematically assert long-run steady-state stability under open-world conditions.
   - When an unmanaged external agent can asynchronously inject 14 requests into the vLLM engine, steady-state queue bounds cannot be guaranteed without an explicit admission control mechanism.
3. **True Long-Run Sustainable Capacity:**
   - Under uncontended single-tenant conditions, Configuration B+'s maximum theoretical throughput is:
     $$\lambda_{\max} = \frac{3600}{164.80} \approx \mathbf{21.84\text{ proj/hr}}$$
   - To maintain a safe queuing margin ($\rho_1 \le 0.82$) and absorb transient fluctuations, the **sustainable long-run operating point** for Configuration B+ is:
     $$\lambda_{\text{sustainable}} \le \mathbf{18.0\text{ projects/hour}}$$

---

## 3. Revised Queue Stability Classifications

| Regime | Configuration B | Configuration B+ (Reconciled) |
|---|---|---|
| **Regime 1 ($\lambda = 12.0$ proj/hr)** | **STABLE** ($\rho_1 = 0.65$) | **STABLE** ($\rho_1 = 0.55$) |
| **Regime 2 ($\lambda = 19.5$ proj/hr)** | **UNSTABLE** ($\rho_1 = 1.06$, linear growth) | **PROVEN WITH LIMITATIONS** (Demonstrated finite-cohort gain to 17.79 proj/hr; transient queue accumulation under concurrent load) |
| **Long-Run Capacity Cap** | $16.0 - 16.5\text{ proj/hr}$ | $18.0 - 18.5\text{ proj/hr}$ |
