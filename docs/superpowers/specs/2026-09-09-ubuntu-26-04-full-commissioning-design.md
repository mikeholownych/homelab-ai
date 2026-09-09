# Ubuntu 26.04 Full Commissioning Design

**Date:** 2026-09-09

**Status:** Approved

## Goal

Make Ubuntu Server 26.04 (Resolute) a first-class, fail-closed platform for
`ai-5820-01`, including the operating-system baseline, a dedicated LVM-backed
data volume, Intel Arc Pro B65 compute enablement, and physical validation of
the dual-GPU inference path. Ubuntu 24.04 (Noble) remains supported without a
behavioral regression.

## Current Host State

- Host: `ai-5820-01` at `10.0.8.5`, accessed as `mike` with SSH keys and
  passwordless sudo.
- Platform: Dell Precision 5820 Tower, Ubuntu Server 26.04, kernel 7.0, Python
  3.14.
- Accelerators: two PCI devices `8086:e222`, enumerated as Intel Battlemage G31
  devices before userspace compute-driver installation.
- Storage: two approximately 477 GiB NVMe devices are LVM physical volumes in
  `ubuntu-vg`. Existing XFS logical volumes are `root-lv` (100 GiB), `usr-lv`
  (100 GiB), and `home-lv` (150 GiB). The VG has approximately 600.82 GiB free.

## Support Boundary

Ubuntu 24.04 and Ubuntu 26.04 are separate supported release profiles. Release
guards execute before any potentially mutating bootstrap operation. No override
may make Noble repository suites available to a Resolute host or vice versa.

Intel documents Ubuntu 26.04 support for Battlemage and lists Ubuntu 26.04 as an
Intel OMIX 0.3.0 host operating system. Its OMIX installation guide specifically
names Ubuntu Desktop 26.04. Because this host runs Ubuntu Server, successful
package installation alone is insufficient for acceptance. The Server variant
remains conditionally supported until real hardware evidence passes every PCI,
DRM, Level Zero, PyTorch XPU, and inference gate.

Authoritative vendor references:

- https://dgpu-docs.intel.com/driver/client/overview.html
- https://dgpu-docs.intel.com/installation-guides/installing-omix.html
- https://dgpu-docs.intel.com/overview/support-matrix/omix-support-matrix.html
- https://dgpu-docs.intel.com/overview/release-notes/OMIX/0.3.0.html
- https://documentation.ubuntu.com/release-notes/26.04/

## Platform Architecture

Release-specific data controls package-suite and platform behavior:

- Ubuntu 24.04 uses Noble suites and retains its existing HWE-based path.
- Ubuntu 26.04 uses Resolute suites, its native Xe kernel driver, and the Intel
  OMIX 0.3.0 Resolute repository for compute userspace.

Shared baseline roles remain release-neutral where their behavior is identical.
Release-specific values are selected from explicit mappings, not derived by
string interpolation from untrusted facts. Unsupported distributions, versions,
or codenames fail before package metadata or host configuration changes.

Role metadata declares both Noble and Resolute only for roles whose tasks have
been reviewed and tested on both releases. Test-only platform-guard overrides
remain restricted to disposable localhost fixtures.

The Dell hardware profile identifies `8086:e222` as Battlemage rather than
Alchemist. PCI database labels are discovery evidence, not proof that compute
drivers or runtimes function.

## Baseline Commissioning Flow

1. Capture read-only OS, package-source, Secure Boot, kernel/module, GPU, block
   device, LVM, and filesystem state.
2. Validate Ubuntu release support before the raw Python-prerequisite task.
3. Install only release-appropriate bootstrap prerequisites.
4. Apply access, time, base-OS, SSH, and security controls.
5. Rerun the baseline and require zero changes before continuing.

The bootstrap preflight must not depend on Python being present. It reads
`/etc/os-release` through raw SSH and accepts only the explicit supported
release/codename pairs.

## Storage Design

Create `local-ai-lv`, a 550 GiB linear logical volume in `ubuntu-vg`, format it
as XFS, and mount it persistently at `/var/lib/local-ai`. The owning roles create
`models/`, `cache/`, `evidence/`, and runtime-specific subdirectories below the
mount. Approximately 50.82 GiB remains free in the VG for recovery and controlled
growth.

Before mutation, the storage role asserts all of the following:

- both expected NVMe physical volumes belong to `ubuntu-vg`;
- the VG has at least 550 GiB free when the target LV is absent;
- an existing `local-ai-lv`, filesystem, or mount is compatible with the desired
  state;
- `/var/lib/local-ai` is not backed by another filesystem;
- source PVs have no unrecognized filesystem or mount state.

Formatting is allowed only for a newly created, empty target LV without an
existing filesystem signature. The persistent mount uses the filesystem UUID.
PV UUIDs, VG/LV topology, filesystem UUID, mount state, and remaining capacity
are recorded as commissioning evidence.

This layout aggregates capacity; it provides no redundancy. Loss of either NVMe
may make a spanning logical volume unavailable. Model and cache content must be
reproducible, while irreplaceable evidence must also be exported off-host.

## Intel GPU and Compute Stack

The 26.04 path uses the native kernel/Xe support plus Intel OMIX 0.3.0. It must:

- reject Intel graphics PPA configuration, incompatible Intel repositories, and
  preinstalled packages that conflict with the pinned OMIX set;
- install a checksum- and fingerprint-verified Intel signing key;
- configure the exact Resolute OMIX 0.3.0 repository path;
- resolve, record, and enforce immutable package versions before installation;
- install only the reviewed runtime/development package set;
- reboot only when kernel or module activation requires it;
- preserve the existing Noble path and its independent safeguards.

No mutable major/minor repository channel, `ignore_errors`, simulated hardware
result, or generic module-loaded assertion may satisfy commissioning.

## Hardware and Runtime Acceptance

Post-install validation correlates both `8086:e222` PCI BDFs through every layer:

1. PCI discovery and approved hardware profile.
2. Xe kernel binding and two usable DRM render nodes.
3. Level Zero enumeration of both physical devices.
4. Per-device memory and firmware observations.
5. PyTorch XPU execution on each individual device.
6. PyTorch XPU execution with both devices visible.
7. Pinned vLLM XPU single-device and tensor-parallel-two execution.
8. Pinned llama.cpp SYCL validation, without claiming dual-GPU certification
   until the real split path passes.

Runtime and model profiles remain disabled until their exact artifacts, model
selection, and physical acceptance tests pass. Two 32 GiB devices are a
multi-device pool, not a transparent 64 GiB device.

## Failure Handling and Evidence

Commissioning is checkpointed:

`preflight -> bootstrap -> baseline idempotency -> storage -> reboot if needed
-> OMIX -> GPU validation -> PyTorch XPU -> inference runtimes`

Each phase emits schema-valid evidence before the next begins. A failed gate
halts subsequent phases and records the last verified state. Package conflicts,
wrong release suites, insufficient LVM capacity, incompatible existing storage,
missing render nodes, partial GPU visibility, or Server-specific runtime failure
cannot be downgraded to warnings for production acceptance.

## Testing Strategy

- Contract tests enforce the Noble/Resolute release map and reject cross-release
  suites.
- Ubuntu 26.04 fixture coverage exercises Python 3.14, APT 3, systemd 259, and
  kernel 7.0 assumptions while retaining Ubuntu 24.04 fixtures.
- Intel GPU tests enforce the exact OMIX repository, trusted key identity,
  immutable package pins, repository-conflict detection, and dual-BDF evidence.
- Storage tests cover fresh LV creation, insufficient free space, conflicting
  state, exact 550 GiB allocation, UUID mounting, and a zero-change rerun.
- Repository quality, playbook syntax, and disposable baseline validation pass
  before physical-host mutation.
- Physical acceptance requires both GPUs to pass PCI, DRM, Level Zero, PyTorch,
  and inference checks. One-device success is not partial acceptance.

## Completion Criteria

The work is complete only when:

- all local contract, lint, syntax, and disposable integration checks pass;
- bootstrap and storage converge twice with zero changes on the second run;
- both GPUs pass BDF-correlated compute validation after any required reboot;
- the approved inference workloads pass their single- and dual-GPU checks;
- evidence records the Ubuntu Server qualification caveat and every physical
  result;
- no production runtime is enabled without immutable artifacts and an explicit
  model selection.
