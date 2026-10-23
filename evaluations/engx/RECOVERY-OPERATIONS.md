# Candidate recovery operations and qualification

All appliance changes run through Ansible. Transactions use the deployed clean
controller snapshot and its hash-checked tooling. The canonical journal is
`~/.local/share/aihost/reconcile/candidate/active.json`; ownership uses the same
`lock/ansible-snapshot.lock` inode as scheduled reconciliation. Never remove that
lock file or change the snapshot while an unresolved transaction exists.

The reconciliation user service calls `candidate_recovery.py recover-if-present`
before normal convergence. Recovery restores the declared production configuration
and runs the pinned independent verifier. The normal snapshot runner rechecks the
journal after acquiring its lock, closing the race between recovery preflight
and normal reconciliation. Pending or malformed journals block convergence.
Lock contention returns 73; an unresolved normal-convergence guard returns 75.

For physical transactions, supply `--baseline-playbook` and `--verify-playbook`
as `playbooks/verify_candidate_restoration.yml`. Evidence is written under the
journal directory and run ID, outside the source tree. Baseline capture checks
production before lending the GPU. Verification checks actual service states,
the unaffected worker's PID/start/restart identity, client registry digest,
gateway release, kernel identity, admitted workers, aliases, trusted-controller
TLS and fresh completions from both production models. Credentials stay on stdin
and credential-bearing Ansible tasks use `no_log`.

Use `controller_candidate_transaction.yml` for normal operator entry or the
recorded runner for externally managed drill units. Direct administrative calls
to `candidate.yml` remain possible and bypass the durable transaction; route all
qualification through the transaction entrypoint. CLI fault hooks are opt-in:
`--fault-point after-workers|after-swap` exercises partial and completed swaps;
`--allow-restore-fault` honors a private `restore-fault` marker only for that run.
Remove the marker through Ansible before retrying recovery. The bounded
`candidate_drill_barrier.yml` holds a candidate for controller/service fault
injection and deliberately reports the experiment as failed on release.

## Acceptance ledger

The source implementation and passing local tests do not establish production
qualification. Bind each of these gates to the exact source SHA and raw evidence:

1. Full repository `make quality`: lint, all tests, syntax, check mode, both cold
   container idempotency gates and tuning idempotency, as run by GitHub quality CI.
2. Successful exact-source CI job, including its complete step/job disposition.
3. Scheduler deployment and scheduled recovery followed by normal convergence.
4. Physical normal lead swap, partial deep swap, completed-swap failure,
   controller SIGTERM/SIGKILL, deep candidate process death, blocked restoration,
   and actual scheduler lock contention.
5. Independent production verification after each disruptive drill and at the end;
   retain baseline/restoration records, durations, event history, service/kernel
   logs and explicit failures even when restoration succeeds.

The scheduler recovery preflight must never silently clear a failed experiment.
A recovered run retains `failed`, `not_completed`, or `not_requested` as appropriate.
Use `restored_verified` only for the restoration disposition. Unknown or stale
GPU measurements are not evidence of available capacity. These recovery drills
do not promote a new model/runtime or resolve prior model-quality/headroom gaps.
