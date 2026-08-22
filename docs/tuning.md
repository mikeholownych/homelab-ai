# OS Tuning Framework

Evidence-driven OS optimization for the P620 + dual Arc Pro B65 workstation.
The framework makes tuning **versioned, reproducible, benchmarkable, reversible,
and promotable only when measured evidence justifies it**.

## 1. Why the repository starts from a conservative baseline

The `baseline` profile (`profiles/tuning/baseline.yml`) manages nothing that
Ubuntu 24.04 and the supported Intel stack do not already do well. Generic
"Linux performance tuning" advice (THP always, swappiness 10, performance
governor, disabled C-states) is frequently wrong for inference workloads with
large device-resident models, and each change carries power, thermal, or
latency-jitter risk. The baseline exists to:

- record untouched distro behavior as the reference point,
- make every future comparison attributable to exactly one change,
- prove the collection/validation machinery before any mutation is allowed.

The first real benchmark run on the P620 must establish this untouched baseline.
**No candidate may be promoted before that evidence exists.**

## 2. How tuning candidates are created

1. Copy `profiles/tuning/baseline.yml` to a new file, e.g.
   `profiles/tuning/inference_candidate_03.yml`.
2. Change **one subsystem** (governor, or THP mode, or one sysctl group). Never
   bundle multiple experiments into one candidate.
3. Set metadata: `state: candidate`, `revision: rN` (bump it), a precise
   `description`, and `parent_baseline: <profile>`.
4. Commit. The Git commit is the authorization point for converging the host
   with the candidate.

Profile structure is enforced by `schemas/os-tuning.schema.json`; every profile
file must validate against it (checked in CI).

## 3. How to benchmark one change at a time

```bash
# 1. Converge onto the candidate explicitly (never leave a candidate selected)
.venv/bin/ansible-playbook playbooks/site.yml --limit ai-p620-01 \
  -e "os_tuning_profile=inference_candidate_01"

# 2. Benchmark (repeat >= policies/tuning.yml promotion.criteria.min_runs_per_profile)
scripts/run-ansible-snapshot --repo-root "$PWD" --schema-root "$PWD/schemas" \
  --inventory inventory/production/hosts.yml --target ai-p620-01 \
  --playbook benchmark.yml --lock-root /run/lock/aihost

# 3. Reconverge back onto the authoritative baseline
.venv/bin/ansible-playbook playbooks/site.yml --limit ai-p620-01
```

Every benchmark document records the live governor/EPP/THP/hugepages/sysctl/
scheduler/kernel state captured at run time (`os_tuning` block), so results can
never be misattributed to a different configuration than the one that produced
them.

## 4. How NUMA testing works

See `docs/numa.md`. Discovery runs on every convergence and emits `numa.json`
(node map, CPU map, per-node memory, GPU-to-node proximity). Binding policies
are workload-level experiment knobs behind `numa.runtime_binding_enabled` plus
the `os_tuning_numa_binding_certified` gate; nothing binds globally by default.

## 5. How THP/HugeTLB experiments work

- THP: `transparent_hugepages.enabled` accepts `default` (manage nothing),
  `always`, `madvise`, `never`. Runtime sysfs is corrected on drift; boot
  persistence uses the `95-aihost-tuning.cfg` GRUB drop-in. Candidate 02 tests
  THP `always` against the recorded distro default.
- HugeTLB: fully opt-in (`hugepages.enabled: false` everywhere today). The role
  refuses reservations exceeding `os_tuning_hugepages_max_host_memory_pct`
  (25%) of observed RAM, configures size via boot parameters, count via
  `vm.nr_hugepages`, and validates `/proc/meminfo` counters afterwards.
- Rollback for both: reconverge the previous profile; reboot persistence of the
  removal is verified by validation after the next reboot.

## 6. How CPU power/governor tests work

Candidate 01 tests `performance` + `balance_performance`. Enforcement goes
through an idempotent helper that writes `scaling_governor` /
`energy_performance_preference` per CPU; the same helper backs the
`aihost-cpu-power.service` boot-time unit and the `--validate` probe used by
convergence. C-states are never disabled by default (`cstate_policy: null`);
any `disable_deep` candidate must additionally record power impact and
performance-per-watt comparisons in its evidence refs.

Firmware power profiles (Lenovo platform modes) are discovered read-only from
`/sys/firmware/acpi/platform_profile*` and recorded in `cpu-power.json`. The
role never changes firmware modes automatically.

## 7. How PCIe topology is validated

See `docs/pcie.md`. Per GPU: negotiated/max generation and width, slot width,
BAR sizes, ReBAR state, AER counters, plus host IOMMU state. Gen4 links are the
expected maximum on this WRX80 host and are not faults; degraded widths are
classified by `hardware_validation`.

## 8. How candidate results are evaluated

Compare benchmark documents across candidate and parent-baseline runs:

| Criterion | Default threshold |
|---|---|
| Runs per side | >= 3 |
| Generation throughput | >= +3% mean improvement |
| TTFT | no more than -5% regression |
| Power | <= +5% increase |
| GPU temperature | <= +3 C increase |
| Correctness | zero regressions |
| Stability / reboot persistence / soak | required |

Record standard deviation for both sides; improvements inside the combined
run-to-run spread are noise, not wins. Single-node samples are small — document
that limitation when reporting.

## 9. How a candidate becomes baseline

1. All criteria above pass with evidence refs recorded in the profile.
2. Change the profile's `state:` to `accepted` and commit.
3. Change `os_tuning_profile:` in inventory to the accepted profile and commit
   (this is the promotion point; scheduled reconciliation now enforces it).
4. Converge, then verify via `validate.yml` active-state checks.

## 10. How a candidate is rejected and reverted

Set `state: rejected` keeping its `benchmark_refs`, reconverge the previous
baseline profile, and confirm rollback through validation checks. Rejected
profiles stay in Git as part of the experimental record.

## 11. When kernel-version experimentation is justified

Only when a specific supported kernel (HWE/OEM/candidate) demonstrably fixes a
problem affecting this workload — e.g. Xe-driver fixes present upstream but not
in the running series. Pin the exact release in `kernel.expected_release`,
retain the previous kernel package, and require post-reboot hardware/XPU/
inference validation. Never track "newest".

## 12. When a custom kernel is justified

Only concrete blockers qualify:

- required Xe-driver functionality/fix unavailable in any supported Ubuntu kernel
- demonstrated scheduler/NUMA defect affecting the workload
- required memory-management patch
- low-latency requirement not satisfiable through supported configuration
- critical bug fix unavailable through vendor-supported streams
- measured gain large enough to justify maintaining a private kernel

A small synthetic benchmark improvement alone is insufficient. Full trigger
policy lives in `policies/tuning.yml` under `kernel_experiments`.

## 13. How a custom kernel would be built reproducibly

See `docs/custom-kernel.md` and `kernel/README.md`: pinned upstream version +
checksum, versioned config, numbered patch series, containerized pinned
toolchain, checksummed `.deb` artifacts deployed only by Ansible after the
certification gate. Kernels are never built interactively on the P620.

## 14. How scheduled reconciliation enforces the selected profile

Scheduled runs execute `site.yml`, which includes `os_tuning` for hosts with
`features.os_tuning: true`. Manual changes to managed values are reverted:
sysctl drop-in keys, THP runtime mode, governor/EPP (via the idempotent helper
plus boot service), NVMe scheduler/readahead (udev + runtime), and GRUB-managed
parameters. Kernel drift is special-cased: a running-kernel mismatch against
`expected_release` fails closed and blocks dependent convergence instead of
attempting automatic kernel rollback; unexpected NUMA/GPU topology changes are
reported through the `numa_topology` validation check.
