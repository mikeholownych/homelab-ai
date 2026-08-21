# Runtime and Component Upgrade Workflow

## Overview

Upgrades of high-risk components (Intel compute runtime, Level Zero, PyTorch XPU, vLLM XPU, llama.cpp SYCL, and Kernel/Firmware) are explicit desired-state changes versioned in Git.

## Lifecycle States

`policies/upgrades.yml` tracks three version pins for each component:
- `current`: The currently deployed, validated version.
- `candidate`: The proposed target version undergoing staging and validation.
- `previous_known_good`: The fallback version used for rollback in case of regression.

## Upgrade Procedure

1. **Update Candidate Pin in Git**:
   Update `policies/upgrades.yml` or host variables with the candidate version.

2. **Stage and Validate Candidate**:
   Execute the upgrade playbook:
   ```bash
   ansible-playbook playbooks/upgrade.yml --limit ai-p620-01 -e "upgrade_component=vllm upgrade_version=0.7.3"
   ```

3. **Run Validation and Benchmark Gates**:
   Ensure all validation checks and performance regression benchmarks pass:
   ```bash
   ansible-playbook playbooks/validate.yml --limit ai-p620-01
   ansible-playbook playbooks/benchmark.yml --limit ai-p620-01 -e "benchmark_profile=small"
   ```

4. **Promote Candidate**:
   Update `current` in `policies/upgrades.yml` and commit to Git.
