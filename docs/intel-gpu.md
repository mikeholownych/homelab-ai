# Intel Arc Pro B65 and PyTorch XPU

Status: **NOT_TESTED on physical hardware** (both e222 cards are staged but not yet installed) and disabled until commissioning
approves the pinned compatibility set.

## Support decision (researched 2026-08-27)

Intel's generic supported-hardware table identifies Arc Pro B65 as PCI ID `8086:e222` with full support where the Xe KMD is
present (default-enabled from Ubuntu 25.10+/kernel 6.17). Intel's OMIX installation guide names B65 as a validated card on
Ubuntu Desktop 26.04, Ubuntu Desktop 24.04.4, or Ubuntu Desktop 24.04 with the 6.17 HWE kernel.

Today there is no remaining "unresolved" vendor conflict: B65 has an explicit, full upstream support statement. The remaining
gap is our target install surface — a headless Ubuntu Server 24.04 host — which Intel's matrix flags as Desktop-only. Canonical
ships the same `6.17` HWE kernel series for Server through `linux-generic-hwe-24.04`, and that Server + HWE 6.17 surface is the
approved path — but it is *unverified in place*, so installation stays fail-closed until the checklist below PASSes on physical
hardware. Recording:

- `roles/intel_gpu/defaults/main.yml` carries `intel_gpu_stack_status: pre_verification_fail_closed`, the
  `intel_gpu_support_decision`, the research date (`intel_gpu_support_research_as_of: 2026-08-27`), source list, and the
  `intel_gpu_verification_checklist`.
- The role's first task is a hard `ansible.builtin.fail` before any mutation when `intel_gpu_install_enabled` is true. There is
  no manual approval boolean that bypasses this boundary, and no partial APT dependency closure or mismatched direct
  compute-runtime artifact set is committed or installed.
- This repository does not infer B65 support from B50/B60/B580 results.

Verifiable pre-commission checklist (must PASS in place on each host):

1. Ubuntu point release >= 24.04.4, proven via the `base-files` package.
2. Running kernel >= 6.17 from the 24.04 HWE series (`linux-generic-hwe-24.04`).
3. Both `8086:e222` devices enumerated in `hardware_inventory` and correlated by PCI BDF.
4. BDF-correlated hardware classification PASS on non-simulated evidence.
5. Level Zero / PyTorch XPU report exactly the expected two-device contract with per-device tensor operations PASS.

Until that checklist PASSes, every runtime result remains `NOT_TESTED`. This gate applies identically to both hosts
(`ai-p620-01` and `ai-5820-01`); neither hardware profile relaxes it. The `intel_gpu_stack_status` check is also listed as a
blocking, always-applied check in `policies/validation.yml` and in the validation aggregator's `REQUIRED_CHECKS_SPEC`, where
absent physical input renders it `NOT_TESTED`, keeping fleet validation honest.

## Pinned PyTorch staging

PyTorch is staged as CPython 3.12 and `torch==2.12.1+xpu`. Its complete 33-package dependency closure was resolved from the
official PyTorch XPU and PyPI indexes on 2026-08-17, with every distribution pinned and SHA-256 protected. Ansible installs
that lock with `--require-hashes`. The validator requires exactly two devices, records device names and memory, and runs
allocation, addition, synchronization, and result verification on each device. Only after PASS does Ansible atomically promote
the versioned virtual environment and preserve `previous`. PASS does not grant commissioning acceptance; the separate
commissioning workflow owns that decision.

The OMIX 0.3.0 repository metadata and `intel-omix=0.3.0-9~24.04` were inspected. They are not presented as a production
closure: the OMIX package surface is Desktop-flagged, and no Server snapshot is committed until the checklist above PASSes.

## Primary sources

- https://dgpu-docs.intel.com/overview/supported-hardware/xe-driver-gpus.html (accessed 2026-08-27)
- https://dgpu-docs.intel.com/driver/client/overview.html
- https://dgpu-docs.intel.com/installation-guides/installing-omix.html (accessed 2026-08-27)
- https://dgpu-docs.intel.com/installation-guides/index.html (accessed 2026-08-27)
- https://ubuntu.com/kernel/docs/reference/hwe-kernels/ (accessed 2026-08-27)
- https://github.com/intel/compute-runtime/releases/tag/26.27.39122.11 (accessed 2026-08-17)
- https://docs.pytorch.org/docs/stable/notes/get_start_xpu.html (accessed 2026-08-17)
- https://download.pytorch.org/whl/xpu/torch/ (accessed 2026-08-17)

## Physical acceptance

Physical acceptance must prove both `e222` PCI devices, `/dev/dri` render nodes, Level Zero enumeration, approximately 32 GiB
per device, large/ReBAR state, negotiated PCIe topology, driver/runtime versions, and per-device PyTorch operations. Until
that occurs on the Precision 5820 with both B65 cards, results remain `NOT_TESTED` and the `pre_verification_fail_closed` gate
applies; once the checklist PASSes in place, the identical role converges both hosts.