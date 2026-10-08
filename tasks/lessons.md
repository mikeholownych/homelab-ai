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
