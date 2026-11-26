# Nexus E2E three-worker accuracy harness

Stage-gated evaluation of whether coordinated use of the three local workers
improves **task acceptance** versus solo baselines. Spec:
`docs/superpowers/specs/2026-11-24-nexus-e2e-three-worker-accuracy-design.md`.

## Contract (Stage 0)

| Rule | Meaning |
|------|---------|
| Front door | All calls through `https://10.0.8.5:8443` (`ai-5820-01`). Never hit worker ports. |
| One call → one worker | Gateway routing unchanged; collaboration lives in this harness. |
| Acceptance | Hidden/deterministic oracle pass **and** a complete evidence packet. |
| Non-acceptance | Model self-grading, peer “LGTM”, or majority vote. |
| Corpus (Stage 1) | engx **hard** (`ENGX_CORPUS=hard`). Digest recorded per run. |
| Pins | Solo baselines pin `engineering/deep`, `engineering/lead`, `engineering/interactive-rocm`. |
| Same-artifact constraint | Live `artifact_digest` for lead and rocm must match. If they diverge, the run fails unless the plan is updated and `--allow-digest-divergence` is set. |
| Cache | Requests set `X-AIHost-Cache: bypass` so repeats are fresh generations. |

## Metrics

**Primary:** accepted task rate (oracle pass), defect escape (dual+ only), evidence completeness.

**Secondary (reported, not used to pick a winner over accuracy):** wall time, tokens, attempts, worker call counts.

## Layout

```
evaluations/nexus_e2e/
  README.md
  schema/evidence_packet.schema.json
  drivers/solo.py          # Stage 1
  drivers/dual.py          # Stage 2 (not until authorized)
  drivers/triple.py        # Stage 3 (not until authorized)
  scripts/capture_fleet_identity.py
  evidence/<stamp>/        # fleet_identity.json, solo_*, summaries
```

## Capture fleet identity

```sh
.venv/bin/python evaluations/nexus_e2e/scripts/capture_fleet_identity.py \
  --base https://10.0.8.5:8443 --token-file - \
  --out evaluations/nexus_e2e/evidence/<stamp>/fleet_identity.json \
  < <(python3 -c "from pathlib import Path
...print key...")
```

Prefer piping a scoped client token. Do not commit tokens.

## Solo baselines (Stage 1)

```sh
export ENGX_PYTHON=.venv/bin/python
.venv/bin/python evaluations/nexus_e2e/drivers/solo.py \
  --pin deep --base https://10.0.8.5:8443 --token-file - \
  --reps 3 --max-attempts 3 --max-tokens 8192 \
  --stamp <stamp> --out evaluations/nexus_e2e/evidence/<stamp> \
  < <(…token…)
```

Pins: `deep` → `engineering/deep`, `lead` → `engineering/lead`,
`rocm` → `engineering/interactive-rocm`.

After all three pins: `solo_baselines.json` aggregates accepted rates.

## Best-of-n (quality-levers campaign)

Execution-gated selection — no LLM judge. Requires `ENGX_TEMPERATURE>0` for sample diversity.

```sh
evaluations/nexus_e2e/scripts/run_bon_vs_solo.sh <stamp> lead 1
```

See `docs/superpowers/specs/2026-11-25-local-coding-quality-levers-design.md`. Stage 3 collaboration remains frozen.

## Dual baselines (Stage 2)

Model-diverse pairings only (`deep`↔`lead`). lead↔rocm is refused while digests match.

```sh
.venv/bin/python evaluations/nexus_e2e/drivers/dual.py \
  --pairing deep-lead --base https://10.0.8.5:8443 --token-file - \
  --reps 3 --stamp <stamp> --out evaluations/nexus_e2e/evidence/<stamp> \
  < <(…token…)
```

Or: `evaluations/nexus_e2e/scripts/run_dual_baselines.sh <stamp> 3`

Compare: `scripts/compare_dual_vs_solo.py --evidence-dir …` → `dual_vs_solo.md`.

## Non-goals

InferSSD promotion, tok/s campaigns, gateway multi-agent merge, Stage 2+
collaboration until operator-authorized, inventory/routing changes.
