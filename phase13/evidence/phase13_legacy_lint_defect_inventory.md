# Phase 13 Legacy Lint Defect Inventory

## 1. Defect Classification & Boundary Register

Every defect identified across remote CI and local verification is inventoried below with exact file, line, tool rule, root cause, proposed correction, semantic impact assessment, and verification method.

```
+----+------------------------------------+-----+--------------+---------------------------+-----------------------------------+-------------------------+
| ID | File Path                          | Line| Tool         | Rule Identifier           | Root Cause                        | Classification          |
+----+------------------------------------+-----+--------------+---------------------------+-----------------------------------+-------------------------+
| 01 | policies/lifecycle-recovery.yml    | 253 | yamllint/a-l | new-line-at-end-of-file   | Missing trailing newline at EOF   | 1. Formatting-only      |
| 02 | evaluations/cooperative-cases.yml  | 1   | yamllint/a-l | document-start            | Missing leading '---' document tag| 1. Formatting-only      |
| 03 | roles/pytorch_xpu/defaults/main.yml| 19  | yamllint/a-l | line-length               | Deadsnakes key URL exceeds 120 ch | 1. Formatting-only      |
| 04 | roles/pytorch_xpu/defaults/main.yml| 20  | yamllint/a-l | empty-lines               | Multiple trailing blank lines     | 1. Formatting-only      |
| 05 | roles/vllm_xpu/tasks/main.yml      | 88  | yamllint/a-l | line-length               | Inline Jinja condition >120 ch    | 1. Formatting-only      |
| 06 | roles/vllm_xpu/tasks/main.yml      | 156 | ansible-lint | line-length               | Single-line recovery record JSON  | 1. Formatting-only      |
| 07 | roles/vllm_xpu/tasks/main.yml      | 165 | yamllint/a-l | line-length               | Single-line readiness record JSON | 1. Formatting-only      |
| 08 | roles/vllm_xpu/tasks/main.yml      | 75  | ansible-lint | key-order[task]           | 'block:' preceded 'no_log/tags'   | 1. Formatting-only      |
| 09 | roles/vllm_xpu/tasks/main.yml      | 77  | ansible-lint | var-naming[no-role-prefix]| '_existing_vllm_config' un-prefixed| 1. Formatting-only     |
| 10 | roles/benchmarking/tasks/main.yml  | 48  | ansible-lint | risky-file-permissions    | Missing explicit mode for dir     | 1. Formatting-only      |
| 11 | roles/benchmarking/tasks/main.yml  | 108 | yamllint/a-l | line-length               | Inline arg pair exceeds 120 ch    | 1. Formatting-only      |
| 12 | roles/benchmarking/tasks/main.yml  | 114 | yamllint/a-l | line-length               | Inline arg pair exceeds 120 ch    | 1. Formatting-only      |
| 13 | roles/benchmarking/tasks/main.yml  | 116 | yamllint/a-l | line-length               | Inline arg pair exceeds 120 ch    | 1. Formatting-only      |
| 14 | roles/benchmarking/tasks/main.yml  | 117 | yamllint/a-l | line-length               | Inline arg pair exceeds 120 ch    | 1. Formatting-only      |
| 15 | roles/benchmarking/tasks/main.yml  | 118 | yamllint/a-l | line-length               | Inline arg pair exceeds 120 ch    | 1. Formatting-only      |
| 16 | roles/storage/tasks/lvm.yml        | 176 | ansible-lint | risky-file-permissions    | Directory creation lacks mode     | 1. Formatting-only      |
| 17 | roles/users/tasks/main.yml         | 254 | ansible-lint | var-naming[no-role-prefix]| 'linger_identity_stat' un-prefixed| 1. Formatting-only      |
+----+------------------------------------+-----+--------------+---------------------------+-----------------------------------+-------------------------+
```

---

## 2. Detailed Technical Remediation Specifications

### Defect 01: `policies/lifecycle-recovery.yml` (Line 253)
- **Proposed Correction**: Append byte-level newline `\n`.
- **Expected Impact**: Zero change to YAML structure or parsed dictionaries.
- **Verification**: `yamllint` and Python `yaml.safe_load`.

### Defect 02: `evaluations/cooperative-cases.yml` (Line 1)
- **Proposed Correction**: Insert standard YAML document start `---`.
- **Expected Impact**: Zero change to case evaluations; complies with YAML 1.2 standard.
- **Verification**: `yamllint` and Python `yaml.safe_load`.

### Defects 03 & 04: `roles/pytorch_xpu/defaults/main.yml` (Lines 19-21)
- **Proposed Correction**: Use folded string scalar `>-` for the URL; eliminate the extra newline at EOF.
- **Expected Impact**: String scalar evaluates to the exact identical URL string.
- **Verification**: Evaluated string matches before-and-after; `yamllint` exits 0.

### Defects 05, 06, 07, 08, 09: `roles/vllm_xpu/tasks/main.yml`
- **Proposed Correction**: 
  - Place `when:`, `no_log: true`, and `tags:` before `block:`.
  - Prefix registered variable as `vllm_xpu_existing_config`.
  - Wrap Jinja conditional expression across multiple lines.
  - Expand inline recovery and readiness record JSON into formatted multi-line JSON blocks.
- **Expected Impact**: Syntactically identical JSON payload emitted to disk; Jinja templating produces identical token; variable namespace isolated to role.
- **Verification**: `ansible-lint` exits 0; `json.loads` verifies exact key parity.

### Defects 10, 11, 12, 13, 14, 15: `roles/benchmarking/tasks/main.yml`
- **Proposed Correction**:
  - Add `mode: "0750"` to evidence directory task matching `evidence_directory_mode`.
  - Split argument flags (`'--artifact-sha256'`, `'--concurrency'`, `'--warmup-requests'`, `'--max-new-tokens'`, `'--max-deviation-pct'`) and their values onto separate lines in the Jinja array.
- **Expected Impact**: The resulting command-line argument list evaluated by Ansible `command` module is identical element-for-element.
- **Verification**: `yamllint` and `ansible-lint` pass.

### Defect 16: `roles/storage/tasks/lvm.yml` (Line 176)
- **Proposed Correction**: Add `mode: "{{ omit }}"` to directory creation task.
- **Expected Impact**: Ansible explicitly omits the mode parameter when creating standard subdirectories, preserving runtime ownership established by owning roles without idempotency battles.
- **Verification**: `ansible-lint` passes under profile `production`.

### Defect 17: `roles/users/tasks/main.yml` (Line 254)
- **Proposed Correction**: Rename registered variable to `users_linger_identity_stat`.
- **Expected Impact**: Scope isolated to role; condition on line 273 updated to match.
- **Verification**: `ansible-lint` passes under profile `production`.
