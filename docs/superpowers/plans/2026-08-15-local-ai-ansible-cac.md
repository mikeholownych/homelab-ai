# Local AI Ansible Configuration-as-Code Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a production-quality Ansible repository that reproducibly manages the P620 AI workstation from Ubuntu 24.04 onward and scales to a future fleet.

**Architecture:** Git contains non-secret desired state, Ansible converges and validates deployed snapshots, and HashiCorp Vault supplies secrets at runtime. Host-native hardware support is combined with isolated pinned inference environments; every lifecycle operation emits evidence and fails closed on blocking validation.

**Tech Stack:** ansible-core 2.17, Python 3.12, YAML/JSON Schema, HashiCorp Vault AppRole, Ubuntu 24.04/systemd, Intel Level Zero/XPU, PyTorch XPU, vLLM XPU, llama.cpp SYCL, pytest, ansible-lint, yamllint, GitHub Actions.

---

## File map

- Root configuration: `ansible.cfg`, `requirements.yml`, `requirements.txt`, `Makefile`, lint configuration, `.gitignore`, and CI define reproducible operator tooling.
- `inventory/{production,lab}/` owns node identity and environment overrides.
- `profiles/hardware/` and `policies/` own expected hardware and lifecycle rules.
- `playbooks/` are stable operator entry points; role implementation stays under `roles/`.
- `schemas/` defines evidence, validation, benchmark, CMDB, and ITSM contracts.
- `scripts/` contains locked-run orchestration, evidence finalization, and repository policy checks.
- `tests/` contains contract, schema, fixture, and localhost-safe convergence tests.
- `docs/` contains operator procedures and explicit hardware acceptance boundaries.

## Task 1: Repository contracts and test-first foundation

**Files:**

- Create: `.gitignore`, `.yamllint`, `.ansible-lint`, `ansible.cfg`, `requirements.yml`, `requirements.txt`, `Makefile`
- Create: `tests/test_repository_contract.py`, `tests/test_no_secrets.py`, `tests/fixtures/inventory/healthy.yml`
- Create: `.github/workflows/quality.yml`, `evidence/.gitkeep`

- [ ] **Step 1: Write repository contract tests first**

Create tests that enumerate every required playbook and role, assert `evidence/*` is ignored except `.gitkeep`, reject files matching `$ANSIBLE_VAULT`, and reject `latest`, `curl ... | sh`, blanket `ignore_errors`, or committed AppRole secret IDs. Use `Path.rglob` and explicit allowlists so violations name the file.

```python
def test_required_roles_exist(repo):
    required = {"base_os", "security", "users", "ssh", "time_sync", "storage",
                "networking", "hardware_inventory", "hardware_validation", "intel_gpu",
                "container_runtime", "pytorch_xpu", "vllm_xpu", "llama_cpp_sycl",
                "monitoring", "scheduled_ansible", "vault_integration", "validation",
                "benchmarking", "cmdb_export", "itsm_hooks"}
    assert required <= {path.name for path in (repo / "roles").iterdir() if path.is_dir()}
```

- [ ] **Step 2: Run the tests and confirm the expected missing-structure failure**

Run: `python3 -m pytest tests/test_repository_contract.py -q`

Expected: FAIL listing missing root files, playbooks, and roles.

- [ ] **Step 3: Add pinned tooling and root configuration**

Pin Python dependencies with exact versions and hashes in `requirements.txt`; pin Ansible Galaxy collections in `requirements.yml`. Configure inventory, YAML callback output, retry-file suppression, interpreter discovery, privilege escalation, and fact caching without logging secrets. `Makefile` targets: `bootstrap-tools`, `lint`, `syntax`, `test`, `check`, `idempotency`, and `quality`.

- [ ] **Step 4: Add role/playbook directory contracts and CI**

Create all role `defaults/main.yml`, `tasks/main.yml`, `handlers/main.yml`, and `meta/main.yml` files required by the contract. Add every required playbook with valid empty-role-safe structure. CI installs pinned dependencies and runs `make quality`; it never runs physical acceptance fixtures as real validation.

- [ ] **Step 5: Run foundation gates**

Run: `make lint test syntax`

Expected: PASS; fixture-dependent tests report simulation, not host success.

- [ ] **Step 6: Commit**

```bash
git add .github .gitignore .yamllint .ansible-lint ansible.cfg requirements.yml requirements.txt Makefile evidence tests playbooks roles
git commit -m "chore: establish Ansible repository contracts"
```

## Task 2: Inventory, hardware profile, policies, and schemas

**Files:**

- Create: `inventory/production/hosts.yml`, `inventory/production/group_vars/{all,inference,gpu,cluster,monitoring}.yml`
- Create: `inventory/production/host_vars/ai-p620-01.yml`, `inventory/lab/hosts.yml`
- Create: `profiles/hardware/p620_dual_b65.yml`, `policies/{patching,upgrades,drift,validation}.yml`
- Create: `schemas/{validation,evidence,benchmark,cmdb,itsm}.schema.json`
- Create: `tests/test_data_contracts.py`, `tests/test_inventory.py`

- [ ] **Step 1: Write failing inventory and schema tests**

Assert the production host has the requested roles/capabilities/features, hardware profile resolves, tags are never used as identity fields, every lifecycle component has `current`, `candidate`, and `previous_known_good`, and all sample documents validate with `jsonschema`.

```python
def test_first_node_is_fleet_shaped(production_host):
    assert production_host["hardware_profile"] == "p620_dual_b65"
    assert set(production_host["node_roles"]) == {"inference", "gpu"}
    assert production_host["features"]["clustering"] is False
    assert production_host["cluster"]["enabled"] is False
```

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_inventory.py tests/test_data_contracts.py -q`

Expected: FAIL because inventory, policies, and schemas do not exist.

- [ ] **Step 3: Implement inventory and expected hardware data**

Use `CHANGE_ME` only for the pre-commissioning `ansible_host` address and document it as an intentional operator input. Define expected model `30E1S7NJ00`, CPU substring `AMD Ryzen Threadripper PRO 3945WX`, two B65 GPUs, 32 GiB VRAM with tolerance, PCIe Gen4 maximum and topology-aware width rules, ReBAR requirement, 48 GiB initial RAM, and discovered-only DIMM/NVMe/NIC/firmware/PSU fields.

- [ ] **Step 4: Implement lifecycle policies and strict schemas**

Schemas set `additionalProperties: false` on stable contracts, require `simulated`, timestamps, Git SHA, status enums, and expected/observed separation. Policies explicitly separate routine packages from kernel, GPU, Level Zero, Python runtimes, llama.cpp, and firmware.

- [ ] **Step 5: Verify GREEN and commit**

Run: `pytest tests/test_inventory.py tests/test_data_contracts.py -q && ansible-inventory --list >/dev/null`

Expected: PASS.

```bash
git add inventory profiles policies schemas tests
git commit -m "feat: define fleet inventory and lifecycle contracts"
```

## Task 3: Evidence framework and normalized command runner

**Files:**

- Create: `roles/evidence/{defaults,tasks,templates}/...`
- Create: `scripts/finalize-evidence.py`, `scripts/run-ansible-snapshot`
- Create: `tests/test_finalize_evidence.py`, `tests/test_run_wrapper.py`

- [ ] **Step 1: Write failing evidence tests**

Test UTC directory naming, atomic JSON writes, incomplete failure manifests, SHA256 coverage, recap parsing, Git SHA capture, inventory target capture, and refusal to run when the deployed tree is dirty or the lock is held.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_finalize_evidence.py tests/test_run_wrapper.py -q`

Expected: FAIL because the scripts are absent.

- [ ] **Step 3: Implement evidence finalization**

The Python finalizer accepts a run directory, validates JSON files against repository schemas, writes `SHA256SUMS` atomically, and updates `manifest.json` with `complete`, recap counts, and final classification. It never prints document values that may contain secrets.

- [ ] **Step 4: Implement the locked snapshot wrapper**

Use `flock --nonblock`, an explicit repository root, an explicit inventory path, and an allowlist of playbook names. Capture `git rev-parse HEAD`, reject a dirty snapshot, set the evidence directory, run `ansible-playbook`, finalize evidence even after failure, and propagate the Ansible exit code. The wrapper performs no `git fetch`, `pull`, or checkout.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_finalize_evidence.py tests/test_run_wrapper.py -q`

Expected: PASS including lock-contention and failed-run preservation tests.

```bash
git add roles/evidence scripts tests
git commit -m "feat: add durable locked run evidence"
```

## Task 4: Ubuntu baseline and practical security

**Files:**

- Modify: `roles/{base_os,time_sync,storage,networking,users,ssh,security}/**`
- Create: role templates for apt sources/preferences, journald, logrotate, sysctl, sshd, sudoers, nftables/UFW, and audit rules
- Modify: `playbooks/{bootstrap,baseline,site}.yml`
- Create: `tests/test_baseline_contract.py`, `tests/integration/baseline.yml`

- [ ] **Step 1: Write failing baseline contract tests**

Assert Ubuntu 24.04 guards, locale/timezone/time sync, pinned-package preferences, unattended-upgrade disablement, journald/logrotate/sysctl configuration, SSH key proof gate, sudo validation, firewall rules, service account shells/groups, secure modes, and absence of shell when modules exist.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_baseline_contract.py -q`

Expected: FAIL on missing baseline behavior.

- [ ] **Step 3: Implement idempotent baseline roles**

Use `deb822_repository`, `apt`, `package_facts`, `locale_gen`, `timezone`, `systemd_service`, `sysctl`, `template`, `user`, `authorized_key`, `lineinfile`, `ufw`, and validated `copy/template` modules. Disable periodic unattended mutation and hold only policy-selected kernel/GPU/runtime packages. Handlers restart only affected services.

- [ ] **Step 4: Implement SSH proof and security compatibility notes**

Disable passwords only after an assertion confirms a managed public key exists for an allowed operator. Document firewall API exposure, render-node group access, systemd device restrictions, locked-memory limits, and audit overhead.

- [ ] **Step 5: Run lint, check mode, and idempotency fixture**

Run: `make lint syntax && ansible-playbook tests/integration/baseline.yml --check`

Expected: PASS. On a disposable Ubuntu 24.04 runner, two real baseline runs must show `changed=0` on the second run.

- [ ] **Step 6: Commit**

```bash
git add roles playbooks tests docs
git commit -m "feat: converge Ubuntu baseline and host security"
```

## Task 5: Vault runtime integration

**Files:**

- Modify: `roles/vault_integration/**`, `playbooks/bootstrap.yml`, `playbooks/site.yml`
- Create: `roles/vault_integration/templates/vault-agent.env.j2`
- Create: `docs/vault.md`, `tests/test_vault_contract.py`

- [ ] **Step 1: Write failing fail-closed Vault tests**

Assert AppRole inputs come only from protected runtime paths or systemd credentials, token lifetime is bounded, secret lookups use `no_log: true`, logical paths are versioned, missing Vault access fails, and no role contains plaintext fallback values.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_vault_contract.py -q`

Expected: FAIL because the role interface is incomplete.

- [ ] **Step 3: Implement replaceable authentication and lookup interface**

Use `community.hashi_vault.vault_login` for AppRole token exchange and `vault_kv2_get` for task-time reads. Validate URL/TLS/mount/path inputs, keep returned data in `no_log` blocks, avoid cacheable facts, and assert required keys. Auth method dispatch accepts only a documented allowlist.

- [ ] **Step 4: Document out-of-band scheduled credentials**

Document Vault policy examples scoped to `secret/data/local-ai/...`, response wrapping for initial SecretID delivery, root-only installation, systemd `LoadCredential=`, rotation, revocation, TLS trust, and recovery. Explicitly prohibit root tokens and Ansible Vault.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_vault_contract.py -q && make lint syntax`

Expected: PASS.

```bash
git add roles/vault_integration playbooks docs/vault.md tests
git commit -m "feat: retrieve secrets from Vault at runtime"
```

## Task 6: Hardware discovery and severity-based validation

**Files:**

- Modify: `roles/hardware_inventory/**`, `roles/hardware_validation/**`
- Create: `roles/hardware_inventory/files/collect_hardware.py`
- Create: `tests/fixtures/hardware/{healthy,gpu_count,rebar_missing,level_zero_missing,pcie_degraded}.json`
- Create: `tests/test_hardware_validation.py`

- [ ] **Step 1: Write failing fixture tests**

Healthy simulated facts must pass. GPU count/model, required ReBAR, missing Level Zero, and materially degraded topology must block. Unknown PSU data must remain informational. Width evaluation must compare each GPU with its observed physical slot capability.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_hardware_validation.py -q`

Expected: FAIL because collector and classifier are absent.

- [ ] **Step 3: Implement collection without mutation**

Collect DMI, CPU, memory/DIMM, NVMe, NIC, BIOS/firmware, serial/asset, PCI device IDs/link capability/link status/BAR sizes, and discoverable PSU data. Commands such as `lspci`, `dmidecode`, `lsmem`, `lsblk`, `ip -json`, and `fwupdmgr` are read-only, use `changed_when: false`, and fail explicitly when a required source is unavailable.

- [ ] **Step 4: Implement pure classification and evidence output**

Keep the comparison logic in a testable Python module. Emit `hardware.json`, `pci.json`, `memory.json`, `storage.json`, and `firmware.json`, with expected, observed, severity, status, rationale, and `simulated` fields.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_hardware_validation.py -q && make lint syntax`

Expected: PASS for healthy fixture and exact blocking classifications for negative fixtures.

```bash
git add roles/hardware_inventory roles/hardware_validation tests
git commit -m "feat: discover and validate P620 hardware"
```

## Task 7: Intel GPU and PyTorch XPU stack

**Files:**

- Modify: `roles/intel_gpu/**`, `roles/pytorch_xpu/**`, `roles/container_runtime/**`
- Create: GPU apt source/preference templates and `roles/pytorch_xpu/files/validate_xpu.py`
- Create: `docs/intel-gpu.md`, `tests/test_gpu_stack_contract.py`

- [ ] **Step 1: Write failing GPU stack contract tests**

Assert immutable repository key fingerprints, explicit package versions, no oneAPI metapackage, Level Zero tooling, render/video group access, two-device checks, approximate 32 GiB VRAM, PCI IDs, driver/runtime versions, ReBAR evidence, and a per-device PyTorch tensor operation producing structured PASS/FAIL.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_gpu_stack_contract.py -q`

Expected: FAIL on missing pins and validation script.

- [ ] **Step 3: Record a supported compatibility set**

Use Intel's Ubuntu 24.04 client GPU repository and the PyTorch Intel GPU support matrix current on implementation day. Record repository URL, signing-key fingerprint, package version strings, PyTorch version, wheel index URL, Python version, and source URLs in role defaults and `docs/intel-gpu.md`. Resolve every package to an immutable version before enabling installation; repository contract tests reject an empty or mutable pin.

- [ ] **Step 4: Implement minimal GPU packages and access**

Install only compute runtime, Level Zero loader/runtime/tools, OpenCL ICD where required by diagnostics, media libraries only if the runtime needs them, and matching firmware packages. Do not install the full oneAPI suite. Configure `/dev/dri` access for named service accounts and pinned container runtime/device mappings only when enabled.

- [ ] **Step 5: Implement isolated PyTorch XPU environment and validator**

Create a versioned venv path, install from a pinned hash lock, atomically switch a `current` symlink after validation, enumerate two `torch.xpu` devices, record names/memory, and perform allocation, addition, synchronization, and result verification on each device. Write `runtime.json` and a dedicated validation document.

- [ ] **Step 6: Verify static gates and defer physical acceptance explicitly**

Run: `pytest tests/test_gpu_stack_contract.py -q && make lint syntax`

Expected: PASS for repository contracts; physical GPU checks remain `NOT_TESTED` until run on the P620.

- [ ] **Step 7: Commit**

```bash
git add roles/intel_gpu roles/pytorch_xpu roles/container_runtime docs/intel-gpu.md tests
git commit -m "feat: provision pinned Intel XPU stack"
```

## Task 8: vLLM XPU primary service

**Files:**

- Modify: `roles/vllm_xpu/**`
- Create: `roles/vllm_xpu/templates/{vllm.service,vllm.env,vllm-config.yaml}.j2`
- Create: `roles/vllm_xpu/files/validate_vllm.py`, `tests/test_vllm_contract.py`

- [ ] **Step 1: Write failing service contract tests**

Assert pinned vLLM artifact/digest, OpenAI-compatible endpoint, inventory-controlled model and revision, no model token in rendered config, profile-selected tensor parallelism, systemd hardening, persistent logs, health/startup probes, deterministic environment, clean stop/restart, and single/dual validation semantics.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_vllm_contract.py -q`

Expected: FAIL on missing role implementation.

- [ ] **Step 3: Implement versioned runtime installation**

Select the upstream-supported XPU installation mode recorded in the compatibility set. For containers, pin image digest; for venv, pin all wheels with hashes. Stage candidate beside current, validate imports, and atomically select the configured current version. Never use an unqualified image tag.

- [ ] **Step 4: Implement service and health validation**

Render non-secret configuration separately from a root-readable runtime credential environment. Bind to the configured endpoint, use explicit model revision/cache path, persist logs, define startup timeout and restart limits, and query `/health` plus the OpenAI model/completions interface. Dual-GPU success is required only for a configured two-GPU profile and exact model revision.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_vllm_contract.py -q && make lint syntax`

Expected: PASS; live inference remains `NOT_TESTED` off hardware.

```bash
git add roles/vllm_xpu tests
git commit -m "feat: manage vLLM XPU inference service"
```

## Task 9: llama.cpp SYCL fallback

**Files:**

- Modify: `roles/llama_cpp_sycl/**`
- Create: `roles/llama_cpp_sycl/templates/{llama-server.service,llama.env}.j2`
- Create: `roles/llama_cpp_sycl/files/validate_llama.py`, `tests/test_llama_contract.py`

- [ ] **Step 1: Write failing fallback contract tests**

Assert an exact 40-character commit, verified checkout, `GGML_SYCL=ON`, Intel target, Level Zero support, pinned compiler dependencies, GGUF model variables, single-GPU selector, configurable split mode/tensor split, revision recording, deterministic validation prompt, and mandatory exact-combination dual-GPU acceptance.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_llama_contract.py -q`

Expected: FAIL because the role is unimplemented.

- [ ] **Step 3: Implement idempotent pinned build**

Use `git` with an exact commit, CMake modules with explicit build flags, a versioned install directory, a build-stamp containing source/compiler/options hashes, and an atomic current symlink. The build command runs only when the stamp differs and propagates failures. Document that upstream lists Arc B-series but not Ubuntu 24.04 as a verified Linux combination, so real acceptance is mandatory.

- [ ] **Step 4: Implement fallback service and validators**

Support GGUF path, context, GPU layers, `ONEAPI_DEVICE_SELECTOR`, split mode, tensor split, and a disabled-by-default dual-GPU test profile. Validate a deterministic prompt against configured correctness criteria and store commit/device/output metadata.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_llama_contract.py -q && make lint syntax`

Expected: PASS; physical inference remains `NOT_TESTED`.

```bash
git add roles/llama_cpp_sycl tests docs
git commit -m "feat: add pinned llama.cpp SYCL fallback"
```

## Task 10: Independent validation and drift classification

**Files:**

- Modify: `roles/validation/**`, `playbooks/{validate,drift-check,site}.yml`
- Create: `roles/validation/files/aggregate_validation.py`
- Create: `tests/test_validation_aggregation.py`, `tests/test_drift_classification.py`

- [ ] **Step 1: Write failing aggregation tests**

Test all required checks, severity propagation, `PASS/FAIL/BLOCKED/NOT_TESTED`, simulation handling, human summary generation, and all four drift outcomes. A simulated pass must not become physical acceptance.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_validation_aggregation.py tests/test_drift_classification.py -q`

Expected: FAIL because aggregator and classifier are absent.

- [ ] **Step 3: Implement independent probes and aggregation**

Validation invokes read-only probes instead of trusting role change status. Aggregate machine, CPU, GPU, VRAM, Level Zero, PyTorch, topology, ReBAR, vLLM, inference profiles, llama fallback, services, schedules, and Vault access into schema-valid JSON and a concise text report.

- [ ] **Step 4: Implement check/apply/check drift workflow**

`drift-check.yml` first records check-mode predicted changes. When remediation is enabled, it runs scoped convergence, repeats check mode, then validates. Classification uses predicted changes, actual changes, unresolved changes, and blocking validation; task recap is preserved.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_validation_aggregation.py tests/test_drift_classification.py -q && make lint syntax`

Expected: PASS.

```bash
git add roles/validation playbooks tests
git commit -m "feat: independently validate state and classify drift"
```

## Task 11: Scheduled reconciliation and monitoring

**Files:**

- Modify: `roles/scheduled_ansible/**`, `roles/monitoring/**`
- Create: systemd service/timer templates for reconciliation, patches, validation, and benchmarks
- Create: `tests/test_scheduling_contract.py`

- [ ] **Step 1: Write failing scheduling tests**

Assert deployed snapshot path, no Git network operations, `flock`, persistent logs, systemd credentials, Git SHA/inventory/recap/validation manifest fields, enabled normal timer, separately configured patch timer, disabled optional benchmark timer, random delay, and service hardening compatible with GPU access.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_scheduling_contract.py -q`

Expected: FAIL on absent units.

- [ ] **Step 3: Implement native timers and monitoring**

Install root-owned snapshot/run/evidence paths, wrapper configuration, systemd units, timers, logrotate rules, and local metrics collection. Use `ConditionPathIsDirectory`, explicit working directory, `LoadCredential`, `Nice`, `IOSchedulingClass`, and start limits. Normal runs call `site.yml`; scheduled patch application is disabled until policy enables it.

- [ ] **Step 4: Verify and commit**

Run: `pytest tests/test_scheduling_contract.py -q && make lint syntax`

Expected: PASS.

```bash
git add roles/scheduled_ansible roles/monitoring tests
git commit -m "feat: schedule locked host reconciliation"
```

## Task 12: Controlled patch, upgrade, and rollback workflows

**Files:**

- Modify: `playbooks/{patch,upgrade}.yml`, relevant runtime roles
- Create: `tests/test_lifecycle_workflows.py`
- Create: `docs/{patching,upgrades,rollback}.md`

- [ ] **Step 1: Write failing lifecycle tests**

Assert routine patch allowlists, separate high-risk classes, explicit component/candidate input, candidate membership validation, pre-change evidence, reboot gating, `wait_for_connection`, post-change hardware/XPU/inference/benchmark validation, previous environment retention, and no automatic Git mutation.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_lifecycle_workflows.py -q`

Expected: FAIL on incomplete workflows.

- [ ] **Step 3: Implement patch assessment and application**

Assessment records available allowed updates without change. Application requires the policy flag and optional change metadata, updates only allowed packages, checks `/var/run/reboot-required`, reboots only within policy, waits for return, and runs validation plus selected regression profiles.

- [ ] **Step 4: Implement candidate upgrade and rollback**

Require `upgrade_component` and `upgrade_version`, assert exact match to configured candidate, install beside current, validate, and leave selection controlled by inventory. Rollback selects `previous_known_good`, restarts the affected service, validates, and records linkage to the failed run.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_lifecycle_workflows.py -q && make lint syntax`

Expected: PASS.

```bash
git add playbooks roles policies docs tests
git commit -m "feat: control patch upgrade and rollback workflows"
```

## Task 13: Benchmark harness

**Files:**

- Modify: `roles/benchmarking/**`, `playbooks/benchmark.yml`
- Create: `roles/benchmarking/files/run_benchmark.py`, `tests/test_benchmark_contract.py`

- [ ] **Step 1: Write failing benchmark tests**

Assert the five configurable classes and every required provenance, performance, resource, thermal, power, and correctness field. Missing sensors must serialize as unavailable with reason. Model names remain unset until operator selection.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_benchmark_contract.py -q`

Expected: FAIL on missing harness.

- [ ] **Step 3: Implement profile-driven harness**

Validate profile schema before execution; resolve model ID/revision/hash and runtime; warm up; measure prompt rate, generation rate, TTFT, RAM/VRAM, temperature, and power; enforce duration and correctness criteria; write one atomic benchmark JSON document. A two-GPU profile refuses to run without prior exact-combination validation unless invoked as the acceptance test itself.

- [ ] **Step 4: Verify and commit**

Run: `pytest tests/test_benchmark_contract.py -q && make lint syntax`

Expected: PASS with simulated fixture data only.

```bash
git add roles/benchmarking playbooks/benchmark.yml tests
git commit -m "feat: add reproducible inference benchmarks"
```

## Task 14: CMDB, ITSM, and cluster scaffolding

**Files:**

- Modify: `roles/cmdb_export/**`, `roles/itsm_hooks/**`, `playbooks/facts-export.yml`
- Create: `docs/{cmdb,itsm,clustering}.md`
- Create: `tests/test_integration_contracts.py`

- [ ] **Step 1: Write failing adapter contract tests**

Assert normalized CI fields, expected/observed separation, stable schema version, relationships, timestamps/Git SHA, adapter-neutral output, typed ITSM fields, permitted-action allowlist, maintenance-window parsing, CI scope checks, and rejection of command-like free-form input.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_integration_contracts.py -q`

Expected: FAIL because exporters are incomplete.

- [ ] **Step 3: Implement local export and authorization interfaces**

CMDB produces schema-valid JSON only unless a future adapter is enabled. ITSM consumes typed input, validates approvals/window/scope/risk/permitted action, and emits an authorization decision plus result envelope. It never evaluates strings or passes ticket fields to shell.

- [ ] **Step 4: Document cluster metadata and future adapters**

Describe standalone fleet-shaped operation, cluster roles/endpoints, and the explicit feature gate for future Ray/distributed vLLM. Define adapter stdin/stdout, authentication, idempotency key, retry, and error contracts for future CMDB/ITSM products.

- [ ] **Step 5: Verify and commit**

Run: `pytest tests/test_integration_contracts.py -q && make lint syntax`

Expected: PASS.

```bash
git add roles/cmdb_export roles/itsm_hooks playbooks/facts-export.yml docs tests
git commit -m "feat: scaffold fleet integration contracts"
```

## Task 15: Operator documentation and commissioning

**Files:**

- Create: `README.md`, `docs/{architecture,commissioning,operations}.md`
- Update: all component documentation and role READMEs
- Create: `tests/test_documentation_contract.py`

- [ ] **Step 1: Write failing documentation tests**

Assert README covers all 18 required topics, commissioning contains the exact physical/logical sequence, every command references a real playbook/target, rollback and Vault procedures are linked, and hardware-dependent claims use `NOT_TESTED` until real evidence exists.

- [ ] **Step 2: Verify RED**

Run: `pytest tests/test_documentation_contract.py -q`

Expected: FAIL on missing operator documentation.

- [ ] **Step 3: Write complete operator documentation**

Include Ubuntu installation assumptions, inventory configuration, Vault bootstrap, exact bootstrap/convergence/scheduling/patch/upgrade/validation/benchmark/evidence/add-host/cluster/CMDB/ITSM/rollback procedures, security-runtime interactions, evidence retention and external storage, version update workflow, and physical acceptance.

- [ ] **Step 4: Verify commands and commit**

Run: `pytest tests/test_documentation_contract.py -q && make quality`

Expected: PASS.

```bash
git add README.md docs roles tests
git commit -m "docs: add workstation lifecycle runbooks"
```

## Task 16: Final acceptance audit

**Files:**

- Modify only files required to resolve verified failures.

- [ ] **Step 1: Run secret and mutable dependency audit**

Run: `pytest tests/test_no_secrets.py tests/test_repository_contract.py -q`

Expected: PASS with no Ansible Vault content, credentials, mutable runtime tags, or unsafe download pipelines.

- [ ] **Step 2: Run all static and unit gates freshly**

Run: `make quality`

Expected: `yamllint`, `ansible-lint`, all playbook syntax checks, schema checks, and pytest complete with zero failures.

- [ ] **Step 3: Run check-mode and disposable idempotency gates**

Run: `make check idempotency`

Expected: supported localhost-safe roles pass check mode and the second disposable convergence reports `changed=0`.

- [ ] **Step 4: Audit requirement coverage and Git posture**

Run: `git diff --check && git status --short --branch && git log --oneline --decorate -20`

Expected: no whitespace errors; only intentional final changes remain; history has reviewable logical commits.

- [ ] **Step 5: Record the real-host acceptance boundary**

Do not run simulated fixture output as physical proof. Report GPU enumeration, VRAM, ReBAR, PCIe topology, Level Zero, XPU tensor tests, live vLLM, live llama.cpp, thermals, power, reboot/reconvergence, and physical idempotency as `NOT_TESTED` until the P620 is present.

- [ ] **Step 6: Commit verified final corrections**

```bash
git add -A
git commit -m "test: complete configuration acceptance gates"
```

Do not create an empty commit when no corrections were necessary.

## First physical-host execution sequence

After inventory addressing, SSH keys, Vault TLS/AppRole provisioning, model-profile selection, and compatibility-pin review:

```bash
python3 -m venv .venv
.venv/bin/pip install --require-hashes -r requirements.txt
.venv/bin/ansible-galaxy collection install -r requirements.yml
make quality
.venv/bin/ansible-playbook playbooks/bootstrap.yml --limit ai-p620-01 --ask-become-pass --tags bootstrap,vault
.venv/bin/ansible-playbook playbooks/baseline.yml --limit ai-p620-01 --tags baseline,security,network,storage
.venv/bin/ansible-playbook playbooks/site.yml --limit ai-p620-01
.venv/bin/ansible-playbook playbooks/validate.yml --limit ai-p620-01
.venv/bin/ansible-playbook playbooks/benchmark.yml --limit ai-p620-01 --extra-vars benchmark_profile=small
.venv/bin/ansible-playbook playbooks/benchmark.yml --limit ai-p620-01 --extra-vars benchmark_profile=large
.venv/bin/ansible-playbook playbooks/site.yml --limit ai-p620-01
.venv/bin/ansible-playbook playbooks/drift-check.yml --limit ai-p620-01 --check
```

Proceed to large dual-GPU and sustained profiles only after single-GPU acceptance and explicit model/runtime configuration. Preserve the resulting evidence directory as the commissioning baseline.
