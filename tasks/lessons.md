# Lessons

## Don't infer where an OOM happened from missing guest logs
- 2026-10-05: Vault VM (109) crashed. Guest journal simply stopped (no OOM lines), so I
  guessed the hypervisor. Wrong: the guest itself OOM'd and was too wedged to log.
- Rule: when a guest log ends abruptly, check sysstat (`sar -r -f /var/log/sysstat/saDD`) for
  the guest's *effective* RAM (free+used+buffers+cached) before blaming the host. Ballooned
  guests report a shrunken MemTotal; the VM config size is not what the guest had.
- Rule: believe the operator's direct observation (console OOM spam) over my inference.
