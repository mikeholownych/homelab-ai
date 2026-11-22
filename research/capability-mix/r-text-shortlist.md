# R-text shortlist (MS-S1)

Plan: `docs/superpowers/plans/2026-11-22-lead-rocm-capability-mix.md` Task 6.
Host: `ai-ms-s1-max-01` (10.0.8.6), llama.cpp HIP image `sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184`.

Order:
1. Qwen3.8-27B Q4_K_M (general; Halo-comfortable). Artifact: `Qwen3.8-27B-UD-Q4_K_M.gguf`
   (sha256 `322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482`, same artifact as the 5820 lead).
2. Gemma 4 31B Q4_K_M (general; HIP/Vulkan smoke required)
3. gpt-oss-20b Q8_0 or Q4 (orchestration-leaning control)
4. gpt-oss-120b Q4 only in a sole-tenant window (would not fit beside the production Coder-30B worker)

Kill: tools broken, OOM at 32k, unusable TTFT for interactive use.
Coding CAIS not required.

## Smoke checklist (per candidate)
1. Load with `-c 65536 -np 1 --jinja -ngl 99` (temp HIP container on a non-production loopback port, beside production Coder-30B).
2. Chat completion OK.
3. Tools schema round-trip OK (`prompts/orch_tools.json`, calculator 17*19 = 323).
4. No HIP correctness nonsense (`HIP_LAUNCH_BLOCKING=1` if batched garbage appears).
5. Record TTFT / tok/s and a >32k prompt check (kill criterion: OOM at 32k).

Production Coder-30B (`llama-hip-qwen3-coder-30b.service`, :8101) is never stopped or replaced by this task.

Results: see `evidence/<UTC>/r-text-*.md`.
