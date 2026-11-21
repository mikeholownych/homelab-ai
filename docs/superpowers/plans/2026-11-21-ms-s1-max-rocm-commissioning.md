# MS-S1 Max ROCm Phase 1 Lab Commissioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commission lab host `ai-ms-s1-max-01` (10.0.8.6) with Ubuntu 26.04 baseline, Ansible-managed ROCm 7.2.0, Strix Halo + NPU hardware acceptance, and a 1 TiB `/var/lib/local-ai` volume — without enabling inference engines or joining the production pool.

**Architecture:** Parallel AMD stack beside the existing Intel path: lab inventory only, new `ms_s1_max_strix_halo` hardware profile, profile-selected classifier backend (AMD vs Level Zero), new `roles/rocm/`, and commission/site wiring that never forces OMIX onto this host. Engines remain deferred.

**Tech Stack:** Ansible, pytest, yamllint/ansible-lint, Ubuntu 26.04, LVM2/XFS, ROCm 7.2.0 (Noble vendor suites), `rocminfo` / `rocm-smi`, `amdgpu` / `amdxdna`.

**Spec:** `docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-commissioning-design.md` (commit `6db92c0`).

**Plan-time storage decision:** `storage_lvm.size: 1024g`, `reserve_gib: 100` (lab bake-off buffer; VG has ~1.72 TiB free).

---

## File Map

| Path | Responsibility |
| --- | --- |
| `inventory/lab/hosts.yml` | Register real SSH host `ai-ms-s1-max-01` |
| `inventory/lab/host_vars/ai-ms-s1-max-01.yml` | Lab host contract: ROCm on, inference off, LVM 1024g |
| `profiles/hardware/ms_s1_max_strix_halo.yml` | Strix Halo + NPU hardware profile |
| `roles/hardware_validation/files/classify_hardware.py` | Profile-selected AMD vs Intel classification |
| `roles/hardware_inventory/files/collect_hardware.py` | Collect ROCm/NPU observations when present |
| `tests/fixtures/hardware/ms_s1_max_*.json` | AMD PASS / missing-NPU FAIL fixtures |
| `tests/test_hardware_validation.py` | AMD classifier tests (Intel fixtures unchanged) |
| `tests/test_rocm_contract.py` | ROCm role pin/repo/gate contracts |
| `roles/rocm/{defaults,tasks,templates}/` | Managed ROCm 7.2.0 install + acceptance |
| `playbooks/site.yml` | Include `rocm` when enabled; keep Intel path intact |
| `playbooks/commission.yml` | ROCm phase; never force OMIX when `rocm_install_enabled` |
| `docs/commissioning.md` | MS-S1 Max Phase 1 runbook section |

---

### Task 1: Lab inventory registration

**Files:**
- Modify: `inventory/lab/hosts.yml`
- Create: `inventory/lab/host_vars/ai-ms-s1-max-01.yml`
- Create: `tests/test_ms_s1_max_inventory_contract.py`

- [ ] **Step 1: Write the failing inventory contract test**

```python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def test_lab_hosts_registers_ms_s1_max():
    hosts = load("inventory/lab/hosts.yml")
    assert "ai-ms-s1-max-01" in hosts["all"]["children"]["lab"]["hosts"]
    assert "ai-ms-s1-max-01" in hosts["all"]["children"]["gpu"]["hosts"]
    assert "ai-ms-s1-max-01" not in hosts["all"]["children"].get("inference", {}).get("hosts", {})


def test_ms_s1_max_host_vars_phase1_contract():
    hv = load("inventory/lab/host_vars/ai-ms-s1-max-01.yml")
    assert hv["ansible_host"] == "10.0.8.6"
    assert hv["node_metadata"]["hostname"] == "ai-ms-s1-max-01"
    assert hv["node_metadata"]["hardware_profile"] == "ms_s1_max_strix_halo"
    assert hv["node_roles"]["inference"] is False
    assert hv["node_roles"]["gpu"] is True
    assert hv["capabilities"]["inference"] is False
    assert hv["capabilities"]["gpu"] is True
    assert hv["rocm_install_enabled"] is True
    assert hv["intel_gpu_install_enabled"] is False
    assert hv["intel_gpu_physical_validation_enabled"] is False
    assert hv["storage_lvm"]["enabled"] is True
    assert hv["storage_lvm"]["size"] == "1024g"
    assert hv["storage_lvm"]["reserve_gib"] == 100
    assert hv["storage_lvm"]["expected_pvs"] == ["/dev/nvme0n1p3"]
```

- [ ] **Step 2: Run test — expect RED**

Run: `.venv/bin/pytest tests/test_ms_s1_max_inventory_contract.py -q`

Expected: FAIL (missing host vars / inventory entries).

- [ ] **Step 3: Update lab inventory**

In `inventory/lab/hosts.yml`, add under `lab` and `gpu` (do **not** add to `inference` or `cluster`):

```yaml
        ai-ms-s1-max-01: {}
```

Keep `ai-5820-test-01` unchanged. Do not add `ai-ms-s1-max-01` under `all.children.ai_hosts.hosts` localhost-style entry; it is a real SSH target resolved via group membership like other non-local hosts. Ensure it appears only via group hosts lists (same pattern as production `ai-5820-01`).

If the lab inventory currently lists `ai-5820-test-01` both under `ai_hosts.hosts` (with connection overrides) and groups, add `ai-ms-s1-max-01` **only** to `lab` and `gpu` group host maps — not to the localhost override block.

- [ ] **Step 4: Create host vars**

Create `inventory/lab/host_vars/ai-ms-s1-max-01.yml`:

```yaml
---
ansible_host: 10.0.8.6
ansible_user: mike
ansible_become: true

platform_release: "26.04"
platform_codename: resolute

node_metadata:
  environment: lab
  hostname: ai-ms-s1-max-01
  hardware_profile: ms_s1_max_strix_halo
  os_tuning_profile: baseline

node_roles:
  inference: false
  gpu: true

capabilities:
  gpu: true
  inference: false
  benchmarking: false
  monitoring: true
  cluster_eligible: false

features:
  monitoring: false
  scheduled_reconciliation: false
  os_tuning: true
  observability: false
  model_registry: false
  clustering: false
  cmdb_export: false
  itsm_integration: false
  ray_enabled: false
  distributed_vllm_enabled: false

rocm_install_enabled: true
intel_gpu_install_enabled: false
intel_gpu_physical_validation_enabled: false

storage_lvm:
  enabled: true
  vg: ubuntu-vg
  lv: local-ai-lv
  size: 1024g
  fstype: xfs
  mount_path: /var/lib/local-ai
  reserve_gib: 100
  expected_pvs:
    - /dev/nvme0n1p3
```

- [ ] **Step 5: Run test — expect GREEN**

Run: `.venv/bin/pytest tests/test_ms_s1_max_inventory_contract.py -q`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add inventory/lab/hosts.yml inventory/lab/host_vars/ai-ms-s1-max-01.yml tests/test_ms_s1_max_inventory_contract.py
git commit -m "feat(lab): register ai-ms-s1-max-01 for ROCm Phase 1 commissioning"
```

---

### Task 2: Hardware profile

**Files:**
- Create: `profiles/hardware/ms_s1_max_strix_halo.yml`
- Modify: `tests/test_ms_s1_max_inventory_contract.py` (or new `tests/test_ms_s1_max_profile_contract.py`)

- [ ] **Step 1: Write failing profile contract test**

```python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_ms_s1_max_hardware_profile_shape():
    profile = yaml.safe_load(
        (ROOT / "profiles/hardware/ms_s1_max_strix_halo.yml").read_text()
    )
    assert profile["profile_name"] == "ms_s1_max_strix_halo"
    assert profile["compute_evidence_backend"] == "rocm"
    assert profile["gpu"]["count_expected"] == 1
    assert profile["gpu"]["approved_pci_devices"][0]["vendor_id"] == "1002"
    assert profile["gpu"]["approved_pci_devices"][0]["device_id"] in ("1586", "0x1586")
    assert profile["gpu"]["expected_models"][0]["memory_gib"]["approximate"] == 61
    assert profile["npu"]["required"] is True
    assert profile["npu"]["hsa_name"] == "aie2p"
    assert profile["firmware"]["resizable_bar"]["required"] is False
    assert profile["firmware"]["above_4g_decoding"]["required"] is False
```

- [ ] **Step 2: Run — expect RED**

Run: `.venv/bin/pytest tests/test_ms_s1_max_profile_contract.py -q`

- [ ] **Step 3: Author the profile**

Create `profiles/hardware/ms_s1_max_strix_halo.yml`:

```yaml
---
schema_version: 1.0.0
profile_name: ms_s1_max_strix_halo
compute_evidence_backend: rocm

platform:
  manufacturer: Micro Computer (HK) Tech Limited
  product_family: MS-S1 MAX
  machine_type_model: "MS-S1 MAX"
  product_name_patterns:
    - MS-S1 MAX
    - MS-S1

cpu:
  vendor: AMD
  model_patterns:
    - RYZEN AI MAX+ 395
    - Ryzen AI Max+ 395
    - AMD RYZEN AI MAX+ 395
  sockets_expected: 1

gpu:
  count_expected: 1
  architecture: Strix Halo
  approved_pci_devices:
    - vendor_id: "1002"
      device_id: "1586"
      model: Radeon 8060S
      source: Live rocminfo gfx1151 / PCI 1002:1586 on ai-ms-s1-max-01
      source_url: https://www.amd.com/en/products/processors/laptop/ryzen-ai-max-series.html
  expected_models:
    - vendor: AMD
      model: Radeon 8060S
      memory_gib:
        approximate: 61
        tolerance_gib: 4
        source: rocminfo_coarse_pool

pcie:
  host_link:
    max_generation: 4
    expected_negotiated_generation: 0
  width_expectations:
    desired_when_slot_supports: x16
    allow_slot_limited_width: true
  material_degradation:
    default_severity: informational
    minimum_negotiated_to_slot_ratio: 0.0

firmware:
  above_4g_decoding:
    required: false
    missing_severity: informational
    undiscoverable_status: not_applicable
  resizable_bar:
    required: false
    missing_severity: informational

memory:
  installed_gib:
    expected: 122
    tolerance_gib: 4
    out_of_tolerance_severity: warning
    classification: initial_commissioning

npu:
  required: true
  hsa_name: aie2p
  marketing_name: RyzenAI-npu5
  kernel_module: amdxdna
  device_node: /dev/accel/accel0

discovery_fields:
  record:
    - dimm_topology
    - nvme_devices
    - nic_inventory
    - bios_version
    - firmware_inventory
  asset_identifiers:
    - serial_number

severity_rules:
  information:
    - dimm_topology_observed
    - firmware_inventory_observed
  warning:
    - memory_capacity
    - unexpected_gpu_devices
  blocking:
    - gpu_count
    - gpu_model_match
    - rocm_gpu_agent
    - rocm_npu_agent
    - npu_device_node
```

- [ ] **Step 4: Run — expect GREEN; commit**

```bash
git add profiles/hardware/ms_s1_max_strix_halo.yml tests/test_ms_s1_max_profile_contract.py
git commit -m "feat(hardware): add MS-S1 Max Strix Halo ROCm profile"
```

---

### Task 3: Classifier AMD backend + fixtures

**Files:**
- Modify: `roles/hardware_validation/files/classify_hardware.py`
- Create: `tests/fixtures/hardware/ms_s1_max_healthy.json`
- Create: `tests/fixtures/hardware/ms_s1_max_npu_missing.json`
- Modify: `tests/test_hardware_validation.py`

- [ ] **Step 1: Write failing AMD classification tests**

Append to `tests/test_hardware_validation.py`:

```python
def test_ms_s1_max_healthy_passes_rocm_backend():
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/ms_s1_max_strix_halo.yml").read_text())
    observed = json.loads((ROOT / "tests/fixtures/hardware/ms_s1_max_healthy.json").read_text())
    result = classifier.classify(profile, observed)
    assert result["status"] == "pass"
    assert result["physical_acceptance"] is False  # simulated
    assert not any(
        c["rule"] in ("level_zero_detected", "dual_bdf_correlation") and c["status"] == "fail"
        for c in result["checks"]
    )


def test_ms_s1_max_missing_npu_blocks():
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/ms_s1_max_strix_halo.yml").read_text())
    observed = json.loads((ROOT / "tests/fixtures/hardware/ms_s1_max_npu_missing.json").read_text())
    result = classifier.classify(profile, observed)
    assert result["status"] == "blocking"
    assert any(
        c["rule"] in ("rocm_npu_agent", "npu_device_node") and c["severity"] == "blocking"
        for c in result["checks"]
    )


def test_d5820_healthy_still_uses_level_zero_path():
    classifier = load_classifier()
    profile = yaml.safe_load((ROOT / "profiles/hardware/d5820_dual_b65.yml").read_text())
    observed = json.loads((ROOT / "tests/fixtures/hardware/d5820_healthy.json").read_text())
    result = classifier.classify(profile, observed)
    assert result["status"] == "pass"
    assert any(c["rule"] == "level_zero_detected" for c in result["checks"])
```

- [ ] **Step 2: Run — expect RED** (missing fixtures / backend)

Run: `.venv/bin/pytest tests/test_hardware_validation.py -k ms_s1_max -q`

- [ ] **Step 3: Add fixtures**

`tests/fixtures/hardware/ms_s1_max_healthy.json`:

```json
{
  "simulated": true,
  "dmi": {
    "manufacturer": "Micro Computer (HK) Tech Limited",
    "product_name": "MS-S1 MAX",
    "serial_number": "SIMULATED"
  },
  "cpu": {
    "model": "AMD RYZEN AI MAX+ 395 w/ Radeon 8060S",
    "sockets": 1
  },
  "memory": {"total_gib": 122},
  "gpus": [
    {
      "bdf": "0000:bd:00.0",
      "vendor_id": "1002",
      "device_id": "1586",
      "kernel_driver": "amdgpu",
      "drm_card": "/dev/dri/card1",
      "render_node": "/dev/dri/renderD128"
    }
  ],
  "pci": [
    {
      "bdf": "0000:bd:00.0",
      "vendor_id": "1002",
      "device_id": "1586",
      "slot_width": 16,
      "current_width": 16,
      "current_generation": 4,
      "rebar_enabled": null
    }
  ],
  "rocm": {
    "agents": [
      {"name": "AMD RYZEN AI MAX+ 395 w/ Radeon 8060S", "device_type": "CPU"},
      {"name": "gfx1151", "device_type": "GPU", "memory_gib": 61.3},
      {"name": "aie2p", "device_type": "DSP", "marketing_name": "RyzenAI-npu5"}
    ]
  },
  "npu": {
    "kernel_module_loaded": true,
    "device_node": "/dev/accel/accel0",
    "device_node_exists": true
  },
  "firmware": {"above_4g_decoding": {"value": null}},
  "level_zero_devices": []
}
```

`tests/fixtures/hardware/ms_s1_max_npu_missing.json`: copy healthy fixture but set NPU agent absent and `device_node_exists: false`, `kernel_module_loaded: false`, and remove the `aie2p` agent from `rocm.agents`.

- [ ] **Step 4: Implement profile-selected backend in classifier**

At the start of `classify()`, after basic machine/cpu/gpu_count/gpu_model_match checks that are shared:

```python
backend = profile.get("compute_evidence_backend", "level_zero")
if backend == "rocm":
    return _classify_rocm(profile, observed, checks)
# existing Level Zero / dual-B65 path continues unchanged
```

Implement `_classify_rocm` to:

1. Skip Level Zero / dual_bdf_correlation / resizable_bar blocking checks.
2. Assert exactly one approved GPU with `amdgpu` driver and DRM render node.
3. Read `observed["rocm"]["agents"]`; require a GPU agent named `gfx1151` (or matching profile) with `memory_gib` within tolerance of 61±4.
4. Require NPU: agent `aie2p`, `observed["npu"]["kernel_module_loaded"] is True`, `device_node_exists` for `/dev/accel/accel0`.
5. Treat firmware Above-4G / ReBAR as informational / not_applicable when `required: false`.
6. Set PCIe link health informational when `minimum_negotiated_to_slot_ratio` is 0.0.
7. Preserve shared machine/cpu/gpu_count/gpu_model_match/memory_capacity/unexpected_gpu checks already appended.

Also update `main()` evidence document rule sets so AMD evidence does not require `level_zero_detected` / `dual_bdf_correlation`.

- [ ] **Step 5: Run full hardware validation suite — expect GREEN**

Run: `.venv/bin/pytest tests/test_hardware_validation.py -q`

Expected: all existing Intel fixtures still pass; new AMD tests pass.

- [ ] **Step 6: Commit**

```bash
git add roles/hardware_validation/files/classify_hardware.py \
  tests/fixtures/hardware/ms_s1_max_healthy.json \
  tests/fixtures/hardware/ms_s1_max_npu_missing.json \
  tests/test_hardware_validation.py
git commit -m "feat(hardware): add ROCm evidence backend for Strix Halo profile"
```

---

### Task 4: Collect ROCm/NPU observations

**Files:**
- Modify: `roles/hardware_inventory/files/collect_hardware.py`
- Add unit coverage in `tests/test_hardware_validation.py` or `tests/test_hardware_inventory_rocm.py`

- [ ] **Step 1: Write a failing collector test** that, given mocked `rocminfo` / `/dev/accel` / `lsmod` outputs matching the live host, asserts the collected dict includes `rocm.agents` with `gfx1151` and `aie2p`, and `npu.device_node_exists is True`.

- [ ] **Step 2: Implement collection helpers** in `collect_hardware.py`:
  - Parse `rocminfo` for Agent blocks (Name, Device Type, Marketing Name, coarse pool Size → GiB).
  - Detect `amdxdna` via `/proc/modules` or `lsmod`.
  - Stat `/dev/accel/accel0`.
  - Leave Intel Level Zero collection unchanged when ROCm tools are absent.

- [ ] **Step 3: Tests GREEN; commit**

```bash
git add roles/hardware_inventory/files/collect_hardware.py tests/test_hardware_inventory_rocm.py
git commit -m "feat(hardware): collect rocminfo and NPU evidence for AMD hosts"
```

---

### Task 5: ROCm role contracts + defaults

**Files:**
- Create: `roles/rocm/defaults/main.yml`
- Create: `roles/rocm/tasks/main.yml` (stub)
- Create: `tests/test_rocm_contract.py`

- [ ] **Step 1: Write failing contract tests**

```python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def test_rocm_defaults_are_fail_closed_and_pinned():
    d = load("roles/rocm/defaults/main.yml")
    assert d["rocm_install_enabled"] is False
    assert d["rocm_release"] == "7.2.0"
    assert d["rocm_apt_suite"] == "noble"
    assert d["rocm_signing_key_sha256"] == (
        "3e660bdc559b34781b5498e79b9c117394b46ce55592812db0b84d65986b4df2"
    )
    assert d["rocm_signing_key_fingerprint"] == "CA8BBB4727A47B4D09B4EE8969386B48A1A693C5C"
    assert d["rocm_packages"]["rocm-core"] == "7.2.0.70200-43~24.04"
    assert d["rocm_packages"]["rocminfo"] == "1.0.0.70200-43~24.04"
    assert d["rocm_expected_gpu_agent"] == "gfx1151"
    assert d["rocm_expected_npu_agent"] == "aie2p"
    assert "latest" not in d["rocm_repository_urls"]["rocm"]


def test_site_includes_rocm_role_gated():
    site = (ROOT / "playbooks/site.yml").read_text()
    assert "name: rocm" in site
    assert "rocm_install_enabled" in site


def test_commission_does_not_force_omix_when_rocm_enabled():
    text = (ROOT / "playbooks/commission.yml").read_text()
    assert "rocm_install_enabled" in text
    assert "Phase 5" in text
```

- [ ] **Step 2: Run — expect RED**

- [ ] **Step 3: Create defaults**

`roles/rocm/defaults/main.yml`:

```yaml
---
rocm_install_enabled: false
rocm_release: "7.2.0"
rocm_apt_suite: noble
rocm_keyring_path: /etc/apt/keyrings/rocm.gpg
rocm_signing_key_url: https://repo.radeon.com/rocm/rocm.gpg.key
rocm_signing_key_sha256: 3e660bdc559b34781b5498e79b9c117394b46ce55592812db0b84d65986b4df2
rocm_signing_key_fingerprint: CA8BBB4727A47B4D09B4EE8969386B48A1A693C5C
rocm_repository_urls:
  rocm: https://repo.radeon.com/rocm/apt/7.2
  graphics: https://repo.radeon.com/graphics/7.2/ubuntu
  amdgpu: https://repo.radeon.com/amdgpu/30.30/ubuntu
rocm_sources_path: /etc/apt/sources.list.d/rocm.list
rocm_graphics_sources_path: /etc/apt/sources.list.d/amdgpu.list
# Keep proprietary list unmanaged unless required; prefer the three pinned lines.
rocm_packages:
  rocm: "7.2.0.70200-43~24.04"
  rocm-core: "7.2.0.70200-43~24.04"
  rocm-hip: "7.2.0.70200-43~24.04"
  hip-runtime-amd: "7.2.26015.70200-43~24.04"
  hsa-rocr: "1.18.0.70200-43~24.04"
  rocminfo: "1.0.0.70200-43~24.04"
  rocm-smi-lib: "7.8.0.70200-43~24.04"
  amdgpu-core: "1:7.2.70200-2278374.24.04"
rocm_target_pci_ids:
  - "1002:1586"
rocm_expected_gpu_agent: gfx1151
rocm_expected_npu_agent: aie2p
rocm_npu_device_node: /dev/accel/accel0
rocm_npu_module: amdxdna
rocm_service_accounts:
  - "{{ host_runtime_account.name }}"
rocm_operator_accounts:
  - mike
rocm_evidence_path: /var/lib/local-ai/evidence/rocm-runtime.json
rocm_minimum_ubuntu: "26.04"
rocm_minimum_kernel: "7.0"
```

Stub `roles/rocm/tasks/main.yml`:

```yaml
---
- name: ROCm role no-op unless explicitly enabled
  ansible.builtin.debug:
    msg: "rocm_install_enabled is false; skipping"
  when: not (rocm_install_enabled | default(false) | bool)
```

Leave site/commission wiring for Task 7 so this task’s site assertions stay RED until then — **or** split: only assert defaults in this task; move site/commission assertions to Task 7. Prefer splitting: delete `test_site_*` / `test_commission_*` from this file until Task 7.

- [ ] **Step 4: Defaults tests GREEN; commit**

```bash
git add roles/rocm/defaults/main.yml roles/rocm/tasks/main.yml tests/test_rocm_contract.py
git commit -m "feat(rocm): add fail-closed ROCm 7.2.0 role defaults"
```

---

### Task 6: Implement ROCm role tasks

**Files:**
- Create: `roles/rocm/tasks/preflight.yml`
- Create: `roles/rocm/tasks/repos.yml`
- Create: `roles/rocm/tasks/packages.yml`
- Create: `roles/rocm/tasks/access.yml`
- Create: `roles/rocm/tasks/validate.yml`
- Create: `roles/rocm/templates/rocm.list.j2` (and amdgpu list template if split)
- Modify: `roles/rocm/tasks/main.yml`
- Extend: `tests/test_rocm_contract.py` for task wiring strings

- [ ] **Step 1: Extend contract tests** to assert `main.yml` includes preflight/repos/packages/access/validate when enabled, and that templates pin `noble` + `/7.2` paths (no `latest`).

- [ ] **Step 2: Implement task graph**

`main.yml`:

```yaml
---
- name: Include ROCm preflight
  ansible.builtin.include_tasks: preflight.yml
  when: rocm_install_enabled | bool

- name: Include ROCm repository management
  ansible.builtin.include_tasks: repos.yml
  when: rocm_install_enabled | bool

- name: Include ROCm package pins
  ansible.builtin.include_tasks: packages.yml
  when: rocm_install_enabled | bool

- name: Include ROCm device access
  ansible.builtin.include_tasks: access.yml
  when: rocm_install_enabled | bool

- name: Include ROCm compute validation
  ansible.builtin.include_tasks: validate.yml
  when:
    - rocm_install_enabled | bool
    - not ansible_check_mode
```

**preflight.yml** — assert Ubuntu ≥ 26.04, kernel ≥ 7.0, PCI `1002:1586` present (`lspci -nn`), reject sources containing `rocm/apt/latest` or unpinned graphics channels when install enabled.

**repos.yml** — mirror `intel_gpu` omix key install pattern using `rocm_signing_key_*`; write pinned list files from templates:

```
deb [arch=amd64 signed-by={{ rocm_keyring_path }}] {{ rocm_repository_urls.rocm }} {{ rocm_apt_suite }} main
deb [arch=amd64,i386 signed-by={{ rocm_keyring_path }}] {{ rocm_repository_urls.graphics }} {{ rocm_apt_suite }} main
deb [arch=amd64,i386 signed-by={{ rocm_keyring_path }}] {{ rocm_repository_urls.amdgpu }} {{ rocm_apt_suite }} main
```

**packages.yml** — `apt:` install each `package={{ version }}` from `rocm_packages`; then `package_facts` and assert installed versions match the pin map exactly.

**access.yml** — ensure groups `render`/`video`; add `rocm_operator_accounts` and `rocm_service_accounts` to both; assert `/dev/kfd` and render node exist.

**validate.yml** — run `rocminfo`, require stdout to contain `gfx1151` and `aie2p`; run `rocm-smi`; assert `amdxdna` loaded; assert `rocm_npu_device_node` exists; write `rocm_evidence_path` JSON with package versions, agents, PCI BDF, timestamp, `physical_acceptance: true` on success.

- [ ] **Step 3: Contract tests GREEN**

Run: `.venv/bin/pytest tests/test_rocm_contract.py -q`

- [ ] **Step 4: Commit**

```bash
git add roles/rocm tests/test_rocm_contract.py
git commit -m "feat(rocm): manage pinned ROCm 7.2.0 repos, packages, and NPU gates"
```

---

### Task 7: Wire site.yml and commission.yml

**Files:**
- Modify: `playbooks/site.yml`
- Modify: `playbooks/commission.yml`
- Modify: `tests/test_rocm_contract.py`
- Modify: `tests/test_gpu_stack_contract.py` only if assertions assume OMIX always runs for `capabilities.gpu`

- [ ] **Step 1: Add failing wiring tests** (site includes rocm gated; commission Phase 5 skips OMIX when `rocm_install_enabled`; new ROCm phase or branch exists; production Intel path still present).

- [ ] **Step 2: Update `playbooks/site.yml`**

Immediately after the Intel GPU include, add:

```yaml
    - name: Include ROCm role for AMD GPU lab/production nodes
      ansible.builtin.include_role:
        name: rocm
      when: rocm_install_enabled | default(false) | bool
      tags: [site, gpu, hardware, runtime, rocm]
```

Tighten the Intel include `when:` to:

```yaml
      when:
        - capabilities.gpu | default(false) | bool
        - not (rocm_install_enabled | default(false) | bool)
```

- [ ] **Step 3: Update `playbooks/commission.yml` Phase 5**

Change the Intel include `when:` to:

```yaml
      when:
        - capabilities.gpu | default(false) | bool
        - not (rocm_install_enabled | default(false) | bool)
```

**Remove** the forced `vars: intel_gpu_install_enabled: true` override for hosts that set it false — keep override only inside the Intel `when` branch (Intel hosts still need install during commission). For Intel branch retain:

```yaml
      vars:
        intel_gpu_install_enabled: true
```

Add a sibling play (still taggable `rocm` / keep `omix` tag only on Intel play):

```yaml
- name: "Phase 5b: Pinned ROCm stack installation"
  hosts: ai_hosts
  any_errors_fatal: true
  gather_facts: true
  tags:
    - rocm
  tasks:
    - name: Include ROCm role
      ansible.builtin.include_role:
        name: rocm
      when: rocm_install_enabled | default(false) | bool

    - name: Persist ROCm evidence checkpoint
      ansible.builtin.copy:
        content: >-
          {{
            {
              'schema_version': '1.0.0',
              'phase': 'rocm',
              'status': 'pass',
              'node': inventory_hostname,
              'rocm_release': rocm_release | default('7.2.0'),
              'engines_deferred': true,
              'generated_at': now(utc=true, fmt='%Y-%m-%dT%H:%M:%SZ')
            } | to_nice_json
          }}
        dest: /var/lib/local-ai/evidence/checkpoints/rocm.json
        owner: root
        group: root
        mode: "0640"
        force: false
      when: rocm_install_enabled | default(false) | bool
```

Phase 6 (hardware validation) stays shared — AMD backend is selected by profile.

Phases 7–8 remain gated on `capabilities.inference` (false for this host). Optionally write an explicit `engines_deferred.json` checkpoint when inference is false; not required if evidence already records deferred status in `rocm.json`.

- [ ] **Step 4: Tests GREEN; ansible syntax**

```bash
.venv/bin/pytest tests/test_rocm_contract.py tests/test_gpu_stack_contract.py -q
make syntax
```

- [ ] **Step 5: Commit**

```bash
git add playbooks/site.yml playbooks/commission.yml tests/test_rocm_contract.py
git commit -m "feat(playbooks): wire ROCm Phase 1 without forcing OMIX on AMD hosts"
```

---

### Task 8: Docs + storage pre-mount note

**Files:**
- Modify: `docs/commissioning.md`
- Modify: `docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-commissioning-design.md` (status → Implemented-in-progress / plan linked; storage size recorded as 1024g)

- [ ] **Step 1: Add commissioning section** for Minisforum MS-S1 Max Phase 1:

```markdown
## Minisforum MS-S1 Max (`ai-ms-s1-max-01`) — ROCm lab Phase 1

Inventory: `inventory/lab` only. Engines deferred.

1. Preflight: `ansible-playbook -i inventory/lab playbooks/commission.yml --limit ai-ms-s1-max-01 --tags preflight`
2. Bootstrap + baseline idempotency tags
3. Storage (`1024g` `local-ai-lv`). If `/var/lib/local-ai` already has root-fs directories (`metrics/`, etc.), archive them aside before the LV mount so content is not shadowed.
4. ROCm: `--tags rocm`
5. GPU validation: `--tags gpu_validation`
6. Do **not** run `--tags pytorch_xpu` / `--tags inference` in Phase 1
7. Full commission twice; second run must be idle
8. Fetch evidence to `evidence/ai-ms-s1-max-01/<timestamp>/`
```

- [ ] **Step 2: Commit**

```bash
git add docs/commissioning.md docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-commissioning-design.md
git commit -m "docs: MS-S1 Max ROCm Phase 1 commissioning runbook"
```

---

### Task 9: Physical commission on the host

**Files:**
- Create: `evidence/ai-ms-s1-max-01/<timestamp>/` (fetched artifacts)

- [ ] **Step 1: Connectivity + sudo**

```bash
ssh mike@10.0.8.6 'hostname; rocminfo | head -5; sudo -n true'
```

Expected: `ai-ms-s1-max-01`; ROCk module loaded; sudo OK.

- [ ] **Step 2: Archive any pre-existing `/var/lib/local-ai` root-fs content**

```bash
ssh mike@10.0.8.6 'sudo mkdir -p /root/local-ai-pre-mount-$(date -u +%Y%m%dT%H%M%SZ) && sudo rsync -a /var/lib/local-ai/ /root/local-ai-pre-mount-*/ 2>/dev/null || true'
```

- [ ] **Step 3: Run commission phases in order**

```bash
ansible-playbook -i inventory/lab playbooks/commission.yml --limit ai-ms-s1-max-01 --tags preflight
ansible-playbook -i inventory/lab playbooks/commission.yml --limit ai-ms-s1-max-01 --tags bootstrap
ansible-playbook -i inventory/lab playbooks/commission.yml --limit ai-ms-s1-max-01 --tags baseline_idempotency
ansible-playbook -i inventory/lab playbooks/commission.yml --limit ai-ms-s1-max-01 --tags storage
ansible-playbook -i inventory/lab playbooks/commission.yml --limit ai-ms-s1-max-01 --tags rocm
ansible-playbook -i inventory/lab playbooks/commission.yml --limit ai-ms-s1-max-01 --tags gpu_validation
```

If reboot required after ROCm, use existing reboot-verify workflow with `-i inventory/lab`, then re-run `--tags rocm,gpu_validation`.

- [ ] **Step 4: Idempotency**

```bash
ansible-playbook -i inventory/lab playbooks/commission.yml --limit ai-ms-s1-max-01 --tags preflight,bootstrap,baseline_idempotency,storage,rocm,gpu_validation
```

Expected: no material changes; checkpoints present; **no** inference units enabled.

- [ ] **Step 5: Fetch evidence**

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p evidence/ai-ms-s1-max-01/$TS
scp -r mike@10.0.8.6:/var/lib/local-ai/evidence/ evidence/ai-ms-s1-max-01/$TS/
```

- [ ] **Step 6: Commit evidence + close Phase 1**

```bash
git add evidence/ai-ms-s1-max-01/
git commit -m "evidence: ai-ms-s1-max-01 ROCm Phase 1 platform acceptance"
```

Update work state / todo: Phase 1 complete; next is separate engine-selection design.

---

## Spec coverage checklist

| Spec requirement | Task |
| --- | --- |
| Lab inventory only | Task 1 |
| `ms_s1_max_strix_halo` profile | Task 2 |
| Classifier AMD backend; Intel unchanged | Task 3 |
| rocminfo/NPU collection | Task 4 |
| Ansible-managed pinned ROCm 7.2.0 + Noble exception | Tasks 5–6 |
| NPU hard gate | Tasks 3, 6 |
| Storage LV pattern; size at plan time (1024g) | Tasks 1, 8–9 |
| site/commission without forcing Intel OMIX | Task 7 |
| Engines deferred | Tasks 1, 7, 9 |
| Evidence + idempotency | Task 9 |
| No production pool membership | Task 1 (never touch production inventory) |

## Self-review notes

- No TBD placeholders; storage size locked to **1024g** / reserve **100**.
- Commission Phase 5 Intel force-enable is explicitly narrowed so AMD hosts are safe.
- Existing `/var/lib/local-ai` on root FS is called out before mount.
- Pin map versions match live host survey (2026-11-21).
