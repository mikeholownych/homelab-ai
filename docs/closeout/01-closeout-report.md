# AIHOST closeout report (2026-10-11)

Scope: the operator brief of 2026-10-07 ("complete all remaining authorized non-deferred work") as reconciled in
`00-reconciliation.md` and `tasks/todo.md`. Nexus development and "future evolution" are out of scope.

## Status

**`AIHOST_WORKSTREAM_COMPLETE_PROVEN_WITH_LIMITATIONS`**

Every required item is complete and evidenced on the appliance, including the Qwen3.6 12,288-token budget point
(row 37), which confirmed 8192. The lead-pool reasoning policy (V5) is decided: off by default, 8192 opt-in. Limitations are
listed below.

## Production state (verified 2026-10-11)

| Pool | Model | Artifact | Reasoning budget | Alias policy |
|---|---|---|---|---|
| lead (GPU 0) | Qwen3.6-35B-A3B UD-Q4_K_M | `sha256:ac0e2c11…` | 8192 (Q-BUDGET, 12,288 adds nothing) | `engineering/lead` and the default rule: reasoning off; `engineering/lead-reasoning`: on, 8192 |
| deep (GPU 1) | Qwen3.8-Flash-Next GSQ RCO IQ1_M | `sha256:93558718…` | 4096 (Q-BUDGET: 8192 adds nothing) | `engineering/deep`: reasoning on |

Gateway release `t5820-gateway-6a3a52e`, healthy, 2/2 workers routable, evidence chain valid. Host validation
(2026-10-11T02:18:26Z, `results/validation-20261010/validation_summary-post-sweep.txt`): **PASS (healthy)**, 0 failed, 0 not
tested, 5 not applicable by inventory declaration. Controller-side reconciliation runs hourly (snapshot `6c36739`). PCIe
ASPM policy `performance` live and persisted.

## Evidence index

| Gate | Result | Evidence |
|---|---|---|
| Q-BUDGET Flash-Next | 2048 80% · **4096 90%** · 8192 90% (1.7x time) | `evaluations/engx/QBUDGET-2026-10-08.md` (`4fb2597`) |
| Q-BUDGET Qwen3.6 | 2048 46.7% · 4096 70.0% · **8192 76.7%** · 12288 66.7% (budget reached 38%) | same; `results/qbudget-20261010/` |
| Q-TOOLS | 7 checks x3 and 20 Nexus replays: all pass, both models | `QUALIFICATION-FLASHNEXT-2026-10-08.md`, `QUALIFICATION-QWEN36-2026-10-09.md` |
| Q-LONGCTX | 12/12 needles to ~59.9K (Flash-Next) / ~55.8K (Qwen3.6); clean over-context 400 | same |
| Q-MMAP | page-cache and major-fault metrics live; Flash-Next faults flat under load | `5548f3f`, `results/qmmap-20261008/` |
| Output contract | 36/36 machine checks on every production path | `072357a`, `results/contract-20261009/` |
| Q-FINAL | promotion, two reboots, rollback drill with the default deep route working | `QUALIFICATION-QFINAL-2026-10-09.md`, `ff4f888` |
| Vault | AppRole login; all eight consumer credentials match Vault; client rotation end to end (old 401, new 200) | `docs/vault.md`, `results/vault-r6-20261010/` |
| Swap recovery | drilled failure after a completed swap: run fails naming the task; candidate removed; production worker and gateway restored; lead completion routed to worker1 and validated in the audit log | `results/candidate-recovery-drill-20261011/` |
| Reconciliation | controller timer; stamp observed by the validator; steady state changes only the stamp | `results/reconcile-20261010/` |

## Defects found and fixed during closeout (all tested and deployed unless stated)

- `/v1/models` misreported b0's reasoning policy (`c241229`).
- The gateway stop hung for 10.5 minutes (SIGTERM handler started a thread). The handler now only records the signal,
  and SIGUSR1 dumps stacks (`3d9dea9`).
- The rollback target lacked verified reasoning evidence and returned 422 on the default deep route. Fixed with
  digest-keyed evidence and re-proven by a drill (`072357a`, `ff4f888`).
- `output_contract_compliance` cited prose instead of a check; it is now machine-verified (`072357a`).
- The qualification token was exposed in a transcript; it was rotated through Ansible and the old token returns 401 (`d10ad5b`).
- An inherited FORCE_COLOR failed a sealed test (`fb8c2bb`).
- The validator published unobserved PASS results (`f7f6180`, `83b5847`). Fixed in `f398935`, observed live since 2026-10-10 20:23.

## Operator decision recorded

1. **Lead reasoning policy (V5, decided 2026-10-11).** Reasoning stays off by default on the lead pool
   (`engineering/lead`, `engineering/b0` and the default rule). 8192 reasoning is available explicitly for demanding
   tasks through `engineering/lead-reasoning`. Basis: +6.7 points (70.0% off vs 76.7% at 8192) at 2-3x the time per
   task, and no observed demand for it during dogfood troubleshooting.

## Limitations and observations

- **How to read validation outcomes.** An *observed* check can still report insufficient evidence:
  `single_gpu_inference` passes only on a validated production completion per worker in the gateway evidence chain;
  worker health alone never satisfies it, and an idle worker is NOT_TESTED. NOT_APPLICABLE (for example
  `llama_cpp_fallback`, retired with vLLM) is a documented disposition from inventory with its reason recorded, not a
  passing test.
- **Reconciliation pauses while a candidate holds a GPU.** `inference.yml` refuses to converge during exclusive GPU
  use, so no stamp is written and `scheduled_reconciliation` turns FAIL once the stamp is older than 2 h. That is the
  intended signal for the duration of a qualification window, not a reconciliation defect.
- **Candidate swaps fail safe, within the drilled scope.** A swap that fails converges the production configuration
  again and still fails the run (`f54cc7a`), after the 2026-10-10 abort left the lead pool down (`f061a95` fixed that
  cause). The live drill fails *after a fully completed swap*, a demanding recovery case; it proves that recovery path, not every partially
  completed state (for example a failure while the candidate model is still loading, or inside the gateway role). Those
  paths share the same rescue but are covered only by the contract test.
- **ASPM tuning was ineffective until 2026-10-11.** The profile set `pcie_aspm=performance`, which the kernel does not
  take as a policy (`pcie_aspm=` accepts `off|force`); the live policy stayed `default` and nothing checked it. Fixed in
  `30d405b`/`badb5c2`: `pcie_aspm.policy=performance` persisted in GRUB, applied at runtime on drift (the kernel
  accepted it, so the firmware grants the OS ASPM control), the duplicate `transparent_hugepage=always` removed, and
  `os_tuning_pcie_aspm` now compares the live policy with the profile.
- **The validation text summary prints check labels for some observed values** (for example the tuning checks); the
  observed values themselves are in `validation.json`. Cosmetic.
- **Gateway release identity drifted once.** `6a3a52e` changed gateway code (client `reasoning_effort` mapped to
  reasoning profiles) while inventory still named `b41eaa1`, and a reconcile deployed it under that name. The release
  id now names the code (`t5820-gateway-6a3a52e`), and `tests/test_gateway_release_identity.py` fails on any future drift.
- **Observability tracing pipeline vs. native Nexus instrumentation.** Distributed tracing infrastructure (Grafana Tempo v3.1.0 with OTLP receivers on :4317/:4318, VictoriaMetrics remote-write service-graph generation, and Loki `derivedFields` log-to-trace linking) is operational and verified via live inference with synthetic OTLP telemetry. Native in-process instrumentation (automatic trace context propagation across the client, gateway, and worker processes) and end-user browser click-through remain unproven.