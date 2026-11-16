# DRAFT (not filed) — upstream report: SYCL 32K MoE prefill regression with IGC 2.42.6 + NEO 26.40

Status: tracker re-searched 2026-11-16 via `gh api search/issues`; no existing report. Related, different: #31068
(XMX-ESIMD MoE pp slower), #31540 (the CI/Dockerfile bump, closed), #26396 (older 200K prefill regression, closed).
Filing is outward-facing: needs the operator's go-ahead and a review for anything host-identifying before posting.

## Title
SYCL: ~15% lower 32K-token MoE prompt processing on Arc Pro B-series after intel.Dockerfile bump (IGC 2.42.6 / NEO 26.40)

## Summary
Same llama.cpp source (a956a852), same flags, same GGUF; only the Intel runtime packages in the image differ.

## Evidence (Qwen3-Coder-30B-A3B Q4_K_M, 1x Arc Pro B65, `-fa on -b 4096 -ub 2048`, `GGML_SYCL_ENABLE_XMX_ESIMD=0`)
| Image | pp32768 t/s | tg128 t/s |
|---|---|---|
| HEAD + current stack (oneDNN 2026.1.0, IGC 2.42.6, NEO 26.40, IGDGMM 22.10.2, L0 1.34.0) | ~872-895 | ~100 |
| HEAD + old IGC 2.34.4 / NEO 26.18 / IGDGMM 22.10.0 (oneDNN current) | 1079 | 92 |
| HEAD + all old (oneDNN 2026.0.2 too) | 1043 | - |
| HEAD + only old oneDNN | 847 (still bad) | - |
Commit d5bbcd1f3 (#31540) changed the Dockerfile pins; bisecting source commits with each commit's own Dockerfile shows
the step there, and reverting the source change that looked responsible (#30156) did not move it (874 vs 872).
IGC and NEO cannot be split (NEO 26.40 requires IGC >= 2.42.6; NEO 26.18 requires an older IGC), so the culprit is one of the
pair. Short prompts are unaffected or faster; decode is ~7-8% faster on the new stack.

## Ask
Is the long-prefill drop known for IGC 2.42.x / NEO 26.40? Is there a compiler-side setting worth trying?
Not verified: other GPUs, dense models, Windows.
