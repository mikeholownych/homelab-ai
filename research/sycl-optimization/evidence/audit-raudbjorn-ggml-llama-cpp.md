# Audit: Raudbjorn/ggml-llama.cpp

Audit date 2026-11-14. Read-only: cloned, never built or executed (repo contains `.claude/`, `.codex/`, `.gemini/`, `AGENTS.md` agent configs: treated as untrusted, not loaded). Upstream reference: ggml-org/llama.cpp HEAD `a956a852c9c8bc1fb07206364838ddef299178c0` (2026-11-14).

## Identity
| Field | Value |
|---|---|
| Owner (GitHub API) | Raudbjorn (maintainer Sveinbjorn Geirsson); `fork:true`, parent `ggml-org/llama.cpp` |
| Default branch | master |
| Pinned HEAD | `ee4b97ca6a7cb939d59fd55ac09b472d746995c8` (2026-10-12 21:21 UTC, "Resync upstream while preserving fork backends and runtime extensions (#109)") |
| GitHub pushed_at | 2026-10-13; open issues 8 (e.g. #108 "MoE offload: routing traces, static expert packs, CPU TP, opt-in async CPU splits", #91 Qwen4Exp MTP fit estimates, #92 xe/A770 ccs_mode) |
| License | MIT (inherited, `LICENSE` present, "The ggml authors") |
| Merge-base with upstream master | `81bc6b83f827df746eb129235488d325c49cae52` (2026-09-26, "jinja : implement sameas test (#29448)") |
| Divergence | HEAD is 1137 commits ahead of / 1187 behind the *current* upstream master (history is merge/"sanitized snapshot" based, counts inflated). Fork has been out of sync with upstream since the 2026-10-12 resync (upstream snapshot actually merged ~2026-09-01 per commit 08d0baaca). Upstream has moved ~1500 commits since the 09-09 era including every SYCL change listed below. |
| Total diff vs merge-base | 11783 files (mostly 8695 files under docs/benchmarks; LFS used), +1.84M/-514K; code diff much smaller: ggml/src ~1052 files incl. generated template-instance stubs. Scoped: ggml-sycl 89 files +10769/-1017; src/ + ggml-cpu MoE: llama-moe-cache.{cpp,h} (+639), llama-kv-cache.cpp (+980), 6 model files. |
| Authorship | 48 of 50 commits since merge-base by the single maintainer, with heavy AI-agent tooling (agents rosters, "Assisted-by" style). |
| Target hardware | Intel Arc A770 (DG2 / Alchemist), NOT Battlemage. All benchmarks are A770 (16 GB). Unmerged branch `MoE-offload-prefill-optimizations` (115 commits ahead, head `36628c4e6`, 2026-10-13) not audited. |

## What it really changes (files/functions)
Fork-new files (vs merge-base, verified via `git diff --name-status`): `ggml-sycl/{fused-gemm.cpp,moe-cache.cpp,fattn-xmx.cpp,fattn-grf.hpp,fattn-mkl.hpp,innerq.cpp,turbo-quants.hpp,turbo-wht.cpp,xe-kmd.cpp,xmx-gather.cmake,sycl-mutable-command-list-probe.cpp}`, `ggml-cpu/iqp.{cpp,h}`, `src/llama-moe-cache.{cpp,h}`, `llama-turbo-innerq-runtime.*`, turbo rotation tables, new model files (clef, glm5-next, k2-horizon...), `common/speculative-adaptive.h`.

Technical content:
1. **TurboQuant+ quant types** (the fork's raison d'etre): KV types `turbo2/3/4` (2.125/3.125/4.25 bpw; WHT rotation + polar codebook) and weight types `TQ3_1S`/`TQ4_1S`. README is honest that this is a capacity feature, not a speed feature. SYCL: turbo SET_ROWS/CPY/dequant and WHT op; turbo mmvq kernels are NOT selected by the router; TQ weights have single-token matvec only and **MoE MUL_MAT_ID on TQ types aborts on SYCL** (README + ornith doc section 8). Turbo FA goes through the VEC route; XMX route is opt-in `GGML_SYCL_FA_XMX=1`.
2. **MoE expert cache** (`--moe-cache`, SYCL provider `moe-cache.cpp` + `llama-moe-cache.cpp`): ported from "TheTom's Vulkan expert-cache provider" with a SYCL twin; default off; docs/backend/MOE-CACHE.md admits `--fit` spill decision is disconnected from the provider's real budget, "a real decode regression versus not registering a provider".
3. **Lookahead expert upload on a private SYCL copy queue** (`--prefetch-experts-slots N`), Level Zero v1 only; on DG2+xe needs `UR_L0_USE_COPY_ENGINE=1` which re-triggers blitter (bcs) hangs. `xe-kmd.cpp` sets `UR_L0_USE_COPY_ENGINE=0` by default on DG2.
4. **SYCL perf items ported from others**: grouped MoE XMX GEMM for IQ weights (`fused-gemm.cpp`, port of upstream PR #29245), SYCL graph record-once/replay (upstream #28725 lineage), Q8_0 DMMV ESIMD / wide-load MMVQ, Q5_K reorder MMVQ + fused GLU, fused single-token `mul_mat_id` MMVQ for legacy/K-quant/MXFP4/IQ types, MUL_MAT_ID -1 skip, q8_0 "quants-first" KV row layout (default on; claimed +8..21% decode at depth 4K-16K on A770 only), oneMKL GEMM FA prefill (default on), 256-GRF FA tiles (`GGML_SYCL_FA_LARGE_GRF`, +2.4..10% pp512, opt-in), stream-ordered scheduler input copies (`GGML_SCHED_COPY_SYNC=0`, experimental).
5. **Qwen4Exp MTP head support** (commit 001d906a6), adaptive speculative decoding, chained drafting `--spec-chain`.
6. CPU: `iqp.cpp` IQ batched panel path.
7. Explicitly NOT in tree: sparse-V dequant (README says not implemented), CUDA/HIP/Metal backends, Dockerfiles.

Claim checks:
- "Sparse V dequant described but not implemented": consistent (no code found). Honest.
- "InnerQ off by default, not runtime-proven on A770": consistent with default-off env gate.
- "`GGML_SYCL_XMX_GATHER` AUTO AOT allow-list = bmg-g21, xe2-hpg, pvc, lnl-m" (docs/backend/SYCL.md ~line 833, `xmx-gather.cmake`): **bmg-g31 (B65/B70) is not in the allow-list.** An AOT build for `bmg-g31` with AUTO omits the gather kernels and falls back to regular GEMM (JIT mode with empty arch works). Code elsewhere does handle `intel_gpu_bmg_g31` (fattn.cpp, fattn-vec.hpp, fused-gemm.cpp target macro), so only the AOT gate is the gap.
- Per-feature performance numbers are all A770 and mostly "paired campaign" documents in docs/research/sycl; none on Battlemage. Unverified for B65.
- README's own "Dead ends already measured": SLM centroid LUT dequant, global large-GRF, GPU oneDNN prefill, alternate MMVQ geometry, joint_matrix XMX at sub-group 16 (IGC internal error on A770).

## Upstream status (upstream HEAD a956a852c)
| Fork item | Upstream |
|---|---|
| Grouped MoE XMX GEMM | merged 847f447c3 (#29245, 2026-10-08); plus device-side scheduler 18c5a95e2 (#30156, 2026-11-10); fork's copy is the older port |
| SYCL graph record/replay | merged 7377bada8 (#28725, 2026-10-22) |
| MUL_MAT_ID -1 skip | merged 701fd25b3 |
| Fused MMVQ mul_mat_id incl. reordered Q8_0 MoE | upstream has `ggml_sycl_mul_mat_id_mmvq_fused`; e707790c7 reordered Q8_0 MoE (2026-10-15); q8 fast dequant 0756e83fc; Q5_K wide stores 13de11e78 |
| oneMKL GEMM FA | upstream 9d9a6d29f (2026-07-31) |
| oneDNN SDPA for quantized KV, DPAS FA for quantized KV | upstream 66fa168a5, f7c01c522 (2026-10-29) |
| MoE expert cache | upstream has its own generic `llama-moe-cache` (d6cf9acb2 2026-10-07, multi-GPU c811cb8f0, SLRU 33d6135cb, LRFU c4fb57969, CPU-share e95426f16, graph-sched refactor 951d465f5 2026-11-13) - fork lineage differs (TheTom Vulkan twin) and is superseded |
| Qwen4Exp MTP | upstream a8fad21e9 / 040ce199a etc. |
| TurboQuant KV / TQ weights, WHT op, InnerQ | NOT upstream (`git grep -i 'turbo[234]'` on ggml/src returns nothing) |
| q8_0 quants-first KV layout, 256-GRF FA, XMX FA for turbo, copy-queue expert prefetch, xe-kmd copy-engine workaround, speculative-adaptive | not found upstream |

## Applicability to our hardware/models
- Hardware mismatch: all evidence is A770/DG2; no B-series data; AOT gather allow-list omits bmg-g31; xe copy-engine workaround is DG2-specific (our B65 on xe might not need it, unknown).
- Qwen3 A3B family: the fork's "Ornith-1.5-35B-A3B" (qwen35moe hybrid MoE, Q4_K/Q6_K experts on a 16 GB card) is the closest analogue to Qwen3.6-35B-A3B. Its own conclusion: Q4_K/Q6_K experts take the per-expert loop on SYCL (grouped path is IQ-only on A770), decode is launch-bound (~48 ms/token vs ~22 ms bandwidth floor), `--fit` mis-sees free VRAM. Upstream has since added K-quant grouped XMX (Q4_K/Q5_K/Q6_K gather bits 2048..4096 per upstream SYCL.md) and graphs, so the fork's K-quant "open code item" is already addressed upstream.
- Qwen3.8-Flash-Next (qwen4exp): MTP support exists in fork, also upstream now; the fork's reported A770 data for this model is not present.
- Turbo KV (turbo3) could help only if VRAM-limited; with 64 GB across 2 B65 and A3B model ~21 GB, it is not needed; Qwen-family auto-rewrites K to q8_0 anyway per README; PPL cost +5% on Llama-3.1-8B.
- Quant types: IQ*, K-quants, Q8_0, MXFP4/NVFP4 via fused decode; TQ weights unusable for MoE on SYCL.

## Risks
- Single-maintainer, AI-agent-driven fork; very large unreviewed surface (11.8K files, much of it LFS benchmark data); out of sync with upstream; sanitized-snapshot history makes provenance of ported code hard to audit.
- MoE cache default-off for good reason (can regress decode with `--fit`).
- Copy-queue prefetch is L0 v1 only; interacts with a known xe blitter hang on DG2.
- Fork-only types (turbo/TQ) make GGUFs incompatible with upstream builds.
- Docs claim "paired" campaigns but only on A770; none reproduced by us.

## Testable hypothesis
H1: Upstream HEAD already contains the fork's generic SYCL wins; therefore an upstream-HEAD build with `GGML_SYCL_DEVICE_ARCH=bmg-g31`, graphs on (`GGML_SYCL_ENABLE_GRAPH=1`) and XMX gather defaults will match or exceed the fork on Qwen3.6-35B-A3B Q4_K_M. Test only upstream builds.
H2: The q8_0 quants-first KV layout (+8..21% decode at 4-16K depth on A770) is the only fork-only throughput idea plausibly transferable; test by porting the single commit idea (`GGML_SYCL_Q8_KV_QUANTS_FIRST`) to an upstream branch and A/B on B65 with `-ctk q8_0 -ctv q8_0` at 8K/16K depth. Expect smaller effect on Xe2 where upstream FA TILE is already preferred for quantized KV.
H3: `UR_L0_USE_IMMEDIATE_COMMANDLISTS=0 UR_L0_BATCH_SIZE=64` (fork note: +32% tg128 on dense Mistral-7B/A770, unmeasured on MoE/B-series) is a cheap env-only experiment on upstream; independent of this repo's code.

## Verdict
- SYCL MoE/MMVQ/graph/grouped-GEMM items: **Already upstream**.
- MoE expert cache and expert prefetch: **Already upstream** (different, generic, multi-GPU implementation; fork's is superseded) / prefetch **Incompatible** (DG2 copy-engine workaround, L0 v1 only).
- TurboQuant KV/TQ weights: **Different arch only / Unproven** (A770 evidence only; capacity not speed; TQ MoE aborts on SYCL).
- q8_0 quants-first KV, 256-GRF FA, XMX turbo FA: **Applicable after modification** only as small experiments, **Unproven** on B65.
- Whole fork as a build base: **Incompatible** (A770-targeted, stale vs upstream, bmg-g31 missing from AOT gather allow-list).
