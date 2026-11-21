# SGLang: UNAVAILABLE on gfx1151 / ROCm 7.2.0 (Phase 2b smoke)

**Status: `unavailable`.** No throughput or latency numbers exist or are implied.
SGLang is dropped from the deep bake-off unless the operator expands scope
(for example a source build of `sgl-kernel`/`aiter` for gfx1151, or a newer host ROCm;
neither was attempted, per campaign constraints).

Image: `docker.io/lmsysorg/sglang@sha256:a3a6eb293187b20012a5abc8f00423e6ab51d0169113a6e58a91da5614200170`
(tag `v0.5.23-rocm720-mi30x`, ROCm 7.2.0 userspace). lmsysorg publishes ROCm images only
for MI30x/MI35x (gfx942/gfx950); no gfx1151 SGLang image exists on Docker Hub
(`kyuz0/*` has vLLM and llama.cpp gfx1151 images, no SGLang). Model: Qwen3-4B-Instruct-2507
(HF BF16), probe only; the mid-size model was skipped because the failure is systemic.
Run command for every attempt: `<attempt>/run_cmd.txt`; logs: `<attempt>/container.log`.
`HSA_OVERRIDE_GFX_VERSION` was not set; the host ROCm was not touched.

| # | Directory | Change | Outcome |
| --- | --- | --- | --- |
| 1 | `probe-attempt1-oom-default-memfrac` | defaults + `--attention-backend triton` | Weights load (7.9 GB). `HIP out of memory` allocating the KV pool: SGLang sees ~115 GB (RAM+GTT) on the APU and sizes the pool from that; the real pool is 61.35 GiB. Tunable, not the blocker. |
| 2 | `probe-attempt2-aiter-cudagraph-build-fail` | `--mem-fraction-static 0.3 --max-total-tokens 32768` | KV pool OK. aiter prebuilt `.so` targets gfx942 only, so it JIT-rebuilds for gfx1151; hipcc fails with `'__builtin_amdgcn_cvt_pk_fp8_f32' needs target feature fp8-conversion-insts`. CUDA-graph capture aborts, server exits. |
| 3 | `probe-attempt3-nocudagraph-aiter-gemm-segfault` | + `--cuda-graph-backend-decode disabled` | Server listens and `/v1/models` is 200. First request segfaults in the aiter bf16 GEMM (gfx942 prebuilt kernel); the scheduler dies and the request hangs until the 300 s client timeout. |
| 4 | `probe-attempt4-aiter-off-sgl_kernel-rotary-segfault` | + `SGLANG_USE_AITER=0` | Same pattern: segfault in `sgl_kernel.rotary_embedding` (prebuilt gfx942 kernels); request hangs until timeout. |

Root cause: the image's native kernels (`aiter`, `sgl_kernel`) are compiled for gfx942.
Plain PyTorch ops and Triton work on gfx1151 (weights load, KV cache allocates), but the
fused kernels SGLang calls on the forward path crash or fail to compile. Attempts 3 and 4
did start an HTTP server, but no completion was ever produced, so there is no valid result.
