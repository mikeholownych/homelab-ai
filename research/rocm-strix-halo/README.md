# ROCm Strix Halo engine selection (`ai-ms-s1-max-01`)

Lab-only campaign on ROCm 7.2.0 / gfx1151. Spec:
`docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-engine-selection-design.md`.

## Phases
- **2a** Model shortlist → `model-shortlist.md`
- **2b** Smoke: llama.cpp HIP, vLLM ROCm, SGLang
- **2c** Deep bake-off (survivors) → scorecard + `evidence/<ts>/recommendation.md`
- **2d** Lab wire winner via Ansible (not production)

## Scorecard weights (balanced)
| Axis | Weight |
| --- | --- |
| Quality (tool/contract probes) | 0.30 |
| TTFT (p50/p95 cold+warm) | 0.30 |
| Sustained tok/s (c=1/2/4) | 0.20 |
| Ops fit | 0.20 |

## Rules
- One engine process on the APU at a time.
- Containers preferred; native only with archived container blocker.
- Reuse `../sycl-optimization/harness/engine_sweep_client.py` against `127.0.0.1:<port>`.
- Do not touch `inventory/production`.