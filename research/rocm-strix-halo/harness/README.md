# ROCm Strix Halo harness

Wrappers in this directory should invoke
`../../sycl-optimization/harness/engine_sweep_client.py` for timed sweeps against
`127.0.0.1:<port>` (OpenAI-compatible chat completions). Use curl-based smoke helpers
for quick health and probe checks before deeper runs.

## gfx1151 starting points

| Engine | Notes |
| --- | --- |
| **llama.cpp** | CMake: `-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1151` |
| **vLLM** | Prefer `TRITON_ATTN`; do not assume `FLASH_ATTN` on this stack |
| **SGLang** | May be unavailable on stock ROCm 7.2 — record **unavailable** with evidence; do not invent zero tok/s |

If an engine cannot start in container or native form, archive the blocker under
`evidence/<ts>/` and move on; smoke phase is pass/fail/unavailable, not fabricated metrics.