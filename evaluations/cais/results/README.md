# CAIS live evaluation bundles

Produced through the production gateway from the controller (gateway-only worker access).

| Bundle | Profile | Capability | Result | Notes |
|---|---|---|---|---|
| `coding.routine-ac0e2c1189e0-20261105T141722Z.json` | Qwen3.6-35B-A3B Q4_K_M, lead, intel-arc-pro-b65-32g | coding.routine | not qualified | **Flawed evidence, superseded.** Repeats were served from the gateway response cache and 3 trials were quota rejections (6 rpm). Kept as the record that led to runner fix b752c41. |
| `coding.routine-ac0e2c1189e0-20261105T143248Z.json` | same | coding.routine | **not qualified**: 9/12 tasks, LB 0.567 < 0.6 | Clean: 38 fresh generations, 0 cache hits, 0 rejections (gateway evidence); rescore 0 mismatches. T10 and T11 fail both repeats; T07 unstable. |
| `coding.complex-ac0e2c1189e0-20261105T153205Z.json` | same (lead) | coding.complex | **not qualified**: 6/10 tasks, LB 0.401 < 0.45 | Clean (42 fresh generations, 0 cache hits, 0 rejections); rescore 0 mismatches. H03, H07, H08 fail both repeats; H02 unstable. |
| `coding.routine-935587187e4b-20261105T153205Z.json` | Qwen3.8-Flash-Next IQ1_M, deep (reasoning on, 4096), intel-arc-pro-b65-32g | coding.routine | **qualified**: 10/12 tasks, LB 0.658 ≥ 0.6 | Clean (37 fresh generations, 0 cache hits, 0 rejections); rescore 0 mismatches; envelope 17,077 tokens. T11 fails both repeats; T02 unstable. Slow: trial latency p50 229 s, p95 1,177 s. Granted as `q-coding.routine-f6cc01c8efc4-028dcdee`, expires 2027-01-04. |

Grants exist only for evidence that passed the unchanged criteria. The criteria were not changed to obtain any result.
