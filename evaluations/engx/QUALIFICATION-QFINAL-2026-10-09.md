# Q-FINAL production qualification — 2026-10-09

## Promoted production state

Promotion commit `998189a96a3c9e827ced34999201b0e5418279a8` pins Qwen3.6-35B-A3B on the lead pool at reasoning budget 8192
and Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M on the deep pool at budget 4096. The candidate was removed and Ansible restored the
production workers (`82 ok, 7 changed, 0 failed` for the initial promotion). Flash-Next uses the qualified 65,536 context and
lazy mmap flags. The promotion inventory carries digest-keyed capability evidence for both selected artifacts.

After Q-FINAL, gateway cleanup commit `159898f` removed the unused static `max_output_tokens` worker field from the runtime,
inventory and tests. Ansible installed versioned release `t5820-gateway-159898f` (`f695292` inventory commit; 34 ok, 6 changed,
0 failed). A fresh OpenCode request to `t5820/engineering/b0` returned `READY`; the gateway remained active and reported release
identity `t5820-gateway-159898f`. The existing live workers were not restarted by this gateway-only deployment.

Remote, authenticated OpenCode-scope production checks:

- Before reboot, `engineering/deep` returned HTTP 200 from Flash-Next. Evidence: `results/candidate-promote-20261009/flashnext-production-smoke.json`.
- After reboot, both `engineering/b0` and `engineering/deep` returned HTTP 200 and `READY`, served by Qwen3.6 and Flash-Next.
  `/v1/models` reported exact artifact digests, contexts, budgets and verified tools, parallel tools, structured output,
  streaming, reasoning control and output-contract evidence. Evidence: `results/candidate-promote-20261009/post-reboot-production-smoke.json`.
- After rollback restoration, both production aliases again returned HTTP 200 and the expected models and digests, with the
  same verified capabilities. Evidence: `results/candidate-promote-20261009/restored-production-smoke.json`.

## Reboot and startup behavior

The first controlled reboot (`reboot-verify.log`) returned with both B65 devices enumerated, but the workers initially failed
systemd namespace setup because `/run/user/999` did not yet exist. systemd recovered after the runtime directory appeared.
Inspection showed that worker units had `After=user-runtime-dir@999.service` without a dependency that starts that service.

The llama worker unit now both orders after and requires `user-runtime-dir@{{ llama_cpp_container_uid }}.service`. Ansible
converged the unit change (`84 ok, 3 changed, 0 failed`) and a second controlled reboot passed the two-GPU assertion. Boot ID
changed from `c85b1ff3-2867-4cf6-8279-6c2863aa4f23` to
`1735e787-735f-469d-bc36-3a5d9992336f`. Both model processes loaded, both B65 devices enumerated, gateway health reported
2/2 routable workers, and gateway/worker `NRestarts` were all zero. There were no runtime-directory namespace failures in
the second boot. Evidence: `results/candidate-promote-20261009/reboot-verify-runtime-dir-fix.log`.

The imported generic `validate.yml` summary still says `NOT_TESTED` for 22 unrelated profile checks (including CPU identity,
VRAM, Level Zero, PyTorch XPU, PCIe/ReBAR and Vault). It reported zero blocking failures and zero failed checks. Those 22
checks remain unproven by that aggregation; direct evidence above only establishes the enumerated GPU PCI IDs, model loads,
gateway health and inference routes.

The first attempt at the controlled reboot stopped before rebooting because the playbook supplied unsupported `max_wait` to
`ansible.builtin.reboot`. That option was removed; `--syntax-check` passed, and the controlled reboot then ran successfully.

## Rollback and restoration

The rollback was materialized in a disposable detached worktree by reverting the promotion commit (`ede7da5`), then Ansible
re-converged the pre-promotion inventory (`85 ok, 5 changed, 0 failed`). The old lead and deep model files were confirmed
present before the drill. The candidate alias was absent, the gateway was healthy with both old workers, and the old lead model
served a default production request.

Recorded limitation: with the pre-promotion Qwen3.5 deep worker, a default `engineering/deep` request returns HTTP 422
`capability_unsupported` because the loaded engine observation does not advertise `reasoning`. A request with
`X-AIHost-Reasoning: off` returned HTTP 200 from Qwen3.5. An attempted inventory declaration did not change this because
observed engine capabilities take precedence over inventory declarations. Thus model rollback and re-convergence were proven,
but the prior default reasoning route is not a fully equivalent fallback under the current capability gate. Evidence, including
both outcomes, is in `results/candidate-promote-20261009/rollback-smoke.json`.

The promoted inventory was then re-converged (`85 ok, 5 changed, 0 failed`). The final `/health` snapshot showed 2/2 healthy,
routable workers; all three service restart counters were zero. Both production aliases passed another authenticated request.

## Validation review and second rollback drill (2026-10-09)

The rollback limitation above was a missing evidence record, not a model limit. The gateway's R9 gate counts `reasoning` only
from the engine declaration or verified evidence, and Qwen3.5's chat template sets neither llama.cpp reasoning flag. Its bounded
Phase B run on the same file (sha256 `84b5f7f1...`, re-hashed on the host) reasoned on 61 of 61 attempts. That run is now the
digest-keyed verified `reasoning` record. A second drill (revert `c04d678` over `b7ef53d`; release `t5820-gateway-3d9dea9`)
converged with 82 ok / 9 changed / 0 failed. A default `engineering/deep` request returned 200 from Qwen3.5 with reasoning, and
`/v1/models` reported reasoning `verified`. The promoted config was restored (85 ok / 6 changed / 0 failed). Both aliases
returned 200 on the promoted artifacts, 2/2 workers, evidence chain valid, zero restarts. Evidence:
`results/rollback-drill-20261009/`.

Deploy incident during the review: stopping the gateway for release `t5820-gateway-c241229` hung until systemd's SIGKILL
(11:49:11-11:59:41 UTC, 10.5 min without a serving gateway). Both listeners were still serving, the main thread was parked, and
there was no stop thread or traceback. The SIGTERM handler started a thread from signal context. Release `3d9dea9` records the
signal in the handler and stops on the main thread, with a SIGUSR1 stack dump. Its own stop is tested in a subprocess (and 10/10
under Python 3.14), and the next deploy stopped in under a second.

`output_contract_compliance` is now machine-verified (`qualify.py contract`) on every production path, replacing the prose
citations; see `results/contract-20261009/`.

## Disposition

Q-FINAL is **satisfied**: promotion, post-reboot operation, and rollback/re-convergence (including the default deep route) are
proven. The 22 generic `validate.yml` checks above remain `NOT_TESTED` by that aggregation and are listed in the closeout report.
