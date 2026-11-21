# MS-S1 Max Production Promotion Design (Phase 3)

**Date:** 2026-11-21

**Status:** Awaiting implementation plan — Phase 2 lab wire complete
(PR #57 / `ee8c969`; llama.cpp HIP + Qwen3-Coder-30B-A3B Q8_0)

**Host:** `ai-ms-s1-max-01` at `10.0.8.6` (Minisforum MS-S1 Max)

**Depends on:**
- `docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-commissioning-design.md`
- `docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-engine-selection-design.md`

## Goal

Promote `ai-ms-s1-max-01` to a **full production peer** of `ai-5820-01`
(inventory, local gateway, monitoring, reconcile) while adding **parallel ROCm
capacity** — a distinct capacity alias that does **not** share the Intel SYCL
lead pool — reachable both via a local MS-S1 gateway and via the existing
`ai-5820-01` gateway front door.

## Non-Goals

- Replacing or migrating Intel SYCL lead / deep aliases off `ai-5820-01`.
- Merging heterogeneous models into one shared lead alias (clients must not
  silently receive either Qwen3.6 SYCL or Coder-30B HIP for the same alias).
- Changing Phase 1 ROCm 7.2.0 pins, Secure Boot, or APU carve-out.
- Enabling SGLang or vLLM ROCm in production (bake-off losers stay off).

## Decisions (operator-approved)

| Topic | Choice |
| --- | --- |
| Promotion depth | Full peer of `ai-5820-01` (inventory, gateway, monitoring, reconcile) |
| Fleet role | Additional capacity (both hosts serve) |
| Alias strategy | Parallel ROCm capacity alias; Intel lead exclusive |
| Gateway topology | Local gateway on MS-S1 **and** advertise worker on 5820 gateway |
| Worker exposure | LAN bind + API key; ufw allow 5820 + localhost |
| Approach | Staged cutover (3a→3f) |

## Architecture

```
Clients
   │
   ├──────────────► MS-S1 local gateway (TLS) ──► HIP worker (Coder-30B Q8_0)
   │                      parallel ROCm alias
   │
   └──────────────► 5820 gateway (TLS)
                         │
                         ├─ Intel lead/deep (unchanged) ──► SYCL workers
                         └─ parallel ROCm alias ──────────► remote HIP worker
                                                            (10.0.8.6 + API key)
```

## Stage map

| Stage | Name | Outcome |
| --- | --- | --- |
| 3a | Inventory cutover | Host in production groups; lab live entry removed |
| 3b | Worker harden | API key + LAN bind + ufw |
| 3c | Local gateway | TLS gateway on MS-S1; ROCm-only routes |
| 3d | 5820 advertise | Remote worker + parallel alias on 5820 |
| 3e | Monitoring + reconcile | Peer observability and reconcile targeting |
| 3f | Dual-front-door qualify | Evidence through both gateways; Intel aliases verified |

Fail closed between stages; retain last verified evidence on stop.

## Stage 3a — Inventory cutover

### Production groups

Add `ai-ms-s1-max-01` under `production`, `inference`, `gpu`, `monitoring`, and
`cluster` in `inventory/production/hosts.yml` (same group set as `ai-5820-01`).

### Host vars

Create `inventory/production/host_vars/ai-ms-s1-max-01.yml` from the lab wire
contract, then:

- Keep: `rocm_install_enabled`, `llama_cpp_hip_enabled`, hardware profile,
  storage LVM, Intel path off, HIP digest/model pins.
- Set: `node_metadata.environment: production`.
- Enable: `orchestrator_gateway_enabled`, production monitoring/observability
  features matching a peer of 5820, reconcile eligibility.
- Set `capabilities.cluster_eligible` consistently with 5820 peer policy.

### Lab inventory

Remove the live host from `inventory/lab` (no dual-live host_vars). Single
source of truth is production. Document the cutover in `docs/commissioning.md`.

### Contracts

Inventory tests assert production membership and absence from lab live hosts.

## Stage 3b — Worker harden

Extend `roles/llama_cpp_hip` (and host_vars) so the production worker:

- Binds to the host LAN address (`10.0.8.6`) or `0.0.0.0` with ufw as the fence
  — **not** loopback-only.
- Requires an API key (Vault-managed or `/etc/local-ai/` file; same pattern as
  SYCL workers on 5820).
- ufw: allow the HIP worker port from `10.0.8.5` (5820) and localhost; deny
  other sources.
- Keeps image digest pin, `/dev/kfd` + DRI devices, no `HSA_OVERRIDE_GFX_VERSION`.

Health: authenticated `/v1/models` from localhost and from 5820.

## Stage 3c — Local gateway on MS-S1

Enable `orchestrator_gateway` on `ai-ms-s1-max-01`:

- ASGI engine; TLS with SANs for `10.0.8.6` and hostname.
- Routes/aliases: **parallel ROCm capacity only** (names locked at plan time,
  e.g. `interactive-rocm` / `engineering/interactive-rocm`) → local HIP worker.
- Do **not** define or shadow Intel lead/deep aliases on this gateway.
- Vault-managed clients as required for the local front door.
- Bump gateway release id per existing inventory/release conventions.

## Stage 3d — Advertise on 5820 gateway

On `ai-5820-01` gateway config:

- Add a remote worker entry for the MS-S1 HIP worker
  (`http://10.0.8.6:<hip-port>` or TLS if added later) with API key.
- Add the matching **parallel** alias/route; Intel lead/deep pools unchanged.
- Bump `orchestrator_gateway_release_id` and converge carefully.
- Pre/post qualify Intel lead alias still maps only to SYCL workers.

## Stage 3e — Monitoring + reconcile

- Enable node monitoring / Alloy (or the current production peer pattern) for
  MS-S1; scrape HIP `/metrics` when exposed.
- Add the host to reconcile-controller / scheduled reconciliation targets like
  5820.
- Ensure Grafana fleet dashboards include the host with idle/zero fallbacks per
  repo observability conventions.

## Stage 3f — Dual-front-door qualification

Required probes:

1. **MS-S1 local gateway:** `/v1/models`, short chat, tool-shaped request on the
   ROCm parallel alias.
2. **5820 gateway:** same probes via the parallel alias → remote MS-S1 worker.
3. **Regression:** Intel lead alias on 5820 still routes only to SYCL workers.

Archive under `evidence/ai-ms-s1-max-01/<UTC>/promotion/`.

## Failure handling

Checkpoints: `3a → 3b → 3c → 3d → 3e → 3f`.

- Blocking failure stops later stages; keep last good evidence.
- Do not leave dual conflicting host_vars (lab + production).
- Do not open the worker port fleet-wide without API key + ufw.
- Do not change Intel lead routing to “make capacity work.”
- 5820 gateway bumps require pre/post Intel alias verification.

## Testing strategy

- **Contract/unit:** production inventory membership; lab absence; exactly one
  engine flag; gateway route tables (ROCm parallel vs Intel exclusive); ufw
  allowlist shape.
- **Physical:** staged converges with health after each stage; dual-front-door
  qualify; Intel regression.
- **Repo quality:** lint/syntax on touched roles/playbooks before mutation.
- **Idempotency:** second converge idle after each mutating stage.

## Completion criteria

Phase 3 is complete only when:

1. Host is in production inventory groups and absent from lab live inventory.
2. HIP worker is API-key protected and LAN-reachable only from allowed sources.
3. Local MS-S1 gateway serves the parallel ROCm alias successfully.
4. 5820 gateway serves the same parallel alias to the remote HIP worker.
5. Intel lead/deep aliases on 5820 remain SYCL-only.
6. Monitoring and reconcile targeting are enabled for the host.
7. Dual-front-door qualification evidence is archived.
8. Commissioning/ops docs describe the production peer layout.

## Follow-on (out of scope)

- Client cutover guidance for consumers that should prefer the ROCm alias.
- Optional later bake-off expansion (deferred shortlist models) under production
  change control.
- Any future migration of Intel workloads onto MS-S1 (separate design).
