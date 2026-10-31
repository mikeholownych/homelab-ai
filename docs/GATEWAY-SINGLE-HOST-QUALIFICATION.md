# Gateway qualification on one host

Host-level high availability is outside this gateway's acceptance scope. Acceptance means correct
client contracts, bounded resource use and overload, observable partial failure, recoverable releases,
and verified state retention on ai-5820-01. A healthy listener alone is insufficient.

## Evidence and gates

The runtime release, runner hash, timestamps, individual failures and raw measurements belong in each
receipt. Never replace a failed receipt with a later passing run. CI validates the runners and runtime;
only explicit live runs qualify the deployed host. Store raw receipts under evidence/gateway-quality.
Credentials arrive over stdin or existing systemd/SSH facilities; never put tokens in command arguments,
commits, receipts or generated-content logs. No warning is accepted by the strict gateway gate.

| Gate | Required observation | Runner / limits |
| --- | --- | --- |
| HTTP contracts | Structured output, tool arguments/results, SSE content and tool deltas on each declared model | evaluations/qualify_single_host.py contracts; 128 output tokens, 30-second deadline |
| Exact instruction compliance | Explicit exact-text result; retain model deviations separately from transport success | Unconstrained and grammar-constrained cases are distinct; do not waive failed cases |
| Installed client | Actual Nexus discovery, exact request counting, nonstream, stream callbacks and tool round trip | evaluations/qualify_nexus_client.mjs; record loaded module hash, Node version and checkout dirtiness |
| Mixed workload | 15 minutes, at most two probe requests in flight, cache bypass, streaming/nonstreaming and paced readers | evaluations/qualify_single_host.py soak; at most 500 requests; qualification client <=5/minute |
| Resource stability | >=100 health and >=6 resource samples; all strict health checks ready; health p99 <250ms | Memory peak <512MiB; median last-third growth <=max(16MiB,20% of first-third median); FD growth <=4; task growth <=2; same gateway PID |
| Short-prompt latency | >=10 streamed samples/model; measured TTFT p95 <10 seconds for the bounded profile | Report misses and successful goodput; these are initial acceptance targets, not long-context guarantees |
| Worker loss | One unavailable worker produces truthful strict/non-strict health; unaffected alias works; unavailable alias fails closed; restored alias works | evaluations/qualify_gateway_faults.py; worker2 only, idle preflight, appliance-side restart watchdog, timer-state restoration |
| Backup / restore | Copy complete evidence prefix and required sealed predecessors; verify hashes and continuation on a separate restored copy | evaluations/qualify_gateway_restore.py; 512MiB snapshot budget; live evidence never edited |
| Retention | Private, verified controller snapshots; prune whole snapshots only after a new backup verifies | evaluations/backup_gateway_state.py; 7 retained snapshots by default; minimum 2; no live evidence pruning |
| Interrupted release / reboot | Recover an identifiable release with working credentials, evidence and both model aliases | Candidate recovery preflight exists; an actual appliance interruption/reboot drill requires an idle maintenance window |
| Operational visibility | Failure visible in unit state/journal; disk pressure visible; backup freshness checked; notification delivery tested separately | systemctl --user status aihost-gateway-backup.service; existing host disk alerts; external delivery is not proved by local journal entries |

These resource bounds are finite-run gates, not proof of indefinite memory plateau. Paced HTTP readers
of short outputs do not establish kernel-level backpressure for arbitrarily large streams. Existing
synthetic saturation/disconnect tests remain necessary. A general engineering-task accuracy benchmark,
long-context performance, prolonged GPU/thermal qualification and a full Nexus agent-loop evaluation
remain distinct from this small contract suite.

## Concurrent workloads and deadlines

Do not interrupt other clients to make a benchmark pass. Record concurrent client identity and worker
execution windows without storing prompt content. The single-slot workers cannot preempt an existing
long generation. A probe can therefore miss its 30-second admission deadline while the gateway stays
healthy. That is a failed completion/latency observation, even when the deadline error is the correct
bounded-overload response. Never increase deadlines or exclude those samples retroactively.

The initial 31 October live run observed OpenCode activity on the lead worker during probe admission
timeouts. Preserve those failures and the evidence timeline. A dedicated latency promise requires an
explicit workload envelope, admission policy or reserved capacity; do not truncate existing clients'
8192-token requests merely to pass a short-probe benchmark.

## Running qualification

Run the HTTP and fault tools on mike-dev with the existing CA certificate and an ephemeral JSON object
of operator, qualification and ansible-admin tokens on stdin. Required flags are --ca,
--expected-release and --output. The HTTP runner accepts contracts or soak and --duration (120..3600
seconds; production acceptance uses 900). The fault runner is a deliberate worker2 outage, not a
read-only command. It refuses active reconciliation or already-in-flight work, arms a 180-second
appliance-side restart watchdog before stopping worker2, restores worker2 in finally, verifies health
and inference, and restores the controller timer's prior state. Do not run it alongside a soak.

The Nexus runner takes the absolute installed client module path and output receipt as positional
arguments, plus {token,endpoint,release} on stdin. Supply NODE_EXTRA_CA_CERTS in the process environment;
never disable TLS verification. It imports the installed client without rebuilding or changing Nexus.
It qualifies the loaded client library, not the complete agent or the cleanliness of its checkout.

Run the strict automated gate with scripts/check-gateway-quality and GATEWAY_TEST_PYTHON pointing to
the hash-locked test environment. Tests explicitly reject missing/degraded observations, resource
leaks, altered processes, corrupted backups, path traversal and credential inclusion.

## Scheduled gateway-state backup

The reconcile_controller role installs a separate user timer, aihost-gateway-backup.timer, daily with
jitter and catch-up after downtime. Defaults are reconcile_controller_gateway_backup_enabled=true,
reconcile_controller_gateway_backup_host=<controller user>@10.0.8.5,
reconcile_controller_gateway_backup_root=~/.local/share/aihost/gateway-backups and
reconcile_controller_gateway_backup_keep=7. Override the host for a different topology.

The backup job discovers the active gateway release and runs the reviewed snapshot helper with that
release's Python. It transfers a complete, verified evidence prefix plus gateway-state.json and
client-usage.json over host-key-verified SSH. Controller directories are mode 0700 and files 0600.
Only a fully transferred and verified snapshot becomes visible as a completed backup. A private
receipt records the release directory, chain head and record count. The job deletes only its own
UUID-named appliance scratch snapshot; retained appliance evidence and releases are untouched.
Retention deletes whole verified controller snapshots beyond the configured count and refuses to
silently prune a damaged snapshot.

This is a per-file runtime-state backup, not an atomic host image or an authentication/TLS/model
backup. client-usage restoration can roll accounting back to the checkpoint and requires an explicit
operator decision. Authentication material remains under the existing credential-management process.
The older monitoring evidence-sync feature covers a different directory and is not evidence that
current gateway state is protected. Backup failure is visible through the user unit and journal;
verify external notification routing separately. Check backup age after the first scheduled run.

For a restore drill, use qualify_gateway_restore.py restore with a completed snapshot as --source and
a new, separate directory as --target, with the reviewed runtime on PYTHONPATH. It verifies every
snapshot digest, resumes the evidence store, appends a qualification record only to the restored
copy, and verifies continuity. It never replaces live state. The snapshot must include every sealed
predecessor; individual segments cannot be removed independently.

## Acceptance limits and follow-up

A successful finite soak, library test or restore drill does not erase failed workload targets or
untested interruption scenarios. Close each gate only for its recorded profile and runtime identity.
Keep main, pushed branch, pinned controller snapshot and runtime identity explicit. An evaluation-only
or controller-backup change does not change gateway runtime code identity and must not restart workers.
