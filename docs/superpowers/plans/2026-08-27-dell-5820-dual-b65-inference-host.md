# Dell Precision 5820 Dual-B65 Inference Host — Implementation Decision

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add the newly purchased **Dell Precision 5820 Tower** to the `homelab-ai` Ansible repo as a first-class
managed generation/inference host with the same fail-closed, evidence-emitting architecture as `ai-p620-01`. The 5820
becomes the dedicated dual-GPU (2x Intel Arc Pro B65) inference host; the P620 retains its current role.

**Architecture:** Identical to the existing repo contract. Git holds non-secret desired state; every host is described
by inventory + `host_vars`; expected hardware lives in `profiles/hardware/*.yml`; lifecycle and runtime state is emitted
as schema-validated evidence; secrets come only from Vault at runtime. The 5820 is added as a second member of
`ai_hosts` (production/inference/gpu/monitoring/cluster groups), reusing every role and playbook unchanged. All
host-specific expectations are generalized from single-host constants to **profile-driven resolution with P620
defaults preserved** so existing tests and behavior are not weakened.

**Tech Stack:** unchanged — ansible-core 2.17, Python 3.12, Ubuntu 24.04/systemd, Intel Level Zero/XPU,
PyTorch XPU, vLLM XPU (TP=1/TP=2), llama.cpp SYCL fallback, pytest/yamllint/ansible-lint/GitHub Actions, Vault AppRole.

---

## Decisions (locked)

1. **Hostname:** `ai-5820-01`. Parallel to `ai-p620-01`; follows the `node_metadata.hostname` convention.
2. **Inventory groups:** production, inference, gpu, monitoring, **cluster** (cluster with `enabled: false`,
   mirroring `ai-p620-01`). This preserves the multi-group contract asserted by `test_inventory.py`.
3. **Hardware profile:** `profiles/hardware/d5820_dual_b65.yml`, mirroring `p620_dual_b65.yml` schema.
   - `platform.manufacturer: Dell`, `product_family: Precision 5820 Tower`,
     `machine_type_model: "Precision 5820 Tower"` with `product_name_patterns: [Precision 5820]`.
     The classifier's `machine_model` check uses `expected_model in product_name`, so this must be a DMI
     product-name substring on the real machine.
   - `cpu`: Intel, patterns `Intel(R) Xeon(R) W-2123` / `Intel Xeon W-2123` / `W-2123`, `sockets_expected: 1`.
   - `gpu`: `count_expected: 2`, `approved_pci_devices` identical `8086:e222` Intel Arc Pro B65 (same source URL);
     `expected_models`: 2x Intel Arc Pro B65, `approximate: 32` GiB, `tolerance_gib: 4`.
   - `pcie.host_link`: `max_generation: 5` (card capability, informational) and
     `expected_negotiated_generation: 3` (the 5820/Xeon W-2123 platform floor, and the check's minimum).
     `width_expectations.desired_when_slot_supports: x16`, `allow_slot_limited_width: true`;
     `material_degradation.minimum_negotiated_to_slot_ratio: 0.5`, default severity blocking.
   - `firmware`: `above_4g_decoding.required: true` (blocking, undiscoverable -> not_tested, BIOS must confirm) and
     `resizable_bar.required: true` (blocking). These remain **manual BIOS checkpoints**; software cannot authoritatively
     confirm them (documented in docs/pcie.md and the commissioning runbook).
   - `memory: installed_gib.expected: 32`, `tolerance_gib: 4`, `out_of_tolerance_severity: warning`,
     classification `initial_commissioning`.
   - `discovery_fields`, `severity_rules`: same shape as P620, plus `unexpected_gpu_devices` added to the `warning`
     severity-rule list in both profiles.
4. **Storage:** OS on NVMe #1; second 512 GB NVMe mounted via the `storage` role for model/cache data under
   `/var/lib/local-ai/models` + `/var/lib/local-ai/cache` (paths the runtime roles already default to). No RAID. This
   is declared per-host in `host_vars/ai-5820-01.yml` only after physical NVMe identities are captured at commissioning.
5. **Runtime selection / multi-GPU:** unchanged mechanism — group `gpu.yml`/`inference.yml` runtime + model profiles stay
   `enabled: false` with `commissioning_required: true` and null pins. The 5820's intended multi-GPU path is
   **vLLM XPU with `tensor_parallel_size: 2`** (primary) and **llama.cpp SYCL** split fallback
   (`llama_cpp_sycl_dual_gpu_support_certified` stays `false` until proven on hardware). Nothing is enabled in this
   change; commissioning does that deliberately, per host, with evidence.
6. **64 GiB aggregate VRAM caveat:** the two B65 cards provide 2x32 GiB. This is a **multi-device memory pool**, not a
   single transparent 64 GiB device. Every doc touchpoint states this explicitly (README, architecture, intel-gpu,
   commissioning).
7. **Interim Quadro P4000:** handled by **honest generalization**, not special-casing. The classifier's GPU identity,
   count, memory, Level Zero, rebar, and link-health checks are scoped to the **approved accelerators declared in the
   selected hardware profile**. Any observed display/GPU device whose (vendor, device) PCI ID is not in the profile's
   `approved_pci_devices` is surfaced as a new `unexpected_gpu_devices` check at **warning** severity. With a P4000
   installed (2 B65 + P4000): `gpu_count`/model remain PASS on the approved pair, `unexpected_gpu_devices` is a warning
   FAIL -> classifier top-level `warning` (not blocking). This means physical commissioning is still driven honestly
   (the B65s must pass all blocking checks) while a leftover transitional card is loudly visible and must be removed
   before GPU-stack certification. The P4000 is never added to any profile.
8. **Intel GPU compute-stack gate:** unchanged fail-closed posture. `roles/intel_gpu` stays
   `unresolved_vendor_support_conflict` until Intel OMIX/Xe officially supports B65 on Ubuntu **Server** 24.04
   (current documentation covers Ubuntu Desktop 24.04.4 or Ubuntu 24.04 + 6.17 HWE). No apt mutation, no
   `ignore_errors`, no approval flag is added. `test_gpu_stack_contract.py` continues to enforce this. Final verdict
   is therefore `READY WITH DOCUMENTED MANUAL PREREQUISITES` (see Verdict).
9. **Benchmarking guardrails:** host_vars overrides for the 5820's 950 W PSU and ~200 W B65 TDP
   (`benchmarking_psu_capacity_watts: 950`, `benchmarking_gpu_tdp_watts: 200`); `system_base_power_watts` (250) and
   abort temp (90) P620 defaults stay. `run_benchmark.py` itself is unchanged (all values already arrive via argv).
10. **Validation policy decomposition:** `policies/validation.yml` keeps its current shape (policy vocabulary +
    reference-platform defaults — `test_data_contracts.py:242` continues to pass unchanged). Platform-specific expected
    **values** (cpu, machine_model, gpu_count/model/vram, pcie generation) are resolved from the selected hardware
    profile by the aggregator and classifier, never by editing policy for each host. This is additive (P620 behavior
    unchanged when no profile is supplied) and matches the policy's existing `profile_match` semantics for
    cpu_model/gpu_model.
11. **Baseline artifact (task §21):** no new role. The existing `hardware_inventory` + `hardware_validation` +
    `validation` interplay already produces `observed.json`, per-subsystem evidence (`hardware.json`, `pci.json`,
    `memory.json`, `storage.json`, `firmware.json`) and a schema-valid `validation.json`. The commissioning runbook
    snapshots these as the 5820's commissioning baseline in the evidence tree (path convention:
    `/var/lib/aihost/evidence/manual/<node>/<timestamp>/`).
12. **Monitoring:** unchanged (single peak GPU temp + reconciliation health via textfile bridge) — sufficient for a
    dual-GPU node and avoids new surface. Deferred per-GPU metrics stay deferred, documented in docs/observability.md.

---

## File map (changes)

- `inventory/production/hosts.yml` — add `ai-5820-01` to production/inference/gpu/monitoring/cluster.
- `inventory/production/host_vars/ai-5820-01.yml` — new: identity, `hardware_profile: d5820_dual_b65`,
  `os_tuning_profile: baseline`, node_roles/capabilities/features mirroring ai-p620-01, cluster disabled,
  benchmarking overrides (950 W / 200 W), `storage_mounts` (NVMe2 -> models/cache).
- `profiles/hardware/d5820_dual_b65.yml` — new profile (decision #3).
- `profiles/hardware/p620_dual_b65.yml` — add `unexpected_gpu_devices` to `severity_rules.warning` (policy doc only).
- `roles/hardware_validation/files/classify_hardware.py` — generalize to approved-accelerator scoping +
  `unexpected_gpu_devices` warning check; **P620 behavior unchanged for existing fixtures**.
- `roles/validation/files/aggregate_validation.py` — optional profile-driven expected values
  (`--hardware-profile-json` / `build_validation_document(..., hardware_profile_spec=...)`); REQUIRED_CHECKS_SPEC
  (P620 defaults) unchanged and still used when absent.
- `roles/validation/{defaults,tasks}/main.yml` — pass the resolved profile to the aggregator.
- `playbooks/reboot-verify.yml` — verify no P620-hardcoding (B65 `8086:e222` matching is already host-agnostic);
  only re-verify both hosts.
- `tests/` — additive updates (see Task 5) plus new hardware fixtures.
- `docs/` — README, architecture, commissioning runbook (5820 section), intel-gpu, pcie, numa, observability,
  operations; battery/VRAM caveat sentence at every GPU-memory touchpoint.

## Task 1: Inventory and host_vars

- [x] Add `ai-5820-01: {}` to each of production/inference/gpu/monitoring/cluster in `inventory/production/hosts.yml`.
- [x] Create `inventory/production/host_vars/ai-5820-01.yml` mirroring ai-p620-01 structure:
  `hardware_profile: d5820_dual_b65`, `os_tuning_profile: baseline`, same node_roles/capabilities/features, cluster
  block with `enabled: false`, benchmarking overrides, and commented `storage_mounts` scaffold to be completed with
  real NVMe identities at commissioning.

## Task 2: Hardware profile

- [x] Create `profiles/hardware/d5820_dual_b65.yml` per decision #3.
- [x] Add `unexpected_gpu_devices` to `p620_dual_b65.yml` `severity_rules.warning`.

## Task 3: Classifier generalization

- [x] In `classify_hardware.py`, derive `approved` set; compute `approved_gpus` from `observed["gpus"]`.
- [x] Scope `gpu_count`, `gpu_model_match`, `level_zero_detected`, `gpu_memory`, `resizable_bar_enabled`, and
      `pcie_link_health` to approved GPUs (missing approved BDF in `pci` still fails blocking).
- [x] Add `unexpected_gpu_devices` check (warning severity; FAIL when any observed GPU is outside
      `approved_pci_devices`; rationale states it must not remain in the certified design).
- [x] Confirm exit-code/status mapping unchanged: blocking -> 2, not_tested -> 3, else 0; warning-only -> 0.
- [x] Confirm `main()` evidence routing still emits `hardware.json`, `pci.json`, `memory.json`, `storage.json`,
      `firmware.json`.

## Task 4: Validation aggregation generalization

- [x] `aggregate_validation.py`: add `hardware_profile_spec` parameter to `build_validation_document` (None => today's
      behavior) derived from profile JSON via `--hardware-profile-json` (accept file path or inline JSON).
- [x] Validate roles/tasks pass profile content; add `validation_hardware_profile_path` default in role defaults.
- [x] Keep REQUIRED_CHECKS_SPEC byte-for-byte identical (P620 defaults).

## Task 5: Tests (additive, never weakened)

- [x] New fixtures: `tests/fixtures/hardware/d5820_healthy.json` (Dell "Precision 5820 Tower", W-2123, 2x B65,
      32 GiB, Gen3 x16 links, rebar true, level_zero 2x32) and `d5820_p4000.json` (same + 1x UNKNOWN display device,
      PCI family matching P4000 IDs).
- [x] `test_hardware_validation.py`: parametrize core fixture loop over both profiles; add
      `test_unexpected_gpu_warns_but_does_not_block` (top-level `warning`, `physical_acceptance` false, approved
      pair checks pass, `unexpected_gpu_devices` fail-warning).
- [x] `test_inventory.py`: assert both hosts in each production group; per-host host_vars checks; CHANGE_ME count
      updated to per-host-file assertions (2 total in inventory output).
- [x] `test_data_contracts.py`: iterate both `profiles/hardware/*_dual_b65.yml` for profile-contract assertions;
      keep line-242 policy assertion unchanged.
- [x] `test_validation_aggregation.py`: keep P620 tests; add a D5820 profile-spec test asserting derived expected
      values (W-2123 pattern, "Precision 5820 Tower", count 2, vram 32.0, Gen3).
- [x] Run `make quality` and confirm all pre-existing tests still pass with zero assertion removals.

## Task 6: Documentation

- [x] README: node table + "supported host profile" for both; aggregate-64 GiB-VRAM caveat sentence at GPU memory
      descriptions; keep "future host" topic.
- [x] docs/architecture.md: add 5820 block (Xeon W-2123, single-socket, PCIe3 x16 per B65, 32 GiB, 2x NVMe, 950 W);
      state P620 stays the reference/validation host; VRAM caveat sentence.
- [x] docs/commissioning.md: add a 5820 runbook mirroring the P620 18-step structure — manual BIOS checkpoint
      (Above 4G/ReBAR/IOMMU), 950 W PSU verification, 10-pin->dual-8-pin power-harness verification (task
      §12/§13/§20), NVMe identity capture before `storage_mounts` is finalized, P4000-removal gate before GPU-stack
      certification, baseline artifact snapshot, aggregate-VRAM caveat.
- [x] docs/intel-gpu.md: note both hosts target B65 `8086:e222`; the Ubuntu-Server support-window gate is unchanged
      and applies to the new host too.
- [x] docs/pcie.md: add 5820 row — Gen3 expected platform link (never fault), Gen5 card capability, Gen3 floor check;
      ReBAR/Above-4G manual path identical.
- [x] docs/numa.md: add single-socket note for the 5820 (no NUMA split; `numa_topology` check still applies).
- [x] docs/observability.md: note the workaround-free single-peak-temp metric covers both GPUs; per-GPU metrics remain
      deferred.
- [x] docs/operations.md: mention the two hosts converge through the same playbooks.

## Task 7: Gate and report

- [x] `make quality` (yamllint + ansible-lint + full pytest), `make tuning-idempotency`, `ansible-playbook
      --syntax-check` across all `Makefile` PLAYBOOKS.
- [x] Review `git diff` for scope, secrets, and unintended weakening.
- [x] Produce final report: Repository changes / Architecture / Hardware validation / GPU stack / Inference runtime /
      Tests / Idempotency / Remaining manual actions / Unknowns / **one** verdict.

## Verdict (target)

`READY WITH DOCUMENTED MANUAL PREREQUISITES` — all repository-side software validation for a second host passes in
sandbox/simulated runs (a pure-inventory change is idempotent by construction and does not need physical hardware);
the Intel OMIX Ubuntu-Server B65 support gap, the manual BIOS/PSU/harness checkpoints, and the final physical
acceptance are explicit documented manual prerequisites that hardware commissioning performs in order, exactly as
`docs/intel-gpu.md` and the 5820 commissioning runbook specify. Not `READY FOR HARDWARE DEPLOYMENT` because
software-controlled GPU acceptance (Level Zero/PyTorch -XPU/vLLM) remains intentionally fail-closed until the vendor
support conflict is resolved, and not `NOT READY` because no repository-side critical validation is knowingly broken
and every gate is satisfied by the change itself.