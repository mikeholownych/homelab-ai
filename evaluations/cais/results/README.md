# CAIS live evaluation bundles

Produced through the production gateway from the controller (gateway-only worker access).

| Bundle | Profile | Capability | Result | Notes |
|---|---|---|---|---|
| `coding.routine-ac0e2c1189e0-20261105T141722Z.json` | Qwen3.6-35B-A3B Q4_K_M, lead, intel-arc-pro-b65-32g | coding.routine | not qualified | **Flawed evidence, superseded.** Repeats were served from the gateway response cache and 3 trials were quota rejections (6 rpm). Kept as the record that led to runner fix b752c41. |
| `coding.routine-ac0e2c1189e0-20261105T143248Z.json` | same | coding.routine | **not qualified**: 9/12 tasks, LB 0.567 < 0.6 | Clean: 38 fresh generations, 0 cache hits, 0 rejections (gateway evidence); rescore 0 mismatches. T10 and T11 fail both repeats; T07 unstable. |

No grant was recorded. The criteria were not changed to obtain one.
