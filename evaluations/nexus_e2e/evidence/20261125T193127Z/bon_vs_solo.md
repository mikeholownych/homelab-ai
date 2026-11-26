# Best-of-n vs solo (execution-gated)

Evidence: `evaluations/nexus_e2e/evidence/20261125T193127Z`

| Arm | Accepted % | Oracle coverage % | Mean tokens | Mean secs | Mean samples / attempts |
|-----|------------|-------------------|-------------|-----------|-------------------------|
| solo-lead (max_attempts=1) | 80.0 | n/a | 6051 | 335.1 | 1 |
| bon3-lead (n=3, max_attempts=1) | 90.0 | 90.0 | 8362 | 470.6 | 1.3 samples |
| solo-lead (max_attempts=3, 30 trials) | 96.7 | n/a | 8289 | 429.4 | up to 3 attempts |

Δ accepted (BoN − solo-1) = 10.0%

Selection rule: first sample that passes hidden oracle; no LLM judge.

**Verdict vs single-sample solo:** BoN improves accepted rate vs `max_attempts=1` (+10.0 pts; fixed `H03-json-patch`).

**Verdict vs matched-token sequential repair (`solo-lead`, `max_attempts=3`):** Δ accepted (BoN − repair) = -6.7% at nearly identical mean tokens (8362 vs 8289). Execution-feedback repair outperforms blind BoN sampling and should remain the primary loop; BoN is a secondary fallback for single-shot non-repair tasks.
