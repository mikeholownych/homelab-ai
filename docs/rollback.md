# Component Rollback Runbook

## Overview

If an upgrade, patch, or drift remediation causes functional or performance regression, execute rollback to the `previous_known_good` baseline.

## Automated Rollback Invocation

Run `playbooks/upgrade.yml` in rollback mode:
```bash
ansible-playbook playbooks/upgrade.yml --limit ai-p620-01 -e "upgrade_component=vllm upgrade_mode=rollback"
```

## Manual Rollback Steps

1. **Revert Git Commit**:
   Revert the commit that updated the component version pin.
   ```bash
   git revert <commit-sha>
   git push origin main
   ```

2. **Converge Host**:
   Apply desired state to reconcile host to previous configuration:
   ```bash
   ansible-playbook playbooks/site.yml --limit ai-p620-01
   ```

3. **Validate**:
   ```bash
   ansible-playbook playbooks/validate.yml --limit ai-p620-01
   ```
