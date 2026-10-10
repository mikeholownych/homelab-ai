# AIHOST closeout report (draft, 2026-10-10)

Scope: the operator brief of 2026-10-07 ("complete all remaining authorized non-deferred work") as reconciled in
`00-reconciliation.md` and `tasks/todo.md`. Nexus development and "future evolution" are out of scope.

## Status

**`AIHOST_WORKSTREAM_BLOCKED_GPU_WINDOW_FOR_QBUDGET_12288`**

One required item remains: the Qwen3.6 12,288-token reasoning-budget point (reconciliation row 37, "adding points if
needed"). It needs GPU 0 for about three hours, and the operator has reserved inference access for Nexus client work.
Everything else below is complete and evidenced, or recorded as a limitation or an operator decision. This status does not
move required work to a later list.

## Production state (verified 2026-10-10)

| Pool | Model | Artifact | Reasoning budget | Alias policy |
|---|---|---|---|---|
| lead (GPU 0) | Qwen3.6-35B-A3B UD-Q4_K_M | `sha256:ac0e2c11…` | 8192 (provisional, see row 37) | `engineering/lead` and the default rule: reasoning off |
| deep (GPU 1) | Qwen3.8-Flash-Next GSQ RCO IQ1_M | `sha256:93558718…` | 4096 (Q-BUDGET: 8192 adds nothing) | `engineering/deep`: reasoning on |

Gateway healthy, 2/2 workers routable, evidence chain valid, zero restarts since the 2026-10-10 13:08 reboot.

## Evidence index

| Gate | Result | Evidence |
|---|---|---|
| Q-BUDGET Flash-Next | 2048 80% · **4096 90%** · 8192 90% (1.7x time) | `evaluations/engx/QBUDGET-2026-10-08.md` (`4fb2597`) |
| Q-BUDGET Qwen3.6 | 2048 46.7% · 4096 70.0% · 8192 76.7%, still binding 66% | same; 12,288 open |
| Q-TOOLS | 7 checks x3 and 20 Nexus replays: all pass, both models | `QUALIFICATION-FLASHNEXT-2026-10-08.md`, `QUALIFICATION-QWEN36-2026-10-09.md` |
| Q-LONGCTX | 12/12 needles to ~59.9K (Flash-Next) / ~55.8K (Qwen3.6); clean over-context 400 | same |
| Q-MMAP | page-cache and major-fault metrics live; Flash-Next faults flat under load | `5548f3f`, `results/qmmap-20261008/` |
| Output contract | 36/36 machine checks on every production path | `072357a`, `results/contract-20261009/` |
| Q-FINAL | promotion, two reboots, rollback drill with the default deep route working | `QUALIFICATION-QFINAL-2026-10-09.md`, `ff4f888` |
| Vault | AppRole login and all five consumer credentials match Vault (digest) | `docs/vault.md` (`9e4b6c4`) |

## Defects found and fixed during closeout (all tested and deployed unless stated)

- `/v1/models` misreported b0's reasoning policy (`c241229`).
- The gateway stop hung for 10.5 minutes (SIGTERM handler started a thread). The handler now only records the signal,
  and SIGUSR1 dumps stacks (`3d9dea9`).
- The rollback target lacked verified reasoning evidence and returned 422 on the default deep route. Fixed with
  digest-keyed evidence and re-proven by a drill (`072357a`, `ff4f888`).
- `output_contract_compliance` cited prose instead of a check; it is now machine-verified (`072357a`).
- The qualification token was exposed in a transcript; it was rotated through Ansible and the old token returns 401 (`d10ad5b`).
- An inherited FORCE_COLOR failed a sealed test (`fb8c2bb`).
- The validator published unobserved PASS results (`f7f6180`, `83b5847`). Fixed in the repo (`f398935`); **not yet
  re-run on the host** (see below).

## Open: operator action or decision

1. **Q-BUDGET 12,288 (required).** Run `evaluations/engx/qbudget.sh qwen36-lead 12288` when GPU 0 can leave the lead
   pool for about three hours. The lead alias falls back to deep in the meantime.
2. **Lead reasoning policy (decision).** No plain request reasons on Qwen3.6. Only the deep-task fallback does, capped at
   4096. Qwen3.6 scores 70.0% with reasoning off and 76.7% at 8192, at 2-3x the time per task.
3. **Host validation evidence (action).** `/var/lib/local-ai/evidence/validation_summary.txt` (2026-10-10 13:09) is false.
   It claims `scheduled_reconciliation` PASS, but `aihost-reconcile.timer` is not installed. Re-running
   `playbooks/validate.yml` with `f398935` replaces it. The run includes the hardware roles, so it waits for an operator
   window.
4. **Scheduled reconciliation (decision).** Inventory sets `features.scheduled_reconciliation: true`, but the timer is not
   installed. Either install it or set the feature to false. The corrected validator reports it as FAIL until then.
5. **R6 client tokens under Vault (authorization).** `operator`, `qualification` and `ansible-admin` gateway tokens
   are Ansible-generated, not Vault records. This needs Vault policy and KV changes on the Vault host.

## Limitations and observations

- **ASPM tuning is ineffective.** The profile sets `pcie_aspm=performance` on the kernel command line, which the kernel
  does not accept as a policy (`pcie_aspm=` takes `off|force`; the policy is `pcie_aspm.policy=`). The live policy is
  `default`, and no validation check covers ASPM. `transparent_hugepage=always` also appears twice on the command line.
- **Inference checks are not observed.** `single_gpu_inference` and `llama_cpp_fallback` stay NOT_TESTED until a
  collector observes them; production inference is evidenced by Q-FINAL instead.
