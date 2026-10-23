# Candidate recovery control-flow qualification

Base source: `f841d880f55ebc729e174da5e0a7bad7873dd5b6`.

The Guaardvark review suggested testing resource ownership across cancellation,
crashes and restarts. This change executes the existing `playbooks/candidate.yml`
byte-for-byte against isolated, file-backed localhost role doubles. It does not
modify candidate lifecycle behavior, production inventory, workers or the gateway.

## Acceptance and evidence boundary

| Scenario | Required observation |
| --- | --- |
| Successful swap and explicit removal | Lead configuration stops, candidate appears, deep configuration remains equal; removal restores both original role configurations. |
| Worker role fails after recording candidate state | Rescue restores both original configurations; Ansible still fails. |
| Gateway role fails after recording candidate state | Same restoration and failed disposition. |
| Existing post-swap drill hook | Same restoration and failed disposition. |
| Controller process group receives SIGTERM | Candidate configuration remains; a separate explicit absent run restores it. |
| Controller process group receives SIGKILL | Same characterized limitation and explicit recovery. |
| Competing lock requester | Requester is refused repeatedly and cannot release the existing owner's lock. |
| Killed lock holder | A new process can acquire the existing lock file after the holder and descendants die. |

Seven test methods cover eight scenarios (worker and gateway failures are
subtests). Tests use real Ansible, local subprocesses and kernel file locks.
GPU probes, model processes, HTTP draining, role internals and service readiness
are not exercised. A passing test that characterizes interrupted-controller state
is **not** evidence of automatic recovery. Role snapshots prove configuration
delivery, not physical service restoration.

Run through Ansible:

```sh
ANSIBLE_CONFIG=ansible.cfg ansible-playbook -i localhost, playbooks/qualification_recovery_contract.yml
```

The entrypoint fails if Ansible or flock is missing; direct unittest discovery
skips when dependencies are absent. Keep those skips distinct from qualification.

Local validation on 2026-10-23: seven methods passed directly in 82.336 seconds,
then passed through the Ansible entrypoint in 87.433 seconds. The outer play
reported `ok=3 changed=0 failed=0 skipped=0`; syntax validation also passed.
Runtime: ansible-core 2.20.4, Python 3.13.7. This is not the repository's complete
quality gate or its pinned CI environment; lint and the full suite were not run.

## Durable transaction implementation

`evaluations/engx/candidate_recovery.py` now provides `run` and `recover` actions,
exposed through `playbooks/controller_candidate_transaction.yml`. The journal is
private, atomically replaced and fsynced, and is written before the first swap.
Every stage is bound to a clean checkout SHA, tracked source content, inventory
content, lock path and Ansible executable hash. Recovery refuses identity drift.
Old completed records are archived before a new run; unresolved records block it.

The runner acquires the actual reconciliation file lock itself and passes that
open descriptor to each Ansible child. A surviving child therefore retains
ownership after wrapper death. It never infers ownership from an unrelated
process's lock and never removes the lock file. Ordinary failures converge
`candidate_state=absent` and then invoke a separately supplied verification
playbook. Failed restoration and failed verification remain unresolved. Failed
experiments remain failed even after verification succeeds. When no experiment
playbook was supplied, the experiment outcome is `not_requested`.
Interactive interrupts and bounded command timeouts terminate and reap the local
Ansible process group before restoration. Ansible scratch files are placed in
the private journal directory, outside the pinned checkout, so interruption
leftovers cannot falsely mark that checkout dirty and block recovery.

The `recover` action must be invoked independently after controller loss. This
change **does not install a timer, systemd supervisor, or automatic recovery actor**.
The Ansible entrypoint defaults to recovery and requires explicit inventory,
state directory outside the checkout, and reconciliation lock. For a new run,
it also requires a declared candidate profile and verification playbook. It does
not default these ownership inputs to production values.
The guard applies to this entrypoint; direct calls to the existing candidate
playbook are not yet blocked. Production adoption must make the journal directory
and reconciliation lock canonical and route all candidate changes through it.
The scheduled reconciliation runner is not changed here and does not inspect
this journal. Its pending-run behavior must also be integrated and qualified
before treating the transaction as an appliance-wide ownership guarantee.

The required verifier's contents are pinned, but its physical acceptance coverage
is not inferred by the runner. A valid production verifier must check services,
admission, aliases, fresh completions, and absence of candidate services. The
fixture verifier independently checks file-backed role configurations only.

## Remaining operational requirements

`candidate.yml` can run rescue only while its controller is alive. A held
reconciliation lock provides exclusion but is not itself a recovery supervisor.
These tests do not establish whether the deployed reconciliation timer would
later repair a particular interrupted physical swap, or how long that takes.

Before an interruption drill on the appliance, install and qualify a recovery
actor outside the interrupted process group and a production verifier. Recovery
must acquire the same lock, pin and verify the source/inventory identity, converge
the original declared state through Ansible, and independently verify services,
gateway admission, aliases and fresh completions. Preserve the failed experiment
as failed even when restoration succeeds. A failed restoration must retain its
run record and block a new swap until resolved.

Physical acceptance must include partial-swap interruption, controller cancellation,
controller death, candidate service death, restoration failure, contention and a
subsequent clean run. Record unaffected-worker identity and availability, in-flight
drain behavior, time to restored capacity, kernel/driver errors, and measured GPU
memory with unknown/stale readings explicit. Do not use a successful local fixture
as permission to kill a production controller or GPU worker.

Source/inventory hashing is not an attestation of external Vault state, dynamic
inventory output, all Ansible library dependencies, or remote runtime state.
Pinning the Ansible executable alone does not pin its imported Python libraries.
Static reviewed inventory and the repository's pinned tooling remain prerequisites.
Remote asynchronous jobs can outlive local Ansible processes and need their own
cancel/expiry and completion checks; a local file lock cannot stop those jobs.

The durable transaction tests exercise failed experiments, failed restoration,
failed verification, dirty source, changed committed recovery source, wrapper
death with a surviving lock-owning child, and interactive interruption. They use
the real runner and real Ansible with the same isolated role doubles. The new
playbooks are included in the Makefile syntax gate; pytest discovery includes
both execution test modules.

## Final local validation

Repository requirements were installed with hash verification in an isolated
temporary environment: ansible-core 2.21.3, ansible-lint 26.8.0, pytest 9.1.1,
and yamllint 1.38.0, running under Python 3.13.7. The CI workflow uses Python
3.12; this is local evidence and not a claim that CI ran for this change.

- Original execution contracts: 7 passed through pinned Ansible, 113.206 seconds.
- Final durable transaction contracts: 7 passed through pinned Ansible,
  100.840 seconds, after the interactive-interrupt correction.
- Existing restoration, qualification exclusion and drain contracts: 4 passed.
- Both new playbooks passed syntax validation and YAML lint.
- Targeted offline Ansible lint passed with zero rule failures or warnings for
  the two new playbooks. Collection installation was skipped in offline mode;
  these playbooks use built-in modules only.
- Python compilation and Git whitespace checks passed.

The complete repository quality gate, CI, physical GPU drills, scheduler
integration, and production verification were not run. The retained earlier
interrupt failure showed why Ansible scratch data must live outside the source
checkout; its corrected regression and complete transaction group then passed.

This package does not implement Nexus task outcomes or an ancillary accelerator
audit; those remain separate follow-up work from the repository review.
