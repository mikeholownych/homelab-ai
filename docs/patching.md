# Host and Platform Patching Guide

## Overview

Patching on the AI workstation fleet is strictly Ansible-managed. Indiscriminate package upgrades (`apt upgrade` or `dist-upgrade`) are prohibited to prevent silent breakage of the GPU compute and inference runtime stack.

## Component Classification

As defined in `policies/patching.yml`:

1. **Routine Components**:
   - `os_packages`: Standard system utilities (e.g. `curl`, `jq`, `rsync`, `sudo`, `systemd`).
   - `security_updates`: Routine security patches (e.g. `openssl`, `libssl3`, `tzdata`).
   - Managed automatically via scheduled patch runs when permitted.

2. **High-Risk Components** (Require explicit Git version change):
   - Linux Kernel (`linux-image*`, `linux-headers*`)
   - Intel GPU Driver / Compute Runtime (`intel-compute-runtime*`, `intel-opencl-icd*`)
   - Level Zero Loader and Runtime (`libze-intel-gpu*`, `level-zero*`)
   - PyTorch XPU
   - vLLM XPU
   - llama.cpp SYCL
   - System Firmware / BIOS

## Patch Execution

### 1. Assessment (Dry Run)
Assess available updates without applying changes:
```bash
ansible-playbook playbooks/patch.yml --limit ai-p620-01
```

### 2. Application
Apply permitted routine patches and handle reboot if required:
```bash
ansible-playbook playbooks/patch.yml --limit ai-p620-01 --extra-vars "patch_apply=true"
```

## Post-Patch Validation

Following patch application and reboot, `playbooks/patch.yml` automatically triggers independent hardware and runtime validation. Evidence is recorded in `/var/lib/aihost/evidence/`.
