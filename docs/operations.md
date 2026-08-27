# Day-2 Operations and Administration Runbook

## Fleet Scope

Every procedure below targets `ai-p620-01` by example; each applies identically
to the Precision 5820 node `ai-5820-01` (same roles, playbooks, and pins), or to
the whole production group by omitting `--limit` or using `--limit 'ai-*'`. The
host-specific deltas live in host variables (`hardware_profile`, benchmarking
PSU/TDP budgets, storage mount points).

## Common Operator Procedures

### 1. Host Bootstrap
Bootstrap a freshly installed Ubuntu 24.04 node:
```bash
ansible-playbook playbooks/bootstrap.yml --limit ai-p620-01 --ask-become-pass --tags bootstrap,vault
```

### 2. Baseline Convergence
Apply baseline OS hardening, user management, and security policies:
```bash
ansible-playbook playbooks/baseline.yml --limit ai-p620-01
```

### 3. Full Authoritative Convergence
Run full end-to-end site convergence:
```bash
ansible-playbook playbooks/site.yml --limit ai-p620-01
```

### 4. Drift Assessment
Check for host configuration drift in check mode:
```bash
ansible-playbook playbooks/drift-check.yml --limit ai-p620-01 --check
```

### 5. Independent State Validation
Run independent validation probes and produce structured evidence:
```bash
ansible-playbook playbooks/validate.yml --limit ai-p620-01
```

### 6. Performance Benchmarking
Execute configurable benchmark profiles:
```bash
ansible-playbook playbooks/benchmark.yml --limit ai-p620-01 -e "benchmark_profile=small"
ansible-playbook playbooks/benchmark.yml --limit ai-p620-01 -e "benchmark_profile=large_70b"
```

### 7. Patching
Assess or apply routine security patches:
```bash
# Assessment
ansible-playbook playbooks/patch.yml --limit ai-p620-01

# Application with reboot if required
ansible-playbook playbooks/patch.yml --limit ai-p620-01 -e "patch_apply=true"
```

### 8. Component Upgrade & Rollback
Upgrade a runtime component or roll back to previous known good:
```bash
# Upgrade
ansible-playbook playbooks/upgrade.yml --limit ai-p620-01 -e "upgrade_component=vllm upgrade_version=0.7.3"

# Rollback
ansible-playbook playbooks/upgrade.yml --limit ai-p620-01 -e "upgrade_component=vllm upgrade_mode=rollback"
```

### 9. Git SHA in evidence
Validation and benchmark evidence records the deployed Git SHA. Runs launched through
`scripts/run-ansible-snapshot` receive `git_commit_sha` automatically from the captured
repository state. For direct `ansible-playbook` invocations, pass it explicitly so
evidence stays attributable:
```bash
-e "git_commit_sha=$(git rev-parse HEAD)"
```

### 10. Failure Visibility
Timer failures alert through `aihost-alert@%n`: alerts always append to
`/var/log/local-ai/alerts/alerts.log`; configure `/etc/local-ai/alert.env`
(out-of-band, not committed) with `AIHOST_ALERT_COMMAND=/path/to/hook` to
forward alerts elsewhere. The command receives `<unit> <timestamp>` as argv;
content is never shell-interpolated.

### 11. Evidence Durability
Mirror the evidence tree off-host behind `monitoring_evidence_sync_enabled`
plus an rsync destination; runs daily via `aihost-evidence-sync.timer`. The
mirror is append-only (`rsync -a`, no `--delete`) so the source of record is
never trimmed by a sync job.

### 12. Controlled Reboot
For kernel experiments or post-patch reboots:
```bash
scripts/run-ansible-snapshot ... --playbook reboot-verify.yml ...
```
The playbook verifies a pinned kernel image exists before rebooting, asserts
the running kernel after return, confirms GPU enumeration, then imports
`validate.yml`.
