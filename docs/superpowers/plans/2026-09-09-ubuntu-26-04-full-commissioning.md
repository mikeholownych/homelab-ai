# Ubuntu 26.04 Full Commissioning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Commission `ai-5820-01` on Ubuntu Server 26.04 with a release-safe baseline, a 550 GiB LVM data volume, pinned Intel OMIX 0.3.0, and BDF-correlated dual-GPU inference evidence.

**Architecture:** Explicit Noble and Resolute platform records drive package suites and GPU installation without weakening platform guards. Commissioning advances through fail-closed checkpoints: preflight, baseline, storage, OMIX, GPU validation, and inference; every physical phase emits evidence and a failed gate prevents later phases.

**Tech Stack:** Ansible Core 2.21, `community.general.lvol`, `community.general.filesystem`, `ansible.posix.mount`, Ubuntu 24.04/26.04, LVM2/XFS, Intel Xe KMD, Intel OMIX 0.3.0, Level Zero, PyTorch XPU, pytest, yamllint, ansible-lint.

---

## File Map

- `inventory/production/group_vars/all.yml`: authoritative supported-platform records.
- `inventory/production/host_vars/ai-5820-01.yml`: Resolute identity, LVM declaration, and commissioning flags.
- `playbooks/bootstrap.yml`: raw, pre-mutation OS gate.
- `playbooks/baseline.yml`: fact-based supported-platform gate.
- `roles/base_os/{defaults,tasks,templates}/`: release-aware APT configuration.
- `roles/storage/{defaults,tasks}/`: guarded LVM creation, filesystem creation, UUID mount, and storage evidence.
- `roles/intel_gpu/{defaults,tasks,templates}/`: OMIX preflight, repository, package installation, and activation.
- `roles/hardware_inventory/`: BDF-to-DRM/Level Zero discovery.
- `roles/hardware_validation/`: dual-device acceptance.
- `roles/pytorch_xpu/`: individual-device and dual-visible-device probes.
- `playbooks/commission.yml`: ordered phase entrypoint with explicit tags.
- `tests/fixtures/inventory/resolute.yml`: non-production Resolute contract inventory.
- `tests/integration/Dockerfile.resolute`: digest-pinned Ubuntu 26.04 harness.
- `tests/test_platform_contract.py`, `tests/test_storage_contract.py`, `tests/test_gpu_stack_contract.py`: static and behavioral contracts.
- `docs/{operations,commissioning,intel-gpu}.md`: operator workflow and support boundary.

### Task 1: Introduce an explicit supported-platform contract

**Files:**
- Modify: `inventory/production/group_vars/all.yml`
- Modify: `inventory/production/host_vars/ai-5820-01.yml`
- Create: `tests/test_platform_contract.py`

- [ ] **Step 1: Write the failing platform-map tests**

```python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path):
    return yaml.safe_load((ROOT / path).read_text())


def test_supported_platforms_are_explicit_and_release_isolated():
    platforms = load("inventory/production/group_vars/all.yml")["supported_platforms"]
    assert platforms["24.04"] == {
        "codename": "noble",
        "apt_suites": ["noble", "noble-updates", "noble-backports", "noble-security"],
    }
    assert platforms["26.04"] == {
        "codename": "resolute",
        "apt_suites": ["resolute", "resolute-updates", "resolute-backports", "resolute-security"],
    }
    assert not set(platforms["24.04"]["apt_suites"]) & set(platforms["26.04"]["apt_suites"])


def test_5820_declares_resolute_platform():
    host = load("inventory/production/host_vars/ai-5820-01.yml")
    assert host["platform_release"] == "26.04"
    assert host["platform_codename"] == "resolute"
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv/bin/pytest tests/test_platform_contract.py -q`

Expected: FAIL because `supported_platforms` and the host platform fields do not exist.

- [ ] **Step 3: Add the platform records**

Add to `inventory/production/group_vars/all.yml`:

```yaml
supported_platforms:
  "24.04":
    codename: noble
    apt_suites: [noble, noble-updates, noble-backports, noble-security]
  "26.04":
    codename: resolute
    apt_suites: [resolute, resolute-updates, resolute-backports, resolute-security]
```

Add near the connection fields in `inventory/production/host_vars/ai-5820-01.yml`:

```yaml
platform_release: "26.04"
platform_codename: resolute
```

- [ ] **Step 4: Run the tests and verify GREEN**

Run: `.venv/bin/pytest tests/test_platform_contract.py tests/test_inventory.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add inventory/production/group_vars/all.yml inventory/production/host_vars/ai-5820-01.yml tests/test_platform_contract.py
git commit -m "feat: declare supported Ubuntu platform releases"
```

### Task 2: Move bootstrap release validation before mutation

**Files:**
- Modify: `playbooks/bootstrap.yml`
- Modify: `playbooks/baseline.yml`
- Modify: `tests/test_baseline_contract.py`

- [ ] **Step 1: Add failing ordering and release-pair tests**

Append these assertions to `tests/test_baseline_contract.py`; they prove the
raw `/etc/os-release` gate precedes package mutation and contains both supported
release/codename pairs:

```python
def test_bootstrap_platform_gate_precedes_apt_mutation():
    text = (REPO_ROOT / "playbooks/bootstrap.yml").read_text()
    assert text.index("Validate raw Ubuntu release before mutation") < text.index("apt-get update")
    assert "24.04:noble" in text
    assert "26.04:resolute" in text


def test_production_bootstrap_does_not_bypass_platform_guard():
    text = (REPO_ROOT / "playbooks/bootstrap.yml").read_text()
    raw_gate = text[:text.index("Install minimal Python serialization prerequisites")]
    assert "baseline_skip_platform_guard" not in raw_gate
    assert "/etc/os-release" in raw_gate
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_baseline_contract.py -q`

Expected: the new ordering/release tests fail.

- [ ] **Step 3: Add a raw preflight task before Python bootstrap**

The first `pre_tasks` item in `playbooks/bootstrap.yml` must be:

```yaml
- name: Validate raw Ubuntu release before mutation
  ansible.builtin.raw: >-
    set -eu;
    . /etc/os-release;
    case "${ID}:${VERSION_ID}:${VERSION_CODENAME}" in
      ubuntu:24.04:noble|ubuntu:26.04:resolute) exit 0 ;;
      *) printf 'unsupported platform: %s:%s:%s\n' "$ID" "$VERSION_ID" "$VERSION_CODENAME" >&2; exit 42 ;;
    esac
  changed_when: false
```

Replace exact-24.04 fact assertions in bootstrap and baseline with membership
and codename-pair assertions against `supported_platforms`.

- [ ] **Step 4: Verify GREEN and syntax**

Run: `.venv/bin/pytest tests/test_baseline_contract.py -q`

Run: `.venv/bin/ansible-playbook -i inventory/production/hosts.yml playbooks/bootstrap.yml --syntax-check`

Expected: tests and syntax check pass.

- [ ] **Step 5: Commit**

```bash
git add playbooks/bootstrap.yml playbooks/baseline.yml tests/test_baseline_contract.py
git commit -m "fix: gate supported Ubuntu releases before bootstrap mutation"
```

### Task 3: Make the base OS role release-aware

**Files:**
- Modify: `roles/base_os/defaults/main.yml`
- Modify: `roles/base_os/tasks/main.yml`
- Modify: `roles/base_os/templates/aihost-baseline.sources.j2`
- Create: `tests/fixtures/inventory/resolute.yml`
- Create: `tests/integration/Dockerfile.resolute`
- Modify: `tests/integration/baseline_container_harness.py`
- Modify: `tests/test_baseline_contract.py`

- [ ] **Step 1: Add failing release-selection tests**

```python
def test_base_os_selects_suites_from_validated_release():
    defaults = load_yaml(REPO_ROOT / "roles/base_os/defaults/main.yml")
    assert defaults["base_os_supported_releases"] == ["24.04", "26.04"]
    tasks = (REPO_ROOT / "roles/base_os/tasks/main.yml").read_text()
    assert "base_os_resolved_platform" in tasks
    assert "ansible_facts.distribution_release" in tasks


def test_sources_template_has_no_hardcoded_noble_security():
    text = (REPO_ROOT / "roles/base_os/templates/aihost-baseline.sources.j2").read_text()
    assert "noble-security" not in text
    assert "base_os_security_suite" in text
```

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_baseline_contract.py -q`

- [ ] **Step 3: Resolve release data before package-source validation**

Define:

```yaml
base_os_supported_releases: ["24.04", "26.04"]
base_os_platforms: "{{ supported_platforms }}"
```

In tasks, assert the fact release exists, select
`base_os_resolved_platform: "{{ base_os_platforms[ansible_facts.distribution_version] }}"`,
assert its codename equals `ansible_facts.distribution_release`, and derive
`base_os_apt_suites` from that record. Set
`base_os_security_suite` to the sole suite ending in `-security`. Update the
template to use that variable in both suite filters and the security stanza.

- [ ] **Step 4: Add a digest-pinned Resolute container fixture**

Resolve the amd64 digest and query package candidates with these exact read-only
commands:

```bash
resolute_digest="$(docker buildx imagetools inspect ubuntu:26.04 --format '{{json .Manifest}}' | jq -r '.digest')"
printf '%s\n' "$resolute_digest"
docker run --rm "ubuntu@$resolute_digest" sh -ec \
  'apt-get update >/dev/null; apt-cache policy ansible-core auditd ca-certificates chrony iproute2 iptables jq locales logrotate netplan.io openssh-server python3 python3-apt rsync sudo ufw | sed -n "/^[^ ]/p;/Candidate:/p"'
```

Use the returned `sha256:...` literally in
`tests/integration/Dockerfile.resolute` as `FROM ubuntu@sha256:...`, and pin every
reported candidate in the Dockerfile. Extend the harness with `--release
noble|resolute`; do not replace the Noble harness.

- [ ] **Step 5: Run both baseline harnesses**

Run: `.venv/bin/python tests/integration/baseline_container_harness.py --release noble --mode idempotency`

Run: `.venv/bin/python tests/integration/baseline_container_harness.py --release resolute --mode idempotency`

Expected: each second run reports `changed=0`.

- [ ] **Step 6: Commit**

```bash
git add roles/base_os tests/fixtures/inventory/resolute.yml tests/integration tests/test_baseline_contract.py
git commit -m "feat: support Noble and Resolute baseline convergence"
```

### Task 4: Add guarded LVM-backed local AI storage

**Files:**
- Modify: `requirements.yml`
- Modify: `roles/storage/defaults/main.yml`
- Modify: `roles/storage/tasks/main.yml`
- Create: `roles/storage/tasks/lvm.yml`
- Modify: `inventory/production/host_vars/ai-5820-01.yml`
- Create: `tests/test_storage_contract.py`

- [ ] **Step 1: Write failing storage-contract tests**

Assert the host declares exactly this desired state and the role contains
preflight commands before `community.general.lvol` or filesystem mutation:

```yaml
storage_lvm:
  enabled: true
  vg: ubuntu-vg
  lv: local-ai-lv
  size: 550g
  fstype: xfs
  mount_path: /var/lib/local-ai
  reserve_gib: 50
  expected_pvs:
    - /dev/nvme0n1p3
    - /dev/nvme1n1p1
```

The tests must also assert `force: false`, `resizefs: false`, UUID-based mount
resolution, and no `pvcreate`, `vgcreate`, `wipefs`, or `force: true` command.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_storage_contract.py -q`

- [ ] **Step 3: Implement read-only LVM preflight**

Use `pvs --reportformat json`, `vgs --reportformat json`, `lvs --reportformat
json`, `findmnt --json`, and `blkid -p` with `changed_when: false`. Assert both
PVs are members of the named VG, free bytes satisfy the requested LV plus
reserve when absent, and any existing LV/filesystem/mount matches the declaration.

- [ ] **Step 4: Implement guarded creation and UUID mount**

```yaml
- community.general.lvol:
    vg: "{{ storage_lvm.vg }}"
    lv: "{{ storage_lvm.lv }}"
    size: "{{ storage_lvm.size }}"
    resizefs: false
- community.general.filesystem:
    dev: "/dev/{{ storage_lvm.vg }}/{{ storage_lvm.lv }}"
    fstype: "{{ storage_lvm.fstype }}"
    force: false
- ansible.builtin.command:
    argv: [blkid, -s, UUID, -o, value, "/dev/{{ storage_lvm.vg }}/{{ storage_lvm.lv }}"]
  register: storage_lvm_uuid
  changed_when: false
- ansible.posix.mount:
    path: "{{ storage_lvm.mount_path }}"
    src: "UUID={{ storage_lvm_uuid.stdout }}"
    fstype: "{{ storage_lvm.fstype }}"
    opts: defaults
    state: mounted
```

Guard creation tasks with `storage_manage_runtime` and preflight success.

- [ ] **Step 5: Emit and test storage evidence**

Write `/var/lib/local-ai/evidence/storage-layout.json` atomically with PV UUIDs,
VG/LV sizes, filesystem UUID, mount path, and free capacity. Add a loopback-backed
integration test that converges twice and requires `changed=0` on the second run.

- [ ] **Step 6: Commit**

```bash
git add requirements.yml roles/storage inventory/production/host_vars/ai-5820-01.yml tests/test_storage_contract.py tests/integration
git commit -m "feat: manage guarded local AI LVM storage"
```

### Task 5: Implement pinned OMIX 0.3.0 installation for Resolute

**Files:**
- Modify: `roles/intel_gpu/defaults/main.yml`
- Modify: `roles/intel_gpu/tasks/main.yml`
- Create: `roles/intel_gpu/tasks/preflight.yml`
- Create: `roles/intel_gpu/tasks/omix.yml`
- Create: `roles/intel_gpu/templates/intel-omix.sources.j2`
- Modify: `tests/test_gpu_stack_contract.py`
- Modify: `docs/intel-gpu.md`

- [ ] **Step 1: Add failing OMIX contract tests**

Require literal release `0.3.0`, codename `resolute`, HTTPS repository
`https://repositories.intel.com/gpu/ubuntu`, a non-empty signing-key SHA-256 and
fingerprint, exact package pins, conflict checks before repository mutation, and
absence of `ppa:kobuk-team/intel-graphics`.

- [ ] **Step 2: Resolve immutable inputs without changing the host**

Download Intel's current public key on the controller, calculate SHA-256 and
full fingerprint, query the `resolute/intel-omix/0.3.0` repository metadata, and
record exact versions for `intel-omix` and `intel-omix-dev`. Update defaults with
literal values and source URLs. If exact versions cannot be resolved, stop this
task without enabling installation.

- [ ] **Step 3: Implement fail-closed preflight**

Before mutation, assert Ubuntu `26.04/resolute`, kernel `>= 7.0`, both target PCI
IDs, no Intel graphics PPA, no non-OMIX Intel GPU repository, and no conflicting
installed user-mode package set. Keep the existing Noble path separate.

- [ ] **Step 4: Install verified repository and exact packages**

Use `get_url` with the recorded checksum, dearmor to a temporary file, validate
the resulting key fingerprint, atomically install the keyring, render the exact
0.3.0 deb822 source, update APT, and install `package=version` entries. Record
resolved package versions after installation.

- [ ] **Step 5: Verify contract tests and syntax**

Run: `.venv/bin/pytest tests/test_gpu_stack_contract.py -q`

Run: `.venv/bin/ansible-playbook -i inventory/production/hosts.yml playbooks/site.yml --syntax-check`

- [ ] **Step 6: Commit**

```bash
git add roles/intel_gpu tests/test_gpu_stack_contract.py docs/intel-gpu.md
git commit -m "feat: install pinned OMIX stack on Ubuntu 26.04"
```

### Task 6: Strengthen dual-BDF compute acceptance

**Files:**
- Modify: `roles/hardware_inventory/files/collect_hardware.py`
- Modify: `roles/hardware_validation/files/classify_hardware.py`
- Modify: `roles/pytorch_xpu/files/validate_xpu.py`
- Modify: `roles/pytorch_xpu/tasks/main.yml`
- Modify: `tests/test_hardware_validation.py`
- Modify: `tests/test_gpu_stack_contract.py`

- [ ] **Step 1: Write failing two-device correlation tests**

Add fixtures with two PCI BDFs but only one DRM/Level Zero/PyTorch device and
assert blocking failure. Add a healthy fixture mapping both BDFs to distinct
render nodes and XPU ordinals and assert pass.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_hardware_validation.py tests/test_gpu_stack_contract.py -q`

- [ ] **Step 3: Extend discovery records**

For every approved GPU emit `pci_bdf`, `pci_id`, `kernel_driver`, `drm_card`,
`render_node`, `level_zero_uuid`, and `xpu_ordinal`. Preserve `None` rather than
inventing a correlation when sysfs or runtime data is incomplete.

- [ ] **Step 4: Enforce bijective correlation**

Classifier pass requires exactly two unique approved BDFs, two distinct render
nodes, two distinct Level Zero identities, and no missing link. PyTorch probes
must allocate a tensor and synchronize separately on `xpu:0` and `xpu:1`, then
run one process with `torch.xpu.device_count() == 2`.

- [ ] **Step 5: Verify GREEN and commit**

Run: `.venv/bin/pytest tests/test_hardware_validation.py tests/test_gpu_stack_contract.py -q`

```bash
git add roles/hardware_inventory roles/hardware_validation roles/pytorch_xpu tests
git commit -m "feat: require dual-BDF XPU acceptance"
```

### Task 7: Add an ordered commissioning entrypoint and evidence checkpoints

**Files:**
- Create: `playbooks/commission.yml`
- Modify: `Makefile`
- Modify: `tests/test_lifecycle_workflows.py`
- Modify: `docs/commissioning.md`
- Modify: `docs/operations.md`

- [ ] **Step 1: Add failing workflow tests**

Assert the playbook imports or defines phases in this exact order:

```text
preflight, bootstrap, baseline_idempotency, storage, omix, gpu_validation, pytorch_xpu, inference
```

Assert every phase is independently taggable and the playbook targets
`ai_hosts` so `--limit ai-5820-01` is mandatory in the documented production
command.

- [ ] **Step 2: Verify RED**

Run: `.venv/bin/pytest tests/test_lifecycle_workflows.py -q`

- [ ] **Step 3: Create the phase-gated playbook**

Each play or role inclusion must carry its phase tag, use `any_errors_fatal:
true`, and persist a schema-valid checkpoint before the next phase. Do not
automatically reboot; end the OMIX phase with a `reboot_required` fact and a
documented `playbooks/reboot-verify.yml` operator checkpoint.

- [ ] **Step 4: Document exact commissioning commands**

Document dry preflight, each mutation phase, reboot verification, validation,
and rerun commands. State that Ubuntu Server acceptance is evidence-based and
that linear LVM is not redundant.

- [ ] **Step 5: Verify and commit**

Run: `.venv/bin/pytest tests/test_lifecycle_workflows.py tests/test_documentation_contract.py -q`

Run: `.venv/bin/ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --syntax-check`

```bash
git add playbooks/commission.yml Makefile tests/test_lifecycle_workflows.py docs/commissioning.md docs/operations.md
git commit -m "feat: add checkpointed host commissioning workflow"
```

### Task 8: Repository verification before physical mutation

**Files:**
- Modify: role `meta/main.yml` files whose tasks were proven on Resolute
- Modify: `README.md`
- Modify: `docs/architecture.md`
- Modify: `docs/security-controls.md`

- [ ] **Step 1: Update only verified role metadata and platform docs**

Add `resolute` beside `noble` only for roles exercised by both disposable
harnesses. Update documentation to describe both supported releases, the OMIX
Server qualification caveat, and the release-specific package boundary.

- [ ] **Step 2: Run the full repository gate**

Run: `make quality`

Expected: yamllint and ansible-lint pass; all pytest tests pass; all playbook
syntax checks pass; Noble and Resolute idempotency harnesses report `changed=0`.

- [ ] **Step 3: Review the mutation plan**

Run: `.venv/bin/ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01 --check --diff --tags preflight,bootstrap,storage,omix`

Expected: no unsupported platform, repository conflict, storage conflict, or
single-GPU gate failure. Review every predicted change before continuing.

- [ ] **Step 4: Commit repository readiness**

```bash
git add README.md docs roles/*/meta/main.yml
git commit -m "docs: declare verified Ubuntu 26.04 commissioning support"
```

### Task 9: Commission the physical host through explicit checkpoints

**Files:**
- Generated on host: `/var/lib/local-ai/evidence/**`
- No repository evidence containing secrets or machine credentials

- [ ] **Step 1: Run preflight only**

Run: `.venv/bin/ansible-playbook -i inventory/production/hosts.yml playbooks/commission.yml --limit ai-5820-01 --tags preflight --diff`

Expected: supported `26.04/resolute`, both NVMe PVs in `ubuntu-vg`, at least
600 GiB free, and two `8086:e222` BDFs; no host changes.

- [ ] **Step 2: Bootstrap and prove idempotency**

Run bootstrap once, verify SSH reconnection, run it again, and require
`changed=0` on the second run. Stop if the firewall or SSH effective-config
proof fails.

- [ ] **Step 3: Create and verify storage**

Run only the storage phase. Confirm `local-ai-lv` is exactly 550 GiB, XFS is
mounted by UUID at `/var/lib/local-ai`, VG free space is at least 50 GiB, and a
second storage run reports `changed=0`.

- [ ] **Step 4: Install OMIX and handle reboot checkpoint**

Run only the OMIX phase. Record exact installed versions. If reboot is required,
run `playbooks/reboot-verify.yml --limit ai-5820-01`, wait for SSH, and repeat
preflight before proceeding.

- [ ] **Step 5: Run physical GPU and PyTorch acceptance**

Require both BDFs, both render nodes, both Level Zero devices, successful
per-device PyTorch allocation, and a two-visible-device PyTorch process. A
one-device result is blocking.

- [ ] **Step 6: Commission pinned inference profiles**

Resolve and record exact vLLM, llama.cpp, and model artifacts before enabling
their host profiles. Run single-device then TP=2 inference acceptance; keep any
runtime disabled if its test does not pass.

- [ ] **Step 7: Capture final evidence and report**

Export irreplaceable evidence off-host, run full validation, and report each
phase as `pass`, `blocked`, or `not_tested`. Do not label the host accepted unless
every enabled production runtime passes.
