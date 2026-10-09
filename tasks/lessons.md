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
