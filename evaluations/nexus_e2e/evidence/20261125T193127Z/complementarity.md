# Pairwise complementarity (β) and solved-set overlap

Definition: `β = both_fail / n_shared` on paired `(task_id, rep)` trials; `union % = 100 * (1 - β)`.

## Evaluated arms

| Arm | Tasks | Trials | Accepted | Accepted % |
|-----|-------|--------|----------|------------|
| solo-lead | 10 | 30 | 29 | 96.7 |
| solo-deep | 10 | 30 | 26 | 86.7 |
| solo-rocm | 10 | 30 | 26 | 86.7 |
| solo-lead-1 | 10 | 10 | 8 | 80.0 |
| bon3-lead | 10 | 10 | 9 | 90.0 |
| cand-devstral-small2 | 4 | 4 | 0 | 0.0 |
| cand-glm47-flash | 4 | 4 | 0 | 0.0 |

## Pairwise trial overlap (paired `(task_id, rep)`)

| Pair (A vs B) | Shared | A % | B % | Both pass | Only A | Only B | Both fail | β (all-fail) | Union % |
|---------------|--------|-----|-----|-----------|--------|--------|-----------|--------------|---------|
| solo-lead vs solo-deep | 30 | 96.7 | 86.7 | 25 | 4 | 1 | 0 | 0.0000 | 100.0 |
| solo-lead vs solo-rocm | 30 | 96.7 | 86.7 | 25 | 4 | 1 | 0 | 0.0000 | 100.0 |
| solo-lead vs solo-lead-1 | 10 | 100.0 | 80.0 | 8 | 2 | 0 | 0 | 0.0000 | 100.0 |
| solo-lead vs bon3-lead | 10 | 100.0 | 90.0 | 9 | 1 | 0 | 0 | 0.0000 | 100.0 |
| solo-lead vs cand-devstral-small2 | 4 | 100.0 | 0.0 | 0 | 4 | 0 | 0 | 0.0000 | 100.0 |
| solo-lead vs cand-glm47-flash | 4 | 100.0 | 0.0 | 0 | 4 | 0 | 0 | 0.0000 | 100.0 |
| solo-deep vs solo-rocm | 30 | 86.7 | 86.7 | 22 | 4 | 4 | 0 | 0.0000 | 100.0 |
| solo-deep vs solo-lead-1 | 10 | 90.0 | 80.0 | 7 | 2 | 1 | 0 | 0.0000 | 100.0 |
| solo-deep vs bon3-lead | 10 | 90.0 | 90.0 | 8 | 1 | 1 | 0 | 0.0000 | 100.0 |
| solo-deep vs cand-devstral-small2 | 4 | 75.0 | 0.0 | 0 | 3 | 0 | 1 | 0.2500 | 75.0 |
| solo-deep vs cand-glm47-flash | 4 | 75.0 | 0.0 | 0 | 3 | 0 | 1 | 0.2500 | 75.0 |
| solo-rocm vs solo-lead-1 | 10 | 90.0 | 80.0 | 8 | 1 | 0 | 1 | 0.1000 | 90.0 |
| solo-rocm vs bon3-lead | 10 | 90.0 | 90.0 | 9 | 0 | 0 | 1 | 0.1000 | 90.0 |
| solo-rocm vs cand-devstral-small2 | 4 | 75.0 | 0.0 | 0 | 3 | 0 | 1 | 0.2500 | 75.0 |
| solo-rocm vs cand-glm47-flash | 4 | 75.0 | 0.0 | 0 | 3 | 0 | 1 | 0.2500 | 75.0 |
| solo-lead-1 vs bon3-lead | 10 | 80.0 | 90.0 | 8 | 0 | 1 | 1 | 0.1000 | 90.0 |
| solo-lead-1 vs cand-devstral-small2 | 4 | 50.0 | 0.0 | 0 | 2 | 0 | 2 | 0.5000 | 50.0 |
| solo-lead-1 vs cand-glm47-flash | 4 | 50.0 | 0.0 | 0 | 2 | 0 | 2 | 0.5000 | 50.0 |
| bon3-lead vs cand-devstral-small2 | 4 | 75.0 | 0.0 | 0 | 3 | 0 | 1 | 0.2500 | 75.0 |
| bon3-lead vs cand-glm47-flash | 4 | 75.0 | 0.0 | 0 | 3 | 0 | 1 | 0.2500 | 75.0 |
| cand-devstral-small2 vs cand-glm47-flash | 4 | 0.0 | 0.0 | 0 | 0 | 0 | 4 | 1.0000 | 0.0 |

### Unique solves by trial

- **solo-lead vs solo-deep** (n=30): only `solo-lead`=[H02-cron-next#rep3, H07-sqlite-rebuild#rep1, H07-sqlite-rebuild#rep2, H07-sqlite-rebuild#rep3]; only `solo-deep`=[H03-json-patch#rep3]; both fail=[—]
- **solo-lead vs solo-rocm** (n=30): only `solo-lead`=[H02-cron-next#rep2, H08-glob#rep1, H08-glob#rep2, H08-glob#rep3]; only `solo-rocm`=[H03-json-patch#rep3]; both fail=[—]
- **solo-lead vs solo-lead-1** (n=10): only `solo-lead`=[H03-json-patch#rep1, H08-glob#rep1]; only `solo-lead-1`=[—]; both fail=[—]
- **solo-lead vs bon3-lead** (n=10): only `solo-lead`=[H08-glob#rep1]; only `bon3-lead`=[—]; both fail=[—]
- **solo-lead vs cand-devstral-small2** (n=4): only `solo-lead`=[H02-cron-next#rep1, H03-json-patch#rep1, H07-sqlite-rebuild#rep1, H08-glob#rep1]; only `cand-devstral-small2`=[—]; both fail=[—]
- **solo-lead vs cand-glm47-flash** (n=4): only `solo-lead`=[H02-cron-next#rep1, H03-json-patch#rep1, H07-sqlite-rebuild#rep1, H08-glob#rep1]; only `cand-glm47-flash`=[—]; both fail=[—]
- **solo-deep vs solo-rocm** (n=30): only `solo-deep`=[H02-cron-next#rep2, H08-glob#rep1, H08-glob#rep2, H08-glob#rep3]; only `solo-rocm`=[H02-cron-next#rep3, H07-sqlite-rebuild#rep1, H07-sqlite-rebuild#rep2, H07-sqlite-rebuild#rep3]; both fail=[—]
- **solo-deep vs solo-lead-1** (n=10): only `solo-deep`=[H03-json-patch#rep1, H08-glob#rep1]; only `solo-lead-1`=[H07-sqlite-rebuild#rep1]; both fail=[—]
- **solo-deep vs bon3-lead** (n=10): only `solo-deep`=[H08-glob#rep1]; only `bon3-lead`=[H07-sqlite-rebuild#rep1]; both fail=[—]
- **solo-deep vs cand-devstral-small2** (n=4): only `solo-deep`=[H02-cron-next#rep1, H03-json-patch#rep1, H08-glob#rep1]; only `cand-devstral-small2`=[—]; both fail=[H07-sqlite-rebuild#rep1]
- **solo-deep vs cand-glm47-flash** (n=4): only `solo-deep`=[H02-cron-next#rep1, H03-json-patch#rep1, H08-glob#rep1]; only `cand-glm47-flash`=[—]; both fail=[H07-sqlite-rebuild#rep1]
- **solo-rocm vs solo-lead-1** (n=10): only `solo-rocm`=[H03-json-patch#rep1]; only `solo-lead-1`=[—]; both fail=[H08-glob#rep1]
- **solo-rocm vs bon3-lead** (n=10): only `solo-rocm`=[—]; only `bon3-lead`=[—]; both fail=[H08-glob#rep1]
- **solo-rocm vs cand-devstral-small2** (n=4): only `solo-rocm`=[H02-cron-next#rep1, H03-json-patch#rep1, H07-sqlite-rebuild#rep1]; only `cand-devstral-small2`=[—]; both fail=[H08-glob#rep1]
- **solo-rocm vs cand-glm47-flash** (n=4): only `solo-rocm`=[H02-cron-next#rep1, H03-json-patch#rep1, H07-sqlite-rebuild#rep1]; only `cand-glm47-flash`=[—]; both fail=[H08-glob#rep1]
- **solo-lead-1 vs bon3-lead** (n=10): only `solo-lead-1`=[—]; only `bon3-lead`=[H03-json-patch#rep1]; both fail=[H08-glob#rep1]
- **solo-lead-1 vs cand-devstral-small2** (n=4): only `solo-lead-1`=[H02-cron-next#rep1, H07-sqlite-rebuild#rep1]; only `cand-devstral-small2`=[—]; both fail=[H03-json-patch#rep1, H08-glob#rep1]
- **solo-lead-1 vs cand-glm47-flash** (n=4): only `solo-lead-1`=[H02-cron-next#rep1, H07-sqlite-rebuild#rep1]; only `cand-glm47-flash`=[—]; both fail=[H03-json-patch#rep1, H08-glob#rep1]
- **bon3-lead vs cand-devstral-small2** (n=4): only `bon3-lead`=[H02-cron-next#rep1, H03-json-patch#rep1, H07-sqlite-rebuild#rep1]; only `cand-devstral-small2`=[—]; both fail=[H08-glob#rep1]
- **bon3-lead vs cand-glm47-flash** (n=4): only `bon3-lead`=[H02-cron-next#rep1, H03-json-patch#rep1, H07-sqlite-rebuild#rep1]; only `cand-glm47-flash`=[—]; both fail=[H08-glob#rep1]
- **cand-devstral-small2 vs cand-glm47-flash** (n=4): only `cand-devstral-small2`=[—]; only `cand-glm47-flash`=[—]; both fail=[H02-cron-next#rep1, H03-json-patch#rep1, H07-sqlite-rebuild#rep1, H08-glob#rep1]

## Task-level ever-solved overlap (across all reps per arm)

| Pair (A vs B) | Shared tasks | Both ever | Only A ever | Only B ever | Neither ever | Task β | Task union % |
|---------------|--------------|-----------|-------------|-------------|--------------|--------|--------------|
| solo-lead vs solo-deep | 10 | 9 | H07-sqlite-rebuild | — | — | 0.0000 | 100.0 |
| solo-lead vs solo-rocm | 10 | 9 | H08-glob | — | — | 0.0000 | 100.0 |
| solo-lead vs solo-lead-1 | 10 | 8 | H03-json-patch, H08-glob | — | — | 0.0000 | 100.0 |
| solo-lead vs bon3-lead | 10 | 9 | H08-glob | — | — | 0.0000 | 100.0 |
| solo-lead vs cand-devstral-small2 | 4 | 0 | H02-cron-next, H03-json-patch, H07-sqlite-rebuild, H08-glob | — | — | 0.0000 | 100.0 |
| solo-lead vs cand-glm47-flash | 4 | 0 | H02-cron-next, H03-json-patch, H07-sqlite-rebuild, H08-glob | — | — | 0.0000 | 100.0 |
| solo-deep vs solo-rocm | 10 | 8 | H08-glob | H07-sqlite-rebuild | — | 0.0000 | 100.0 |
| solo-deep vs solo-lead-1 | 10 | 7 | H03-json-patch, H08-glob | H07-sqlite-rebuild | — | 0.0000 | 100.0 |
| solo-deep vs bon3-lead | 10 | 8 | H08-glob | H07-sqlite-rebuild | — | 0.0000 | 100.0 |
| solo-deep vs cand-devstral-small2 | 4 | 0 | H02-cron-next, H03-json-patch, H08-glob | — | H07-sqlite-rebuild | 0.2500 | 75.0 |
| solo-deep vs cand-glm47-flash | 4 | 0 | H02-cron-next, H03-json-patch, H08-glob | — | H07-sqlite-rebuild | 0.2500 | 75.0 |
| solo-rocm vs solo-lead-1 | 10 | 8 | H03-json-patch | — | H08-glob | 0.1000 | 90.0 |
| solo-rocm vs bon3-lead | 10 | 9 | — | — | H08-glob | 0.1000 | 90.0 |
| solo-rocm vs cand-devstral-small2 | 4 | 0 | H02-cron-next, H03-json-patch, H07-sqlite-rebuild | — | H08-glob | 0.2500 | 75.0 |
| solo-rocm vs cand-glm47-flash | 4 | 0 | H02-cron-next, H03-json-patch, H07-sqlite-rebuild | — | H08-glob | 0.2500 | 75.0 |
| solo-lead-1 vs bon3-lead | 10 | 8 | — | H03-json-patch | H08-glob | 0.1000 | 90.0 |
| solo-lead-1 vs cand-devstral-small2 | 4 | 0 | H02-cron-next, H07-sqlite-rebuild | — | H03-json-patch, H08-glob | 0.5000 | 50.0 |
| solo-lead-1 vs cand-glm47-flash | 4 | 0 | H02-cron-next, H07-sqlite-rebuild | — | H03-json-patch, H08-glob | 0.5000 | 50.0 |
| bon3-lead vs cand-devstral-small2 | 4 | 0 | H02-cron-next, H03-json-patch, H07-sqlite-rebuild | — | H08-glob | 0.2500 | 75.0 |
| bon3-lead vs cand-glm47-flash | 4 | 0 | H02-cron-next, H03-json-patch, H07-sqlite-rebuild | — | H08-glob | 0.2500 | 75.0 |
| cand-devstral-small2 vs cand-glm47-flash | 4 | 0 | — | — | H02-cron-next, H03-json-patch, H07-sqlite-rebuild, H08-glob | 1.0000 | 0.0 |
