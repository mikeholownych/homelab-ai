# Lessons

## Don't infer where an OOM happened from missing guest logs
- 2026-10-05: Vault VM (109) crashed. Guest journal simply stopped (no OOM lines), so I
  guessed the hypervisor. Wrong: the guest itself OOM'd and was too wedged to log.
- Rule: when a guest log ends abruptly, check sysstat (`sar -r -f /var/log/sysstat/saDD`) for
  the guest's *effective* RAM (free+used+buffers+cached) before blaming the host. Ballooned
  guests report a shrunken MemTotal; the VM config size is not what the guest had.
- Rule: believe the operator's direct observation (console OOM spam) over my inference.

## Sealed phase baselines: verify the evidence manifests before committing phase edits
- 2026-10-08: I committed Codex's tunnel→TLS edits to phase1/phase4 files (f31218c), then made a hash-determinism fix
  in phases 4-7. Each `phaseN/evidence/manifest.sha256` checksums that phase's own sources; both changes broke seals
  that were all clean at 0287aed. Found only because phase8's G01 gate re-verifies phase7's manifest.
- Rule: before touching anything under `phase*/`, check whether a manifest lists the file; if so the file is sealed
  history. Fix the problem outside the seal (root conftest gating, test-runner environment), never by editing it.
- Rule: after any phase change, verify every manifest (all must match), not just the tests that happen to run.

## pgrep -f matches its own shell
- 2026-10-08 (second time this workstream): `until ! pgrep -f adhoc_server.py` waited forever because the wrapping
  `bash -c` command line contains the pattern. Use `pgrep -f "[a]dhoc_server"` (the bracket class never matches its
  own literal text) or track the PID directly.

## pkill/pgrep -f patterns match the invoking shell too
- `pkill -f "[q]ualify.sh"` in a command line that ALSO contains `qualify.sh` (e.g. a relaunch later in the same
  command) kills the tool's own shell: the bracket trick only protects the pattern's own text, not other text on the line.
- Rule: never combine `pkill -f` with any other mention of the target in the same shell command. Kill by PID
  (`ps -eo pid,args | grep -E '[q]ualify'` → review → `kill <pid>`), and relaunch in a separate command.

## `ps` output is filtered by the rtk hook: use `rtk proxy ps` for process checks
- `ps -eo ... | grep` through the rtk rewrite hid live processes; a run looked dead, was relaunched twice, and three
  qualification runs overlapped (shared single slot, same result file) and had to be discarded.
- Rule: liveness checks before any relaunch use `rtk proxy ps` (or `pgrep -a` with a bracketed pattern) and the
  relaunch is refused if anything matches. Long runs are started with `setsid -f` so they are not tied to a tool shell.

## Check where a dependency runs before judging its health
- I reported "Vault is inactive" from `systemctl is-active vault` on the inference appliance; Vault runs on a separate
  host, so a local unit says nothing about Vault access (operator correction, 2026-10-09).
- Rule: for any external dependency, first establish where it runs and how this host reaches it (inventory address,
  client config, credentials), then test that path. A missing local service is evidence only for local services.


## 2026-11-05 — never signal a service from a handler that can flush with its restart (CAIS deploy rollback)
- Pattern: a `notify:` handler sent SIGHUP; `meta: flush_handlers` ran it ~1 s after the release restart, before the
  new Python process installed its SIGHUP handler, and SIGHUP's default action killed it. Unit tests could not see it.
- Rule: signals to a long-running service go in an explicit task placed **after** strict readiness verification, never
  in a handler. Pin the ordering with a role-structure test.
- Rule: verify which engine/config production actually runs from host_vars, not role defaults (Phase 0 said `sync`;
  production is `asgi`).
- Rule: evaluation runs through the gateway must bypass the response cache and survive client quotas, or "repeats"
  are cache hits and quota refusals get scored as model failures.

- Rule: before re-pinning the reconcile snapshot to a merge commit, fast-forward local `main`: the snapshot role's git
  checkout fetches only local branches/tags, so an `origin/main`-only commit fails with "reference is not a tree".

## 2026-11-16 — a bisect over source commits must hold the build environment fixed (SYCL 32K regression)
- Pattern: I bisected llama.cpp commits using each commit's own `.devops/intel.Dockerfile`, concluded the regression "enters
  at 18c5a95e", and was wrong: the Dockerfile bump (oneDNN, IGC, NEO, IGDGMM, Level Zero; d5bbcd1f3) rode along with the source.
  Reverting the suspect source change did nothing (874 vs 872), which exposed it.
- Rule: before attributing a perf change to source, list every input that changes between the two builds (toolchain, runtime
  libraries, base image, env defaults) and vary one at a time; verify by reverting the suspect and checking the number moves.
- Rule: packaged runtime pairs (IGC/NEO) can be hard-coupled by Debian dependencies; check `dpkg` constraints before planning a
  split bisect, and keep a failed-build log as evidence rather than retrying blindly.

## 2026-11-16 — a long outage harness must survive its launcher and be watched for liveness, not only for its done-marker
- Pattern: a multi-hour engx outage was started with `nohup ... &` from the tool shell; the process vanished without running its EXIT trap, so
  worker 2 stayed down ~3 h until I noticed. My monitors waited only for a `RESTORED` line that never came and expired silently.
- Rule: launch outage harnesses with `setsid` (own session), and have the watcher also check that the harness PID is alive; if it is gone with no
  RESTORED, run `harness/restore_baseline.sh` immediately. Prefer shorter outages (one image per outage) over a multi-hour one.
