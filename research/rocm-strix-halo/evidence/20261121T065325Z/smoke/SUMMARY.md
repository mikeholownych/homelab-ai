# Phase 2b smoke summary (ai-ms-s1-max-01, ROCm 7.2.0 host, gfx1151)

All engines ran in rootless podman (`--device=/dev/kfd --device=/dev/dri --group-add keep-groups
--net=host`), one at a time with `stop_engine.sh` between runs, without `HSA_OVERRIDE_GFX_VERSION`.
Model files verified (`../downloads.txt`): GGUF sha256 matches the shortlist pins; HF repos were
verified against per-file LFS sha256 at the pinned revisions.

| Engine | Image (digest) | Probe Qwen3-4B | Mid Qwen3-Coder-30B-A3B | Tools |
| --- | --- | --- | --- | --- |
| llama.cpp HIP | `ghcr.io/ggml-org/llama.cpp@sha256:9c44da4d…a4184` (tag `server-rocm`, b12464) | pass (GGUF Q8_0, ctx 8192) | pass (GGUF Q8_0, ctx 16384) | tool_calls on both |
| vLLM ROCm | `docker.io/kyuz0/vllm-therock-gfx1151@sha256:f8a7433d…3966` (vLLM 0.33.0+strix, ROCm 10.0/TheRock userspace in-image) | pass (BF16, ready 113 s) | pass (FP8, `TRITON_ATTN`, ready 164 s, ctx 8192) | tool_calls on both |
| SGLang | `docker.io/lmsysorg/sglang@sha256:a3a6eb29…0170` (v0.5.23-rocm720-mi30x) | **unavailable** | not attempted (systemic) | n/a |

Peak GTT used while serving: llama.cpp probe 5.8 GB, llama.cpp mid 34.2 GB, vLLM probe 32.5 GB
(`--gpu-memory-utilization 0.5`), vLLM mid 46.2 GB (`0.7`). See each `rocm_mem.txt`.

Timings here are single-request smoke latencies, not benchmarks, and are not comparable across
engines (the vLLM numbers include a Triton JIT warmup spike on the first request).

SGLang: see `sglang/UNAVAILABLE.md`; the per-attempt `status.json` files under `sglang/` come from
the harness heuristics and are superseded by `sglang/status.json`.
