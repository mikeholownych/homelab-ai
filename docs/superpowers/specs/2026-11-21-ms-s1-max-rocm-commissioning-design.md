# MS-S1 Max ROCm Lab Commissioning Design (Phase 1)

**Date:** 2026-11-21

**Status:** Approved (design review); awaiting implementation plan

**Host:** `ai-ms-s1-max-01` at `10.0.8.6` (Minisforum MS-S1 Max)

## Goal

Commission `ai-ms-s1-max-01` as a **lab qualification host**: Ubuntu 26.04
baseline, Ansible-managed ROCm 7.2.0, a Strix Halo + NPU hardware profile, and a
sized-later `/var/lib/local-ai` data volume. Determine the best long-term setup
with measured evidence **before** adding the host to the production inference
pool.

## Non-Goals

- Inference engine selection or enablement (llama.cpp HIP, vLLM ROCm, SGLang, or
  others). That is a separate engine-selection design/plan after Phase 1.
- Production `ai_hosts` membership, reconcile-controller targeting, or gateway
  worker pool membership.
- Modifying or coupling to the Intel Arc Pro B65 / OMIX / SYCL path on
  `ai-5820-01`.
- Disabling Secure Boot.
- Changing APU GTT/VRAM carve-out unless a later measured plan adds it.

## Decisions (operator-approved)

| Topic | Choice |
| --- | --- |
| Fleet role | Lab / qualification first; promote only after evidence |
| Engine scope | Deferred; Phase 1 is OS / ROCm / storage / hardware only |
| ROCm ownership | Ansible fully manages and pins ROCm 7.2.0 |
| NPU | Hard acceptance gate alongside GPU (`aie2p`) |
| Inventory | `inventory/lab/` only until promotion |
| Storage size | LV/mount pattern fixed; size chosen at plan time |
| Architecture | Parallel AMD stack (new profile + `roles/rocm/`) |

## Current Host State

Captured 2026-11-21 over SSH as `mike@10.0.8.6` (passwordless sudo; Secure Boot
**enabled**).

| Item | Observed |
| --- | --- |
| Hostname | `ai-ms-s1-max-01` |
| DMI | Micro Computer (HK) Tech Limited / **MS-S1 MAX** / serial `MD458LMSS1HHMPA00141` |
| OS | Ubuntu Server 26.04.1 LTS (Resolute), kernel `7.0.0-44-generic` |
| CPU | AMD Ryzen AI Max+ 395, 16 cores / 32 threads |
| System RAM | ~122 GiB |
| GPU PCI | `1002:1586` at `bd:00.0`, kernel `amdgpu`, DRM `card1` / `renderD128` |
| HSA GPU | `gfx1151` (~61 GiB coarse-grained APU pool via `rocminfo`) |
| NPU | HSA `aie2p` / RyzenAI-npu5; kernel `amdxdna`; `/dev/accel/accel0` |
| ROCm | 7.2.0 (`/opt/rocm` → `rocm-7.2.0`); `rocminfo` reports 3 agents |
| APT | Vendor Noble suites: `rocm/apt/7.2`, `graphics/7.2`, `amdgpu/30.30` |
| Keyring | `/etc/apt/keyrings/rocm.gpg` SHA-256 `3e660bdc559b34781b5498e79b9c117394b46ce55592812db0b84d65986b4df2`; fingerprint `CA8B BB47 27A4 7B4D 09B4 E896 9386 B48A 1A69 3C5C` (AMD MLSE DevOps) |
| Storage | `ubuntu-vg` on `/dev/nvme0n1p3` (~1.82 TiB); root LV 100 GiB; **~1.72 TiB free** |
| Runtimes | No llama-server / vLLM / podman / docker present; `hipcc` present |

## Support Boundary

- Phase 1 supports this exact platform: Ubuntu Server 26.04 + vendor ROCm
  **7.2.0** on Strix Halo (`gfx1151`) + NPU (`aie2p` / `amdxdna`).
- ROCm’s **Noble** APT suites on a Resolute host are an **explicit, pinned
  exception** matching vendor packaging. Ansible must pin repo URLs, keyring,
  and package versions. Unpinned `latest` channels are rejected.
- The host remains lab-only: never a member of production `ai_hosts` or
  reconcile targets until a later promotion design.
- Inference runtimes remain disabled until a separate engine-selection plan.
- Secure Boot stays enabled; commissioning must not require disabling it unless
  a measured blocker is recorded and separately approved.

## Architecture

```
inventory/lab/ai-ms-s1-max-01
        │
        ▼
 bootstrap / OS baseline ──► hardware profile gate
        │                         (ms_s1_max_strix_halo)
        ▼
 storage (local-ai-lv) ──► roles/rocm (pinned 7.2.0)
        │                         │
        ▼                         ▼
 evidence archive ◄────── compute acceptance
                          (GPU gfx1151 + NPU aie2p)
```

- **Inventory:** `inventory/lab/` only (real SSH host alongside the existing
  localhost fixture `ai-5820-test-01`).
- **Hardware profile:** `profiles/hardware/ms_s1_max_strix_halo.yml`.
- **New role:** `roles/rocm/` — AMD repos/key, pinned packages, device access,
  post-install gates. Defaults keep `rocm_install_enabled: false` everywhere
  except this lab host.
- **Reuse:** bootstrap/baseline, existing `storage` LVM pattern, extended
  hardware validation. **Do not** change `intel_gpu` mutation behavior.
- **Evidence:** `evidence/ai-ms-s1-max-01/<timestamp>/` plus on-host copies under
  `/var/lib/local-ai/evidence/` after the data volume exists.

## Inventory Wiring

- Host `ai-ms-s1-max-01` with `ansible_host: 10.0.8.6`.
- Groups: `lab`, `gpu` (optional later: `monitoring` for node metrics). **Not**
  in production inventory; **not** in production `inference` / `cluster`.
- Host vars (from template, specialized):
  - `hardware_profile: ms_s1_max_strix_halo`
  - `os_tuning_profile: baseline`
  - `node_roles.gpu: true`
  - `node_roles.inference: false` (engines deferred)
  - Worker/gateway/inference feature flags **off**
  - `rocm_install_enabled: true`

## Phase 1 Commissioning Flow

Fail closed between checkpoints:

1. **Preflight (read-only)** — OS release, Secure Boot, DMI, PCI `1002:1586`,
   `/dev/kfd` + DRI + `/dev/accel`, LVM free space, existing ROCm/APT state →
   evidence.
2. **Bootstrap / OS baseline** — access, time, base packages, SSH/security;
   rerun to `changed=0`.
3. **Hardware profile gate** — classifier accepts `ms_s1_max_strix_halo`.
4. **Storage** — create/mount `local-ai-lv` at `/var/lib/local-ai` (size from
   host_vars set at plan time); UUID fstab; evidence.
5. **ROCm manage** — pin keyring + Noble suite repos + immutable 7.2.0 package
   set; converge; reboot only if module/kernel activation requires it.
6. **Compute acceptance** — `rocminfo` agents CPU + `gfx1151` + `aie2p`;
   `rocm-smi` device 0; `amdxdna` + `/dev/accel/accel0`; group access for
   service users.
7. **Idempotency** — full Phase 1 play twice; second run has no material
   changes.
8. **Stop** — no engine/image/model enablement; emit evidence status
   **platform accepted / engines deferred**.

## Storage Design

Reuse the existing `storage` role LVM path (same shape as `ai-5820-01`),
adapted for this host’s single-PV VG.

| Field | Value |
| --- | --- |
| VG | `ubuntu-vg` (existing) |
| Expected PV | `/dev/nvme0n1p3` only |
| LV | `local-ai-lv` |
| Filesystem | XFS |
| Mount | `/var/lib/local-ai` by filesystem UUID |
| Evidence | `/var/lib/local-ai/evidence/storage-layout.json` (+ mirrored off-host) |

**Size policy:** `storage_lvm.size` is required in host_vars and is filled in the
**implementation plan** after measuring the intended model/artifact set for later
engine bake-off. The plan must also set `reserve_gib` so VG free space never
drops below a recovery floor (default proposal ≥ 50 GiB unless plan evidence
says otherwise).

**Pre-mutation asserts:** expected PV membership; enough free extents for
`size`; no conflicting filesystem/mount on the target path; format only on a new
empty LV without an existing signature.

**Constraints:** single NVMe → no redundancy; model/cache content must be
reproducible; irreplaceable evidence exported off-host. Root LV stays 100 GiB;
do not grow root for models.

## ROCm Role (`roles/rocm/`)

Mirror the fail-closed style of `intel_gpu` as a **separate** role (no shared
mutation path with Intel).

### Ownership

- Keyring at `/etc/apt/keyrings/rocm.gpg` (checksum + fingerprint verified;
  live baseline fingerprint and SHA-256 recorded under Current Host State).
- Pinned APT sources matching the working live set:
  - `https://repo.radeon.com/rocm/apt/7.2` → `noble main`
  - `https://repo.radeon.com/graphics/7.2/ubuntu` → `noble main`
  - `https://repo.radeon.com/amdgpu/30.30/ubuntu` → `noble main`
- Immutable package version map for the reviewed ROCm **7.2.0** set. The
  implementation plan freezes exact versions from the live `dpkg` inventory into
  role defaults (starting point: `rocm-core` `7.2.0.70200-43~24.04` and the
  installed `rocm*` / `hip*` set on the host).
- Ensure operator account and future `aihost-runtime` are in `render` / `video`;
  `/dev/kfd`, DRI render, and `/dev/accel/accel0` usable.
- Optional: assert `amdgpu` / `amdxdna` module load expectations.
- **No** default `HSA_OVERRIDE_GFX_VERSION` (`gfx1151` is native).

### Blocking gates

- Ubuntu 26.04 and kernel ≥ 7.0 (as observed on this host).
- PCI `1002:1586` present and bound to `amdgpu`.
- After converge: `rocminfo` reports agents **CPU**, **GPU gfx1151**, and
  **DSP/NPU aie2p**.
- `rocm-smi` sees device 0; `amdxdna` loaded; `/dev/accel/accel0` exists.
- Reject unpinned/latest channels, missing key fingerprint, or package version
  drift from the pin map.

### Out of role scope

- Inference engines, model downloads, PyTorch wheels, gateway units.
- Disabling Secure Boot.
- APU memory carve-out tuning unless a later measured plan adds it.

## Hardware Profile & Acceptance

### Profile: `profiles/hardware/ms_s1_max_strix_halo.yml`

- Platform: Micro Computer (HK) Tech Limited / MS-S1 MAX (patterns: `MS-S1 MAX`,
  `MS-S1`).
- CPU: AMD; patterns include `RYZEN AI MAX+ 395` / `Ryzen AI Max+ 395`; 1 socket.
- GPU: `count_expected: 1`; approved PCI `1002:1586` (Radeon 8060S / Strix Halo);
  memory expected **61 GiB** APU coarse pool (±4 GiB) from `rocminfo` /
  `rocm-smi` (**not** Level Zero / BAR size; live coarse pool was
  64325152 KiB ≈ 61.3 GiB).
- System memory: expected **122 GiB** (±4 GiB).
- Firmware: Above-4G / ReBAR treated as **not_applicable** for this APU (not
  discrete-slot tower gates); do not block on inapplicable PCIe slot checks.
- NPU: expected HSA agent `aie2p` / marketing `RyzenAI-npu5`; kernel `amdxdna`;
  `/dev/accel/accel0` — **blocking** if missing after ROCm converge.

### Classifier changes

Today’s `roles/hardware_validation/files/classify_hardware.py` assumes Intel
Level Zero dual-B65 semantics. Phase 1 adds a **profile-selected compute
evidence backend**: Intel profiles keep the Level Zero path; the
`ms_s1_max_strix_halo` profile selects an AMD path that validates **PCI + DRM +
rocminfo/rocm-smi + NPU**. Existing Intel fixtures and behavior must remain
unchanged.

### Phase 1 acceptance (all required)

1. Hardware profile PASS (machine / CPU / GPU PCI).
2. Storage LV mounted; evidence recorded.
3. ROCm pin converge; three HSA agents present.
4. NPU path present (`aie2p` + `amdxdna` + `/dev/accel/accel0`).
5. Idempotent second run.
6. Evidence archive under `evidence/ai-ms-s1-max-01/<timestamp>/`.
7. Explicit status: **platform accepted; engines deferred**.

## Failure Handling

Checkpoints:

`preflight → bootstrap → hardware profile → storage → ROCm → compute acceptance → idempotency`

Any blocking gate stops later phases; last verified evidence is retained. The
following cannot be downgraded to warnings:

- wrong Ubuntu release;
- unpinned ROCm channel;
- package pin drift;
- missing `gfx1151` or `aie2p`;
- missing `/dev/kfd` or `/dev/accel/accel0`;
- insufficient VG free for the declared LV size;
- conflicting storage state.

Reboot only when role evidence shows kernel/module activation requires it;
post-reboot re-runs compute acceptance.

## Testing Strategy

- **Unit/contract:** ROCm role pin map; Noble-suite exception only when
  explicitly configured; key fingerprint checks; NPU + GPU agent assertions.
- **Classifier:** AMD profile fixtures (PASS path + missing-NPU FAIL); existing
  dual-B65 fixtures still PASS.
- **Storage:** fresh LV, insufficient free space, conflict, UUID mount,
  zero-change rerun (size parameterized).
- **Repo quality:** lint/syntax on touched playbooks/roles before any host
  mutation.
- **Physical:** run Phase 1 against `ai-ms-s1-max-01` via `inventory/lab` only;
  archive evidence.

## Completion Criteria

Phase 1 is complete only when:

- Lab inventory, hardware profile, `rocm` role, and classifier AMD path are
  landed and targeted tests are green.
- The host converges twice with no material drift.
- Evidence shows three HSA agents, NPU device node, storage mount, and pinned
  ROCm 7.2.0.
- The host has no production inventory membership and no inference services
  enabled.
- A follow-on engine-selection design/plan is explicitly out of scope for this
  document and remains to be written after Phase 1 acceptance.

## Follow-On (out of scope here)

Separate design + plan to A/B inference engines on the accepted ROCm platform
(e.g. llama.cpp HIP, vLLM ROCm, others), then a promotion design to move the
host from `inventory/lab/` into the production pool if warranted.
