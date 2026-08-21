# ITSM Change Integration Flow

## Overview

The `itsm_hooks` role provides authorization boundaries for change ticket integration without evaluating free-form shell commands.

## Intended Lifecycle Flow

```text
Change / Request Ticket
  -> Validate ticket fields & risk classification
  -> Verify approvals
  -> Verify maintenance window (start/end UTC)
  -> Verify target CI scope
  -> Verify requested action is in permitted allowlist (PATCH, UPGRADE, ROLLBACK, VALIDATE, BENCHMARK, RECONCILE)
  -> Permit locked Ansible execution
  -> Execute convergence
  -> Run independent validation
  -> Publish evidence & update CMDB
  -> Update / close change ticket
```

## Security Guardrails

- No free-form ticket text is ever passed to shell or command execution.
- Action strings are strictly matched against an explicit allowlist.
