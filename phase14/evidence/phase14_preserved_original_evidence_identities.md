# Phase 14 Experiment 02: Preserved Original Evidence Identities

- **Date:** 2026-09-29
- **Canonical Repository:** `mikeholownych/homelab-ai`
- **Source Commit:** `a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce`
- **Manifest Scope:** 32 verified Phase 14 artifacts prior to forensic additions

---

## 1. Preserved Campaign Artifact Identities

All original Phase 14 Experiment 02 reports, data payloads, traces, and manifests remain completely unmodified. The table below records the preserved artifacts and their cryptographic SHA256 hashes as verified by `generate_manifest.py verify`:

| Artifact Name | Preserved SHA256 Hash | Category |
|---|---|---|
| [`manifest.sha256`](file:///home/mike/Projects/aihost/phase14/evidence/manifest.sha256) | Baseline Manifest (32 files) | Integrity Ledger |
| [`phase14_sustained_comparison_results.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_comparison_results.json) | `db9ca6db0f946270632ea3c95977a44f51e089201509a25b3a32fcfc751ba861` | Primary Campaign Data |
| [`phase14_sustained_config_b_results.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_config_b_results.json) | `ec48e5ceba0a475d4001cbf5f089679f22569fa12df0ca84f72db771804d9c79` | Config B Cohort Traces |
| [`phase14_sustained_config_b_plus_results.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_config_b_plus_results.json) | `f044955b76cf66d3bc01b590e828456637e199f36f0ecf62776c59b2075a3639` | Config B+ Cohort Traces |
| [`phase14_sustained_containment_and_rollback_results.json`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_containment_and_rollback_results.json) | `ad5a2c20624d7756f7396c0d80e8cb1f4092b772097e3be977f68c353ec22031` | Safety & Rollback Data |
| [`phase14_sustained_accepted_throughput_comparison.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_accepted_throughput_comparison.md) | `5ceef91dfb6ba9633e9d8e7eb68b37e909a3fc3d2d46e297be8fe4ca004df842` | Analytical Report |
| [`phase14_sustained_arrival_schedule_and_corpus.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_arrival_schedule_and_corpus.md) | `aa9489f66089e02316e6f54dddeba403bf6d5386fae8df3114d64024348639ce` | Analytical Report |
| [`phase14_sustained_measurement_definitions.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_measurement_definitions.md) | `50e1ee2256b823b1dc32f913d09a25b1be28108c4cb79133857e5d2334f4f346` | Analytical Report |
| [`phase14_sustained_preflight_and_baseline.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_preflight_and_baseline.md) | `451c045b85e0bc875b14421b8c0a87677bf1b2c451db60a80e154884c56891eb` | Analytical Report |
| [`phase14_sustained_production_noninterference.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_production_noninterference.md) | `faec2b55f1b265691e813f3ae104396dc79dca68ca7cc347bb4ee16ae14c62c9` | Analytical Report |
| [`phase14_sustained_queue_stability_analysis.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_queue_stability_analysis.md) | `4c84964177d61aeeb2b4b455dc875905d5494cbbf85890cbe44431e549d41d13` | Analytical Report |
| [`phase14_sustained_rollback_and_failure_injection.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_rollback_and_failure_injection.md) | `1eb43b593644f6f7902640aa91fc4ec4846ae72635bc5ba96bc63eb2b8dcfe7d` | Analytical Report |
| [`phase14_sustained_security_and_containment.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_security_and_containment.md) | `168677c7f7bc863ff102830f6b39ec4e3d368e7343e86c0500e57209d13c726a` | Analytical Report |
| [`phase14_sustained_statistical_analysis_and_limitations.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_statistical_analysis_and_limitations.md) | `8f5d0239cf32ebdf0aa8b0efdfa4db95764d262da3c9b7e7cc996c56784e1b8b` | Analytical Report |
| [`phase14_sustained_tail_latency_and_resources.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_tail_latency_and_resources.md) | `f0bb5d564fa72a728b7b255e2d14cb3c0b1156543b5a198c617eb04ffef574c8` | Analytical Report |
| [`phase14_sustained_workload_design.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_workload_design.md) | `ca0cb5d6e273063f68d66df215ecf31d044f56f8f537dbb0e8c87f9754f2fc12` | Analytical Report |
| [`phase14_sustained_final_disposition.md`](file:///home/mike/Projects/aihost/phase14/evidence/phase14_sustained_final_disposition.md) | `8dfd2eb8f4201be4a2dc2ae1bc79a781b0a501bf26e45f9bf35a4d623b3eb6c3` | Terminal Report |

---

## 2. Underlying Container and Physical Model Identities

The physical infrastructure executing all requests during the campaign window consisted of:

- **Worker 1 (Lead Engine):**
  - Podman Container ID: `00b04abc9e05bee377f45b3f0208d1611576cd4363d0b45b3a80174f19700d56`
  - Image: `docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d`
  - Model: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (revision `4bd30395b72ea6045edd04806c4fea448d4467b3`)
  - Target: Intel Arc A770 (Device 0, BDF `0000:03:00.0`, tile 0), port 8000.
- **Worker 2 (Specialist Engine):**
  - Podman Container ID: `09dc5f67cf27d4418fa6a33ec3120bb953a8527d3cd034c3ecf0b8b0e1141918`
  - Image: `docker.io/vllm/vllm-openai-xpu@sha256:4bdfd5b928b4a6a95c92b1edc861f13587a797a32db8c1bc96ca4e2c0d58629d`
  - Model: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (revision `4bd30395b72ea6045edd04806c4fea448d4467b3`)
  - Target: Intel Arc A770 (Device 1, BDF `0000:04:00.0`, tile 1), port 8001.
- **Production Gateway:**
  - Systemd Service: `aihost-orchestrator-gateway.service` (PID 3542340)
  - Release Path: `/var/lib/aihost/releases/t5820-gateway-e523f9a`
  - Client Credential Drop-in: `10-t5820-opencode-client.conf`
