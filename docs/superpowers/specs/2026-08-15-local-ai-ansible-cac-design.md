# Local AI Ansible Configuration-as-Code Design

## Purpose

This repository is the authoritative reconstruction and lifecycle-management path for an Ubuntu 24.04 LTS local AI workstation fleet. The initial managed node is Lenovo ThinkStation P620 `ai-p620-01`, machine type/model `30E1S7NJ00`, with an AMD Threadripper PRO 3945WX and two Intel Arc Pro B65 32 GB GPUs. The same inventory and role model must accommodate additional nodes and clusters without requiring a new orchestration platform.

Git holds all non-secret desired state. Ansible performs convergence, discovery, lifecycle changes, and independent validation. HashiCorp Vault is the only secret authority. Generated evidence records what ran and what was observed without becoming desired state.

## Repository Boundary

`/home/mike/Projects/aihost` is the repository root. The repository begins empty, so it establishes its own Ansible, lint, test, and CI conventions. Generated evidence, logs, caches, model weights, Vault credentials, and tokens remain outside version control.

Scheduled reconciliation uses a deployed repository snapshot. A node never pulls a branch as part of an unattended run. Updating the deployed snapshot is a separate authorized operation, allowing a future CI or ITSM gate to control rollout without changing the host convergence contract.

## Architecture

The implementation uses a hybrid host-native architecture:

- Ansible, Intel kernel and user-space GPU support, Level Zero, hardware discovery, monitoring, and systemd scheduling run on the host.
- PyTorch XPU, vLLM XPU, and llama.cpp SYCL use separate pinned environments. A pinned container is permitted for a runtime only when the supported Intel compatibility matrix makes it more reproducible than a host virtual environment.
- Inventory describes node identity, roles, capabilities, topology, and feature switches. Tags only select work.
- Version-controlled hardware profiles define expected state and mismatch severity. Discovery preserves observed topology rather than forcing expected values onto unknown hardware.
- Policy files define patch, upgrade, drift, and validation behavior independently from role implementation.
- Evidence contracts and normalized export schemas isolate operational consumers from individual role internals.

No cluster runtime, CMDB product adapter, ITSM product adapter, or external scheduler is installed by default.

## Inventory and Desired State

The production inventory defines `ai-p620-01` as a production inference and GPU node. It records its `p620_dual_b65` hardware profile, capabilities, feature switches, future cluster metadata, network endpoint placeholders, runtime profiles, and model paths. Host-specific values override group defaults only where the node is genuinely different.

The P620 hardware profile records expected machine type, CPU, GPU count and model, approximate per-GPU VRAM, Gen4 negotiated PCIe capability, and severity rules. PCIe width is discovered and evaluated against actual slot topology; the profile does not blindly assert x16. BIOS, firmware, serial, asset, PSU, DIMM, NVMe, and NIC values are recorded when discoverable. Unknown values are reported explicitly.

Blocking defaults include GPU count or model mismatch, absent required ReBAR, missing Level Zero devices, and materially degraded PCIe topology. Lesser deviations are classified as warning or informational.

## Role Boundaries

Roles are narrowly scoped:

- `base_os`, `time_sync`, `storage`, and `networking` manage the Ubuntu platform baseline.
- `security`, `users`, and `ssh` manage access and practical hardening without imposing an unreviewed generic CIS profile.
- `hardware_inventory` collects observations; `hardware_validation` compares them with the selected profile.
- `intel_gpu` installs pinned required GPU and Level Zero components and proves enumeration, device IDs, versions, VRAM, topology, and large BAR state.
- `container_runtime` provides pinned container tooling only when enabled.
- `pytorch_xpu`, `vllm_xpu`, and `llama_cpp_sycl` own isolated, pinned runtime environments and runtime-specific acceptance checks.
- `monitoring` collects useful host and GPU telemetry without requiring a fleet monitoring backend.
- `vault_integration` authenticates and performs fail-closed runtime secret lookups through a replaceable authentication interface.
- `scheduled_ansible` installs locked systemd reconciliation, patch, and optional benchmark/validation units.
- `validation` independently checks resulting state and emits structured and human-readable results.
- `benchmarking` runs configurable profiles and records reproducibility and performance metadata.
- `cmdb_export` emits normalized expected-versus-observed CI data.
- `itsm_hooks` validates a bounded change authorization contract and never executes free-form ticket content.

Shared evidence helpers are reusable task files and templates. Roles do not duplicate manifest or checksum logic.

## Convergence and Operational Flow

The standard flow is:

```text
deployed Git snapshot
-> inventory + hardware profile + policies
-> Vault authentication and runtime lookups
-> discovery
-> desired-state convergence
-> independent validation
-> evidence manifest and checksums
-> optional CMDB/ITSM adapter outputs
```

Playbook responsibilities are explicit:

- `bootstrap.yml` establishes Python, operator access, repository runtime prerequisites, and Vault prerequisites from a documented Ubuntu base installation.
- `baseline.yml` applies base OS, users, SSH, security, time, storage, and network intent.
- `site.yml` performs authoritative convergence in dependency order.
- `drift-check.yml` combines check-mode convergence results and validation to classify no drift, remediated drift, unresolved drift, or blocking drift.
- `patch.yml` applies only policy-approved patch classes and validates after an allowed reboot.
- `upgrade.yml` applies an explicitly selected candidate for one component, validates it, and preserves rollback information; it does not rewrite Git automatically.
- `validate.yml` performs fresh independent validation.
- `benchmark.yml` runs selected configurable benchmark profiles.
- `facts-export.yml` produces normalized export data for future CMDB adapters.

Normal reconciliation uses `site.yml`, remediates permitted drift, runs independent validation, and records Git SHA, inventory target, recap counts, and final validation status. A host-local lock prevents overlapping Ansible processes.

## Secrets

Vault is the only secret authority. Git stores logical path references under `secret/local-ai/shared/`, `secret/local-ai/hosts/<host>/`, `secret/local-ai/clusters/`, and `secret/local-ai/services/`, but no secret values.

Initial machine authentication uses AppRole. The role ID and secret ID are provisioned out of band into systemd credentials or root-readable files with least privilege; neither is committed. The scheduled runner exchanges them for a short-lived token, performs runtime lookups, and does not persist secret values in generated facts, logs, or evidence. Authentication is abstracted so another Vault auth method can replace AppRole without redesigning consumers.

Vault unavailability or authorization failure stops dependent work. There is no Ansible Vault, long-lived administrative token, plaintext fallback, or stale secret cache.

## Runtime Lifecycle

Versioned components use `current`, `candidate`, and `previous_known_good` pins. Normal convergence installs `current`. An explicit upgrade invocation selects the configured candidate, captures pre-change evidence, applies it, runs hardware and runtime validation, and fails closed on any required check. Promotion of a validated candidate to `current` is a reviewed Git change, not an automatic mutation.

Routine OS and security patches are separated from kernel, Intel GPU runtime, Level Zero, PyTorch, vLLM, llama.cpp, BIOS, and firmware changes. High-risk components change only through version pins in Git. Reboots occur only when policy permits and the host reports they are required.

The vLLM service exposes an OpenAI-compatible API, uses inventory-selected model and profile configuration, supports configurable tensor parallel sizes, has deterministic environment and restart behavior, persists logs, and has explicit startup and health checks. No model is hard-coded.

llama.cpp is pinned to an exact commit or release, records that revision, accepts GGUF and split parameters through variables, and validates output. Dual-GPU SYCL support is never declared merely because configuration exists; the exact model/runtime combination must pass its dual-GPU test.

## Validation and Failure Semantics

Task success is not acceptance. Independent validation produces JSON plus a human-readable summary. Individual checks use `PASS`, `FAIL`, `BLOCKED`, or `NOT_TESTED`, with severity and evidence references.

Required checks cover CPU, machine model, two B65 GPUs, approximate VRAM, two Level Zero devices, two PyTorch XPU devices with per-device tensor operations, observed PCIe topology, required ReBAR, vLLM health, configured single- and dual-GPU inference, llama.cpp fallback, required services, scheduled reconciliation, and Vault access.

Hardware-dependent CI results are marked `simulated: true` and cannot satisfy physical acceptance. On absent real hardware, relevant checks remain `NOT_TESTED`. Blocking mismatches prevent runtime acceptance. Partial evidence is retained after failures and marked incomplete.

## Evidence and Drift

Each major operation creates a UTC timestamped run directory under a configurable evidence root, outside Git by default. It contains a manifest, component observations, validation or benchmark results, a human summary, and `SHA256SUMS`. The manifest identifies hostname, Git SHA, inventory, playbook, start/end timestamps, simulation status, Ansible recap counts, and resulting classification.

Drift status is one of:

- `no_drift`: check-mode convergence predicts no changes and validation passes.
- `remediated_drift`: convergence changed state and validation passes.
- `unresolved_drift`: convergence or non-blocking validation leaves differences.
- `blocking_drift`: a blocking mismatch or validation failure prevents acceptance.

Manual changes are reverted during scheduled convergence where policy permits. High-risk unexpected state is reported as blocking rather than silently normalized.

## Benchmarking

Benchmark profiles define model identity and revision, quantization, GPU count, tensor parallel size, context, correctness criteria, duration, and optional split parameters. Initial classes cover small single-GPU, 30-32B single-GPU, approximately 70B dual-GPU, supported low-precision or MoE, and sustained thermal/load testing without selecting arbitrary model names.

Results record the required host, firmware, kernel, runtime, model, throughput, latency, memory, temperature, power, and correctness metadata. Unsupported telemetry is represented as unavailable rather than fabricated. Benchmarking is separate from provisioning and only scheduled when explicitly enabled.

## CMDB, ITSM, and Clustering Interfaces

CMDB export uses a normalized versioned schema with stable node ID, expected state, observed state, relationships, runtime versions, convergence timestamps, validation timestamps, and Git SHA. Product adapters consume that schema later; collection roles do not depend on ServiceNow, Jira Assets, Device42, NetBox, or another product.

ITSM hooks accept only typed fields: change ID, request ID, affected CI IDs, risk, approval state, maintenance window, permitted action, rollback reference, execution result, and validation result. The interface validates authorization and emits an adapter request. No free-form field becomes a command or Ansible argument.

Cluster inventory defines cluster name, enabled flag, node role, worker/API/scheduler/storage roles, endpoints, and capabilities. The first host is fleet-shaped but standalone. Ray or distributed vLLM installation remains disabled until an explicit future design and Git change enable it.

## Scheduling and Security

Systemd timers invoke a wrapper from the deployed snapshot for normal reconciliation, patch assessment/application, and optional validation or benchmarking. The wrapper uses `flock`, captures durable logs, creates evidence, and never updates the repository. Timers use randomized delay where appropriate to scale across future nodes.

The security baseline hardens SSH, proves key access before disabling password authentication, manages sudo and firewall policy, applies least-privilege service accounts and file modes, and enables useful audit/log retention. Controls affecting GPU devices, containers, locked memory, network listeners, or inference services are documented alongside their compatibility effects. Unattended upgrades are disabled so they cannot mutate the pinned GPU/runtime stack.

No arbitrary download-and-execute pipeline is used. Command or shell tasks are allowed only where no suitable module exists and must declare why, define change conditions, propagate failures, and document idempotency.

## Testing and Quality Gates

All gates run locally through `make`; GitHub Actions is added as the default CI because no existing platform convention exists.

Gates include YAML formatting, `yamllint`, `ansible-lint`, inventory parsing, syntax checks for every playbook, repository contract tests, schema validation, secret-pattern checks, pinning checks, and unsafe-task checks. Fixture tests cover healthy P620 observations and failures for GPU count/model, ReBAR, Level Zero, VRAM, and PCIe degradation. Fixtures are explicitly simulated.

Check mode is supported where meaningful. Baseline roles receive disposable Ubuntu 24.04 idempotency coverage, requiring zero changes on a second run. Hardware, GPU, systemd, and inference acceptance remains fixture-backed in CI until the real host is available.

Physical acceptance follows commissioning order: factory capture; chassis, serial, PSU, memory, and storage checks; approved firmware and BIOS prerequisites; first GPU installation and validation; second GPU installation and validation; XPU and inference deployment; single- and dual-GPU tests; sustained load; reboot; reconvergence; idempotency; and accepted-baseline evidence.

## Commit Strategy

Implementation is divided into reviewable commits:

1. repository foundation, schemas, policies, inventory, and contract tests;
2. Ubuntu baseline, access, and security roles;
3. hardware discovery, validation, Intel GPU, and PyTorch XPU roles;
4. vLLM and llama.cpp runtime roles;
5. scheduling, drift, patch, upgrade, evidence, and benchmarking;
6. CMDB/ITSM scaffolding, cluster documentation, and operator documentation;
7. final verification fixes.

Each commit must pass the gates relevant to the files it introduces. Hardware acceptance is reported separately and cannot be claimed before the physical P620 and both B65 GPUs are tested.
