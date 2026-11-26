# Dual vs solo (engx-hard)

Evidence: `/home/mike/Projects/aihost/evaluations/nexus_e2e/evidence/20261124T191124Z`

## Solo baselines (Stage 1)

| Arm | Accepted % | Always fail | Flaky | Mean secs |
|-----|------------|-------------|-------|-----------|
| solo-deep | 86.7 | H07-sqlite-rebuild | H02-cron-next | 399.0 |
| solo-lead **best** | 96.7 | — | H03-json-patch | 429.4 |
| solo-rocm | 86.7 | H08-glob | H02-cron-next | 185.0 |

## Dual arms (Stage 2)

| Arm | Accepted % | Escape % | Regressions | Supported / refuted / dropped | Mean calls | Mean secs |
|-----|------------|----------|-------------|-------------------------------|------------|-----------|
| dual-deep-lead | 83.3 | 0.0 | 0 | 0/0/129 | 1.83 | 684.9 |
| dual-lead-deep | 100.0 | 0.0 | 0 | 0/0/156 | 2.0 | 750.9 |

## Decision vs Stage-2 criteria

- **dual-deep-lead**: Δ vs best solo (solo-lead 96.7%) = -13.4%; Δ vs same-implementer solo-deep (86.7%) = -3.4%; escape_rate=0.0%; regressions=0.
- **dual-lead-deep**: Δ vs best solo (solo-lead 96.7%) = +3.3%; Δ vs same-implementer solo-lead (96.7%) = +3.3%; escape_rate=0.0%; regressions=0.

Promote dual only if accepted rate improves vs best solo, or escapes drop with accepted rate ≥ best solo − ε (ε=0). Otherwise document as not worth it and do not build triple without a new decision.

**Verdict:** dual improves on best solo via dual-lead-deep.
