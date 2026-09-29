# Phase 14 Baseline Identity: Frozen Phase 13 Baseline

- **Date:** 2026-09-29
- **Author:** Autonomous Engineering System
- **Status:** Complete / Frozen / Cryptographically Verified
- **Baseline Release Commit:** `90890390f70a5c404bc557876a337582b1da79b5`
- **Canonical Remote HEAD:** `ca5385348321fba5a2f17f7f19f457bfe0d52eba`
- **Canonical Tree SHA:** `9267686198d3149e68eb77ccc5dc02c12cf317b2`

---

## 1. Frozen Baseline Component Identities

| Component | Identifier / Path | Version / Commit / Hash | Operational State |
|---|---|---|---|
| **Canonical Repository** | `mikeholownych/homelab-ai` | `origin` (`git@github.com:mikeholownych/homelab-ai.git`) | Clean / Synchronized |
| **Current Remote HEAD** | `origin/main` | `ca5385348321fba5a2f17f7f19f457bfe0d52eba` | Verified Green in CI Run `36514809766` |
| **CI Triggering Commit** | `f10bbc3` | `f10bbc3948419619fe2f3338eaa6b4010a90c2f7` | Verified Green in CI Run `36512730505` |
| **Production Promotion** | Branch integration commit | `90890390f70a5c404bc557876a337582b1da79b5` | `CONFIGURATION_B_PRODUCTION_PROMOTION: COMPLETE_PROVEN` |
| **Production Scheduler** | `phase13/src/.../capability_scheduler.py` | SHA-256: `d9c17160749e5a67f9378e7470814c3e9bbaeceec128ca50ca16ce193e3b1947` | Default: `SchedulingMode.CONFIGURATION_B` |
| **Production Pipeline** | `phase13/src/.../production_pipeline.py` | SHA-256: `18f1a2333cfc8b0ebae721feec05c93c4ff433b9b46ec6ff36a2185ee9156645` | Homogeneous Dual-30B Pipeline |
| **Worker 1 Model** | GPU 0 (`0000:51:00.0`, Port 8000) | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | Active / Healthy / Authoritative Lead |
| **Worker 2 Model** | GPU 1 (`0000:93:00.0`, Port 8001) | `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | Active / Healthy / Secondary Specialist |
| **Gateway Router** | Host Port 8010 (Tunnel 18010) | `engineering/b0` virtual service | Active / Healthy / Authenticated |
| **External Validator** | `phase13/src/.../containment.py` | SHA-256: `95f80d6dc25252b09f7d0f47363b57c2c95e84f1c3a20bca3732c8d5b6e12530` | `ExternalAuthorityBoundary` Enforced |
| **Rollback Procedure** | `phase13/src/.../baseline_restore.sh` | SHA-256: `e0c4b2353381640fa8894dfa9cce54c25f4a6217409489fef79eb67823f666f8` | Tested / Deterministic (< 2 min MTTR) |
| **Phase 12 Manifest** | `phase12/evidence/manifest.sha256` | SHA-256: `da12f1d2a97a648eb7961d421d35d92038e710b545889966df8ed17220b4d4dc` | 31/31 Verified Artifacts |
| **Phase 13 Manifest** | `phase13/evidence/manifest.sha256` | SHA-256: `eb994d837a3ebeaa2b4eba4709202db8241ae3d7ec5f8bb1b36fa36310807d35` | 129/129 Verified Artifacts |

---

## 2. Model Routing & Exclusion Invariants

1. **7B Model Exclusion**:
   - The experimental 7B candidate model (`Qwen/Qwen2.5-7B-Instruct-AWQ`) is completely stopped, unloaded from VRAM, and absent from active routing tables.
   - Live querying of Worker 2 (`http://10.0.8.5:8001/v1/models`) authoritatively returns `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`.
   - The Gateway virtual model `engineering/b0` dispatches exclusively to Worker 1 and Worker 2 under homogeneous 30B serving.
2. **Authority Isolation**:
   - Worker 2 is restricted by `CapabilityAwareScheduler.validate_worker_authority` to `TaskClass.TEST_GENERATION` and `TaskClass.STRUCTURED_OUTPUT`.
   - Worker 1 retains sole lead authority for architecture, core implementation, security review, integration, and final project acceptance.
   - All specialist outputs undergo out-of-process quarantine and sanitization via `ExternalAuthorityBoundary` prior to downstream consumption.

---

## 3. Preservation of Phase 13 Qualification Limitations

The baseline preserves the final qualified disposition:
`PHASE_13_CAUSAL_AND_SUSTAINED_QUALIFICATION: PROVEN_WITH_LIMITATIONS`

The empirical limitations established in Phase 13 remain active and binding:
1. **Critical-Path Truncation**: Faster token decoding on Worker 2 does not translate into proportional end-to-end project acceleration because Worker 1's serialized execution dominates project turnaround.
2. **Queue Backlog Asymmetry**: Under burst arrival regimes ($\lambda = 4.0$ req/min), project queue delays ($W_q$) are driven by Worker 1 traffic intensity ($\rho_1 = 1.58$), while Worker 2 remains underutilized ($\rho_2 \le 0.24$).
3. **Non-Authoritative Role**: Specialized secondary workers remain advisory and cannot hold final acceptance authority.
