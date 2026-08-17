# Intel Arc Pro B65 and PyTorch XPU

Status: **NOT_TESTED on physical hardware** and disabled until commissioning approves the pinned compatibility set.

As accessed on 2026-08-17, Intel's generic supported-hardware table identifies Arc Pro B65 as PCI ID `8086:e222` and lists
full support on Ubuntu 25.10/kernel 6.17. More specifically, Intel's OMIX installation guide names B65 and supports Ubuntu
Desktop 24.04.4 or Ubuntu 24.04 with the 6.17 HWE kernel. The role therefore requires Ubuntu 24.04.4+, kernel 6.17+, and an
explicit Git-controlled compatibility approval. Installation is disabled by default and fails before mutation if any gate
is absent. This repository does not infer B65 support from B50/B60/B580 results.

The supported installation route is the exact Intel OMIX 0.3.0 repository and `intel-omix=0.3.0-9~24.04`. Intel describes
that runtime package as the validated driver/library set required for PyTorch. It is not the full oneAPI toolkit and the
role does not install `intel-omix-dev`, media, debugging, or development metapackages. The repository key is pinned by file
SHA-256 and primary fingerprint before APT use. Upstream compute-runtime 26.27.39122.11 artifact hashes remain recorded as
component provenance, but Ansible installs the vendor-validated OMIX dependency set rather than mixing releases.

PyTorch is staged as CPython 3.12 and `torch==2.12.1+xpu`, using the official XPU wheel URL and index-published SHA-256.
Installation uses `--no-deps` specifically to prevent unpinned transitive dependency mutation; therefore commissioning
must replace this scaffold with a complete hash lock before enabling it. The validator requires exactly two devices,
records device names and memory, and runs allocation, addition, synchronization, and result verification on each device.
Only after PASS does Ansible promote the versioned virtual environment through the `current` symlink. PASS still does not
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
