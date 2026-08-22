# Day-2 Operations and Administration Runbook

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
