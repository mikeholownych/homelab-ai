# aihost — Enhancement Analysis & Opportunity Report

**Generated:** 2026-06-14  
**Repository:** `/home/mike/Projects/aihost`  
**Local HEAD:** `bf12c89` — *feat(inventory): declare hermes as authorized orchestrator gateway client*  
**Origin main:** `5b83ac6` — *docs(release): certify v1.0.0 readiness with all 17 gates passing*  
**Divergence:** Local is **73 commits ahead** of origin/main; **0 commits behind**.

---

## 1. Repository Overview

**aihost** is an Ansible-driven infrastructure automation project for a local AI homelab. It manages:

- **Orchestrator Gateway** — Python-based LLM inference gateway with smart routing, streaming, caching, and self-healing
- **vllm-top** — Rust-based heterogeneous worker discovery & monitoring engine (139 Rust tests pass)
- **Observability stack** — Grafana dashboards, Prometheus rules, OTLP distributed tracing, syslog evidence transport
- **Hardware profiles** — Intel Arc Pro B65 (d5820), NVIDIA P620 (p620), template profiles
- **Inventory management** — Production host groups, vault servers, nftables firewall policies
- **Smart routing** — 12 capabilities (R1–R12): cancellation, priority, escalation, shadow routing, drain/swap, quotas, deadlines, reasoning control, capability-checked routing, feedback loop, evidence integrity, graceful restart

### Branch Landscape

| Branch | Commit | Purpose |
|--------|--------|---------|
| `main` | `bf12c89` | Current development (73 commits ahead of origin) |
| `b0-evidence-remediation` | `1f3f5b6` | Evidence pipeline fixes |
| `phase0-offline-prototype` – `phase13-heterogeneous-qualification` | Various | 14 phase branches (feature development) |
| `security/t5820-credential-remediation-20260929` | `68de433` | Security remediation |

### Recent Commit Themes (last 20)

1. **Release certification** — v1.0.0 readiness with 17 gates passing
2. **Security hardening** — Controller reconciliation boundary, Vault DR unseal runbook
3. **Architecture docs** — Dual-llama.cpp SYCL deployment reconciliation
4. **Gateway features** — Phase 4 hot reload, self-healing, semantic cache, web console
5. **Observability** — OTLP tracing, networked syslog, complexity tier metrics, idle fallbacks
6. **Inventory fixes** — Decouple uncommissioned hosts, vault_servers group, hermes client authorization
7. **Lint remediation** — yamllint and ansible-lint violations

---

## 2. Identified Enhancement Opportunities

### 2.1 [HIGH] Push Local Branches to Origin

**Status:** Local `main` is 73 commits ahead of `origin/main` with no push.

**Risk:** All local work is at risk of loss. The working tree is clean but unpushed.

**Action:** `git push origin main` after confirming no remote changes need merging first.

---

### 2.2 [HIGH] Complete V9 — PCIe ASPM Policy

**Source:** `tasks/todo.md` line 453–499 — Closeout workstream, validation finding V9 (pcie_aspm policy) marked incomplete `[ ]`.

**Context:** All other closeout findings (V1–V8) and code review findings (N1–N6) are marked complete. V9 is the last unchecked validation item.

**Action:** Define and implement PCIe ASPM (Active State Power Management) policy for the Intel C422 platform, then mark V9 complete.

---

### 2.3 [HIGH] Resolve NEXUS_SEC_REF Placeholders

**Source:** `tasks/todo.md` lines 24, 118 — References to `Flash-Next-GSQ-RCO-Coder` and `Glimmer/GLM/Flash-Next` are unresolved.

**Context:** These appear to be internal security reference identifiers that should resolve to actual files, configs, or evidence artifacts in the repository.

**Action:** Locate or create the referenced artifacts; if they are external, document the resolution path.

---

### 2.4 [MEDIUM] Update Ubuntu Codename Reference

**Source:** `README.md` line 60 — References "Ubuntu 26.04 LTS (Resolute Raccoon)" which is not an official Ubuntu codename (26.04 is not yet released/officially named).

**Context:** The README documents supported releases; the codename is speculative.

**Action:** Update to use the official codename once released, or remove the speculative name.

---

### 2.5 [MEDIUM] Add tasks/todo.md and docs/design/ to Documentation Index

**Source:** `docs/README.md` — Documentation index does not link to `tasks/todo.md` or `docs/design/` directory.

**Context:** The docs index provides navigation to architecture, platform, operations, and reference docs but omits the task tracker and design documents.

**Action:** Add entries for `tasks/todo.md` (project status) and `docs/design/` (design documents) to the documentation index.

---

### 2.6 [MEDIUM] Complete Future Evolution Roadmap

**Source:** `tasks/todo.md` lines 377–399 — Future evolution topics marked as "later/not authorized":
- Queueing improvements
- Efficient worker use
- Model switching
- Batch windows

**Context:** These are identified as next-phase capabilities but not yet authorized for implementation.

**Action:** Prioritize and authorize the next evolution phase, or formally close these as out-of-scope.

---

### 2.7 [MEDIUM] Benchmark Evidence Documentation

**Source:** `README.md` line 39 — Claims "vLLM was retired... after empirical qualification showed llama.cpp SYCL delivers over 4x higher throughput" without citing the specific benchmark evidence file.

**Context:** The claim is significant but lacks a traceable evidence reference.

**Action:** Add a reference to the specific benchmark report or evidence file that supports the 4x throughput claim.

---

### 2.8 [LOW] Unify Version Management

**Source:** Multiple `versioning.py` files across phase directories (`phase0`–`phase8`); `vllm-top/CHANGELOG.md` (410 lines); `orchestrator_gateway/__main__.py` uses `ORCHESTRATOR_REGISTRY_VERSION` env var.

**Context:** Version management is fragmented across phase directories, the Rust vllm-top crate, and the Python gateway. No root-level VERSION file exists.

**Action:** Establish a single source of truth for versioning (e.g., root `VERSION` file) and ensure all components derive from it.

---

### 2.9 [LOW] Legacy vllm-top Checkout Synchronization

**Source:** `tasks/todo.md` line 151 — Legacy checkout at `/home/mike/Projects/vllm-top` is v0.8.0; production is v0.9.2.

**Context:** The legacy checkout is 1.2 versions behind production.

**Action:** Update the legacy checkout or document why it should remain at v0.8.0.

---

### 2.10 [LOW] README Script Reference Verification

**Source:** `README.md` line 131 references `scripts/run-ansible-snapshot` which is not listed in Makefile playbooks or standard paths.

**Context:** The script is referenced in documentation but may not exist or may be orphaned.

**Action:** Verify the script exists and is functional, or remove the reference.

---

## 3. Architecture Observations

### 3.1 Strengths
- **Comprehensive smart routing** — 12 routing capabilities fully implemented and deployed
- **Multi-engine support** — vLLM, llama.cpp SYCL, Ollama, SGLang, TGI, and OpenAI-compatible fallback
- **Observability depth** — OTLP tracing, Prometheus rules, Grafana dashboards with idle fallbacks
- **Security posture** — nftables firewall policies, Vault integration, TLS client-compatibility remediation
- **Test coverage** — 139 Rust tests pass in vllm-top; pytest with importorskip guards
- **Ansible automation** — Full infrastructure-as-code with linting, syntax validation, and integration tests

### 3.2 Areas for Improvement
- **Branch hygiene** — 14 phase branches + security branch + main, all local; none pushed to origin
- **Documentation completeness** — Missing links in docs index, unresolved security references
- **Version consistency** — Fragmented version management across components
- **Evidence traceability** — Some claims lack specific file references

---

## 4. Recommended Priority Order

| Priority | Enhancement | Effort | Impact |
|----------|------------|--------|--------|
| P0 | Push local branches to origin | Low | Critical — prevents data loss |
| P1 | Complete V9 (PCIe ASPM policy) | Medium | Closes last validation gap |
| P1 | Resolve NEXUS_SEC_REF placeholders | Low | Completes closeout |
| P2 | Update Ubuntu codename reference | Low | Documentation accuracy |
| P2 | Add tasks/design to docs index | Low | Documentation completeness |
| P2 | Benchmark evidence documentation | Low | Claim traceability |
| P3 | Future evolution roadmap | Medium | Strategic planning |
| P3 | Unify version management | Medium | Operational hygiene |
| P4 | Legacy vllm-top sync | Low | Maintenance |
| P4 | README script verification | Low | Documentation accuracy |

---

## 5. Repository Health Summary

| Metric | Value |
|--------|-------|
| Working tree status | Clean (no uncommitted changes) |
| Local vs origin | 73 commits ahead, 0 behind |
| Branches | 18 total (1 main + 14 phase + 1 security + 2 others) |
| Recent author | Mike Holownych (all 20 recent commits) |
| Test status | 139 Rust tests (vllm-top); pytest suite available |
| Lint status | yamllint + ansible-lint configured |
| Release state | v1.0.0 certified with 17 gates passing |
| Closeout status | V1–V8 complete, V9 incomplete; N1–N6 complete |
