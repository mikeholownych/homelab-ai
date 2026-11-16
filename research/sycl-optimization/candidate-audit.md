# Candidate audit

| Candidate | Source | Runtime stack | Env | Status |
|---|---|---|---|---|
| deployed (baseline) | b11347 `5fc4f3c8` | oneAPI 2026.1.1, image digest `sha256:2f494061...` | defaults | production |
| head-a956a852 | HEAD 2026-11-14 | oneAPI 2026.2.0, oneDNN 2026.1.0, IGC 2.42.6, NEO 26.40 | defaults | rejected: 32K prefill -15% (Coder), ESIMD MoE regression (#31068) |
| head-stackB | HEAD a956a852 | oneDNN 2026.1.0 + IGC 2.34.4 / NEO 26.18 / IGDGMM 22.10.0 (pinned) | `GGML_SYCL_ENABLE_XMX_ESIMD=0` | **gated, not deployed** (see `integration-recommendations.md`) |
| head-stackA/oldstack/revert30156, bisect-* | bisect images | various | - | diagnostic only, never deploy |

Gate status for head-stackB: throughput and KL pass on Qwen3.6, Coder-30B, Flash-Next; engx pass on Qwen3.6 and Coder-30B (not worse);
Flash-Next engx in progress; not covered: gateway latency, failure injection, `-np 2`, Ansible pin + rollback, soak.
Supply chain: stack versions come from upstream `.devops/intel.Dockerfile` history; the old IGC/NEO pair is an unsupported hold position.
