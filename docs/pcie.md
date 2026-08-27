# PCIe Validation and Benchmarking

The P620 platform is PCIe 4.0; the Arc Pro B65 cards are Gen5-capable. **Gen4
negotiated links are the expected maximum on this host and are never reported
as faults.**

The Precision 5820 (`ai-5820-01`, profile `d5820_dual_b65.yml`) is a Gen3
platform: **Gen3 x16 negotiated links are the expected maximum there.** The B65
report peak Gen5 capability (`host_link.max_generation: 5`) and the 5820 root
complex may advertise Gen5, but the physical C422 (LGA2066) topology negotiates
Gen3; `expected_negotiated_generation: 3` and `allow_slot_limited_width: true`
encode this. A Gen5-capable integer in sysfs must therefore be evaluated against
the platform's real physical generation, not treated as a degradation. Reported
link width/generation below Gen3 x16 remains classifiable as degraded.

## What is captured per GPU (hardware collector -> pci.json)

- PCI domain/bus/device/function (`bdf`)
- negotiated link generation + width, device maximum generation + width
- physical slot width (dmidecode slot type) — width is judged per-slot, so an
  x8 card in a physically x8 slot is not a defect while an x16 slot running x4
  is classified as degraded
- BAR sizes; Resizable BAR current size (ReBAR enabled when >= 16 GiB)
- AER error counters (`aer_dev_correctable/fatal/nonfatal`) where exposed
- kernel driver binding

## Host IOMMU state (hardware collector -> hardware.json `iommu`)

- `/sys/kernel/iommu_groups` population
- DMAR/IOMMU devices under `/sys/class/iommu`
- `intel_iommu=` / `iommu.pt=` boot flags from `/proc/cmdline`

## Classification

Severity rules live in `roles/hardware_validation/files/classify_hardware.py`:

| Condition | Severity |
|---|---|
| GPU count/model mismatch | blocking |
| Missing ReBAR (required by profile) | blocking |
| Negotiated width below the GPU's actual slot capability | blocking |
| Negotiated generation below host maximum (unexpected degradation) | warning/blocking |
| Above-4G decoding state not exposed by Linux | informational |

Tuning-profile `pcie.validate_*` switches let a candidate declare which checks
apply during experiments (all default true and stay true).

## Bandwidth and P2P benchmarking

- An optional host-to-device bandwidth benchmark class may be added to
  `benchmarking_profiles`; it must record transfer rate with the same tuning
  provenance block as every other class.
- Peer-to-peer between the two B65s is **detected, never assumed**: capability
  probes run only on real hardware through Level Zero device queries, and the
  result is recorded (supported/unsupported/unavailable) in evidence. Absence
  of P2P support is informational; claiming it without a successful measured
  transfer is prohibited.

Nothing in this area can be verified until the real GPUs are present; all such
probes report NOT_TESTED today.
