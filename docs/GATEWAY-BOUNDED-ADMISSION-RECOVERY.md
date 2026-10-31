# Bounded admission and durable gateway activation

This increment closes two concrete single-host gaps: an opt-in route that need not queue behind a
long lead generation, and appliance-owned recovery of interrupted gateway activation files. It does
not change the existing pinned aliases, client profiles, credentials or the two model worker services.

## Explicit low-wait routing

Select `engineering/interactive` as the model. It is a named routing rule, advertised through
`/v1/models` with the intersection of its workers' capabilities and minimum context limits. It may
use either the lead or deep model: this is an explicit latency/quality tradeoff, not model equivalence.
Alternatively, a generic routed request for `engineering/b0` can opt in with
`X-Task-Class: interactive-fast`. Explicit aliases such as `engineering/lead`, `engineering/deep`
and `engineering/lead-reasoning` bypass task rules and retain their existing model and waiting policy.

Both opt-in rules wait at most 100 ms in each candidate pool's admission queue, use lead then deep,
and request reasoning off with a 1024-token default answer allowance. Existing rules and their
8192-token allowances are unchanged. A caller can still supply its finite output allowance under
existing context/budget policy. If both eligible pools are busy, the gateway returns HTTP 429 with
Retry-After before generation. An earlier overall request deadline still wins. There is no fallback
after partial output. Fallback/canary and legacy worker selection enforce the caller's pool authority.

Example request body (use the client's existing TLS trust and credential handling):

```json
{"model":"engineering/interactive","messages":[{"role":"user","content":"Explain this error briefly."}],"max_tokens":128}
```

The queue budget is **not** an end-to-end latency promise. TLS, body reading, prompt counting, model
prefill and generation retain their own bounds. Validate accepted/completed goodput and TTFT for the
actual workload. The earlier pinned-lead 15-minute result (five admission timeouts; TTFT p95 11.06 s)
is retained. Adding this opt-in route does not turn that recorded failure into a passing measurement.
Unconstrained exact-text model compliance also remains separate from explicit schema/grammar output.

## Persistent activation journal

The role checks for unresolved activation recovery before capturing a new baseline or staging
activation files. A root-only helper journals the previous systemd unit, environment and readiness
probe into `/var/lib/aihost-gateway-activation/pending`, with hashes, original modes, transaction ID,
previous release and service invocation ID. Files and directories are flushed before publication.
No journal is created on an unchanged converge. TLS keys, tokens, registry rotation and model files
are outside this activation transaction and remain under their existing management processes.

After all three target files are written, `arm` seals their hashes and records the service invocation
that must be replaced. Acceptance requires the exact target release, strict readiness, intact armed
files and a new service invocation after arming. This also covers configuration changes that reuse
one runtime release ID. An appliance-owned systemd timer checks pending work every 30 seconds and
catches up after boot. It runs independently of the controller process and its SSH connection.

A prepared transaction expires after 60 seconds; a lost controller cannot leave half-written files
indefinitely. An activation that was armed but never launched has the same short launch bound.
An explicitly failed new service is recovered at the next poll. Legitimate graceful stop/start is
allowed up to 2100 seconds (600-second shutdown grace, up to 1300-second readiness, plus margin).
A healthy, intact new target may be accepted independently if the controller dies before commit;
the controller's later commit is idempotent for that transaction ID.

Rollback validates every baseline digest before changing any activation file. It restores original
bytes/modes, reloads systemd only if unit definitions may have changed, and restarts only when the
old, correct service invocation is not already serving. Recovery progress is persisted so ordinary
polls do not repeat reloads/restarts while waiting for old readiness. Failed recovery or malformed
journal data is latched for manual attention and disarms automatic retries. Original evidence is
retained for diagnosis; it is not silently replaced by a new transaction. A committed receipt is
written before pending cleanup so interruption during cleanup cannot undo an accepted release.

The recovery service uses the existing `aihost-alert@` hook on actual failure. Isolated drills omit
that hook; no external notification delivery is claimed by those tests.

## Verification and limits

`scripts/check-gateway-quality` treats all warnings as errors and includes the admission, authority,
journal state, corruption, same-release identity, cleanup-interruption and reload-gate regressions.
The inventory route table is validated by the runtime and `gateway-routes.schema.json` before deploy.

`evaluations/qualify_gateway_interruption.py --execute --source CHECKOUT --output RECEIPT` is a
**root-only controller-side fault drill**. It creates disposable loopback HTTP fixture services,
runs a real Ansible process through durable mutation barriers, kills that process group, and verifies
that independent systemd recovery restores a half-write, repairs a failed start, or adopts a healthy
target. It uses the actual helper and recovery service confinement, a two-second test cadence, and
no credentials, GPU workers or external notification hook. Its unit files are removed on completion.
It does not run on the inference appliance and does not qualify a full appliance power cycle or
worker cold boot. It qualifies the recovery component; normal role convergence and the unchanged
second run must also be observed on the deployed appliance.

## Read-only operational checks

```sh
sudo /usr/local/libexec/aihost-gateway-activation status --state /var/lib/aihost-gateway-activation
sudo systemctl status aihost-gateway-activation-recovery.timer --no-pager
sudo journalctl -u aihost-gateway-activation-recovery.service -n 30 --no-pager
```

`idle` means no pending activation. The root-only `last.json` receipt records acceptance or recovery.
For `manual_attention`, inspect the private journal and service logs before taking action. Do not
remove the journal merely to bypass the guard. Retained prior releases plus their original pinned
snapshot remain the manual rollback path after a transaction has already committed. Automatic
recovery is not a substitute for tested host backup, reboot procedures or external alert delivery.

## Distribution unit compatibility

The production `systemd_compat` role runs before inference roles. On systemd 258 or newer it
regenerates two locally owned XFS unit shadows from the currently installed vendor files, removing
only `CPUAccounting=` declarations. This setting has no effect on unified cgroups; systemd 259 on
the appliance logs it as removed. See the upstream [resource-control history](https://www.freedesktop.org/software/systemd/man/258/systemd.resource-control.html).
All other bytes, including XFS commands, CPU quota, IO priority and confinement, are preserved.
The role does not disable XFS scrub or change package-owned files. Drop-ins cannot prevent the
manager from parsing the obsolete vendor declaration, so full regenerated shadows are required.

The helper refuses unmanaged overrides and masks before changing either unit. Reconciliation
refreshes shadows after vendor changes, removes its own shadows when upstream fixes/removes the
unit or systemd is downgraded, and reloads the manager only after actual shadow changes. Ansible
check mode predicts the changes without writing or reloading. This is a compatibility workaround
for the installed xfsprogs 6.18.0-3 package, not a claim that all distribution unit warnings are fixed.
Inspect future reload journals; any new obsolete declaration is a new failed warning gate.

The same role installs explicit native oneshot units for the installed cpufrequtils, loadcpufreq
and OpenIPMI package actions. It preserves package start/stop/reload scripts and their configuration
rather than reimplementing hardware detection. CPU-frequency services retain enabled boot policy;
OpenIPMI remains disabled. No service is started/restarted and no governor/module state is changed
by migration. This removes dependency on deprecated `systemd-sysv-generator` conversion; the packaged
shell actions remain an explicit dependency. Owned wrappers yield to future vendor native units or
are removed when their package action disappears. Operator units/masks are refused. Native boot
links are managed directly, avoiding SysV enablement conversion. Cold-boot execution remains an
unqualified gate. Warning acceptance must inspect generator/kernel records as well as PID 1.
