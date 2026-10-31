# Reconciliation manager reloads

The controller user timer on mike-dev runs a pinned snapshot, not the source checkout at
`/home/mike/Projects/aihost`. Source changes require review and an explicit snapshot deployment
before they affect scheduled runs.

The retained run `2026-10-30T030426Z` used commit
`465e475d936b1d0593c1dbd560e9b4ee4ffa0e07`. Its recorded files passed SHA256SUMS verification.
It reported 141 ok, one changed (the completion stamp), and no failures, while the target journal
recorded nine manager reloads. Explicit unconditional daemon_reload options in the executed task
sequence account for these requests. This is historical run evidence, not validation of this fix.

Unit template and removal results now gate manager reloads. Worker templates and retired units
are loaded together before the existing drain/start sequence. Per-worker start/stop actions do
not repeat that reload. Policy, gateway and console handlers still restart their services when
notified, but only reload manager configuration when their unit template changed. Monitoring
service/timer changes are loaded before managing the corresponding timer.

Acceptance after an authorized deployment:

1. Record the deployed snapshot SHA and the scheduled run evidence directory.
2. An unchanged configuration run must issue zero manager reloads attributable to the run.
   The timestamped completion stamp can still report changed; task recap alone is insufficient.
3. A controlled unit addition/change/removal must reload manager configuration before dependent
   service operations. Worker drain and health checks must remain effective.
4. Check service health, timer states, and rollback behavior. Do not treat source tests or syntax
   checks as live appliance acceptance.

Do not disable the reconciliation timer or XFS scrub to suppress warnings. The separate
October 31 03:22:43-44 UTC burst accompanied OpenIPMI disablement in session 864 and is not
part of the hourly nine-reload sequence.
