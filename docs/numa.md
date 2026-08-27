# NUMA Discovery and Tuning

Priority area for the P620: the Threadripper PRO 3945WX (WRX80) exposes multiple
NUMA nodes, and GPU-to-node locality can materially affect model-load time and
token throughput when host-side copies dominate.

The Precision 5820 (`ai-5820-01`) is a single-socket Xeon (W-2123) platform and
presents a single NUMA node; GPU-to-node locality concerns are materially reduced
there, but the same per-device sysfs proximity discovery applies and no locality
is assumed for either host. The `d5820_dual_b65` profile shares the same
NUMA/PCIe discovery and tuning switches.

## Discovery (always on)

Every convergence, drift-check, and validation run collects:

- `numactl --hardware`: node count, CPU map per node, per-node memory/free
- `lscpu -j -e=CPU,NODE,SOCKET,CORE,ONLINE`: CPU-to-node mapping
- `/sys/devices/system/node/node*/meminfo`: per-node MemTotal
- `/sys/bus/pci/devices/*/numa_node` + `local_cpulist` for display-class PCI
  devices: **GPU-to-node proximity**
- IOMMU/PCI-root context from the hardware collector (`pcie.json`, `iommu`)

Output lands in `numa.json` inside each evidence run directory. Missing
optional sources are recorded as unavailable with a reason; nothing is
fabricated. The role also persists a topology fingerprint; unexpected topology
changes surface as a FAIL on the `numa_topology` validation check.

## Experiment classes

The benchmark harness accepts placement controls via environment:

```bash
# default scheduler/memory placement (reference)
scripts/run-ansible-snapshot ... --playbook benchmark.yml ...

# CPU binding experiment (example: pin to node0 CPUs once topology is known)
AIHOST_BENCH_CPU_AFFINITY=... benchmark run

# memory binding / interleave experiments
AIHOST_BENCH_MEMBIND_NODES=0 ...
```

These knobs exist for controlled comparison runs only.

## What is deliberately NOT done by default

- No global NUMA binding is enforced (`runtime_binding_enabled: false` in every
  shipped profile).
- No assumption is made that both B65 GPUs share locality — proximity is read
  from sysfs per device.
- Binding enforcement requires `os_tuning_numa_binding_certified=true`, which
  stays false until topology-aware benchmark comparisons on the real machine
  justify it (policies/tuning.yml promotion criteria).

## Workflow

1. Commission each node; capture the baseline `numa.json` (both `ai-p620-01` and `ai-5820-01`).
2. Benchmark reference runs (default placement).
3. Create a candidate profile enabling one binding mode; certify the flag in
   inventory for the test window; converge; benchmark identical profiles.
4. Evaluate per docs/tuning.md section 8; promote or reject.
