# Intel Arc Pro B65 and PyTorch XPU

Status: **NOT_TESTED on physical hardware** and disabled until commissioning approves the pinned compatibility set.

As accessed on 2026-08-17, Intel's generic supported-hardware table identifies Arc Pro B65 as PCI ID `8086:e222` and lists
full support on Ubuntu 25.10/kernel 6.17. More specifically, Intel's OMIX installation guide names B65 and supports Ubuntu
Desktop 24.04.4 or Ubuntu 24.04 with the 6.17 HWE kernel. The role therefore requires Ubuntu 24.04.4+, kernel 6.17+, and an
conflicting support statements. The host stack therefore has the explicit state `unresolved_vendor_support_conflict` and
installation fails unconditionally before mutation. There is no manual approval boolean that bypasses this boundary. This
repository does not infer B65 support from B50/B60/B580 results.

The OMIX 0.3.0 repository metadata and `intel-omix=0.3.0-9~24.04` were inspected, but are not presented as a supported
production closure because of that conflict. No partial APT dependency closure or mismatched direct compute-runtime
artifact set is committed or installed. Resolving this requires Intel to provide a coherent B65 host support statement
and an immutable full dependency snapshot suitable for the selected Ubuntu installation.

PyTorch is staged as CPython 3.12 and `torch==2.12.1+xpu`. Its complete 33-package dependency closure was resolved from
the official PyTorch XPU and PyPI indexes on 2026-08-17, with every distribution pinned and SHA-256 protected. Ansible
installs that lock with `--require-hashes`. The validator requires exactly two devices,
records device names and memory, and runs allocation, addition, synchronization, and result verification on each device.
Only after PASS does Ansible atomically promote the versioned virtual environment and preserve `previous`. PASS does not
grant commissioning acceptance; the separate commissioning workflow owns that decision.

Primary sources (accessed 2026-08-17):

- https://dgpu-docs.intel.com/overview/supported-hardware/xe-driver-gpus.html
- https://dgpu-docs.intel.com/driver/client/overview.html
- https://dgpu-docs.intel.com/installation-guides/installing-omix.html
- https://github.com/intel/compute-runtime/releases/tag/26.27.39122.11
- https://docs.pytorch.org/docs/stable/notes/get_start_xpu.html
- https://download.pytorch.org/whl/xpu/torch/

Physical acceptance must prove both `e222` PCI devices, `/dev/dri` render nodes, Level Zero enumeration, approximately
32 GiB per device, large/ReBAR state, negotiated PCIe topology, driver/runtime versions, and per-device PyTorch operations.
Until that occurs on the P620 with both B65 cards, every such result remains `NOT_TESTED`.
