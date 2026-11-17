# Audit: da3dsoul/Qwen3.8-Flash-Next-LlamaCpp-MoE-Cache-Arc-Experiments

Audit date 2026-11-14. Read-only: cloned, never built or executed. All "measured" numbers below are the repo author's claims from logs/docs in the repo; none were reproduced by us.
Local clone: `.../scratchpad/audit/qwen-flash/r`. Upstream comparison clone: `.../scratchpad/audit/upstream/u` (ggml-org/llama.cpp HEAD a956a852c9c8bc1fb07206364838ddef299178c0, 2026-11-14).

## Identity
| Field | Value |
|---|---|
| Owner (verified via GitHub API) | da3dsoul (not a fork; `fork:false`, no parent) |
| Default branch | master |
| Pinned HEAD | `689d417569b12b8be39d01121998c883811d0647` |
| Last commit | 2026-10-11 20:34 -0400 ("Add the production stack: deploy/ compose, ...") |
| Commits | 14 (2026-09-09 .. 2026-10-11) |
| License | NONE (no LICENSE file; GitHub license = null; README/PLAN have no license statement). Default = all rights reserved. The patch is a derivative of MIT llama.cpp, but the author's own additions carry no grant. |
| Open issues | 0 |
| Repo shape | NOT a llama.cpp fork. It contains no llama.cpp source. Code lives in `patches/llama.cpp.patch` (932 KB, 86 files, +15057/-645) plus `patches/ws-*.patch` and `kexp-*.patch` (workstream slices), docs (`docs/research/*`, `PLAN.md` 226 KB), Dockerfiles, bench drivers under `staging/work/`, and logs. |
| Base commit of patch | upstream `6d9c82ea2bb34e277c0664b8dd3434bfb4dcfb27` (2026-09-09). Verified: `git apply --check` succeeds cleanly at that commit in a throwaway worktree. |
| Divergence from upstream | Base is 1505 commits behind upstream HEAD. `git apply --check` of the patch against upstream HEAD fails with 68 conflict/"does not apply" hits, so it cannot be applied as-is. |

## What it really changes (files/functions)
Verified by reading the patch hunks and per-file added-line counts (largest first):
- `ggml/src/ggml-sycl/ggml-sycl.cpp` +1829: device-planned fused MUL_MAT_ID path (`ggml_sycl_mul_mat_id_device_planned_fused`, decode-only, requires `ne12==1`), small-N routing (`GGML_SYCL_MMID_SMALLN`), op profiler, graph/launch tweaks.
- `moe-cache.{cpp,hpp}` (new, +1541/+235): SYCL dynamic MoE expert cache (hot slots in VRAM, cold in pinned host), env-configured (`GGML_SYCL_MOE_CACHE_SIZE`, interim mechanism, "not a real CLI flag yet"), optional prefetch (`GGML_SYCL_MOE_PREFETCH`), async mode, verify mode. `expert-pool.{cpp,hpp}`, `mmid-hybrid.{cpp,hpp}` + `ggml-mmid-hybrid.h` (hybrid CPU/GPU MUL_MAT_ID, from RFC upstream #24528).
- `fused-gemm.{cpp,hpp}` (new, +1140): hand-merge of upstream PR #29245 grouped MoE XMX GEMM (joint_matrix; IQ types, then Q8_0/Q4_K/Q5_K/Q6_K via `GGML_SYCL_XMX_GATHER_TYPES`).
- `mmvq.cpp` +303, `mmv_bf16.hpp` +274, `mmv_q8.hpp` +174 (new): small-N fused MoE GEMV (2<=N<=4 independent decode rows), split-K BF16 GEMV (claimed +25% decode), split-K Q8_0 GEMV for dense BF16->Q8_0 tensors; `spill_guard.hpp` (register spill checker).
- `fattn-sparse.{cpp,hpp}`, `fattn-common.hpp`, `fattn-onednn.cpp`: QSA (Qwen sparse-attention lightning indexer) sparse flash attention incl. multi-row (4/8 rows) variant; `topk-radix.{cpp,hpp}` (TOP_K radix select, needed by QSA); `hyper_connect.{cpp,hpp}` (qwen4exp hyper-connection fusion).
- `ggml-cpu/arch/x86/quants.c` +444, `iqp.cpp`, `ggml-cpu.c`, `ops.cpp`: AVX-512 (VBMI/VNNI) dots for IQ2_S/IQ2_XXS/Q2_0, IQ batched panel `mul_mat_id` fast path, expert repack (aligned SoA).
- `src/models/qwen4exp.cpp` +421, `src/llama-memory-hybrid-idx.cpp` +712 (qwen4exp MTP head support, QSA index cache), `llama-kv-cache.cpp`, `llama-memory-recurrent.cpp`.
- `tools/server/*` (+~2000): `--context-tiers CTX:UB:NCMOE,...` dynamic reload into larger context tiers with more CPU experts, `--fork-min-tokens` (prefix fork from a live slot), disk-backed prompt cache for conversation persistence, ctx checkpoints, ngram-mod spec.
- `common/arg.cpp`: exposes device "extra" buffer types to `-ot`.

Author's own findings (docs, not reproduced):
- Custom MoE cache works and is bit-correct but only TIES static `-ncmoe` ("headline finding #1"). Prefetch (doc 22: net loss +18-26 ms/token), plan kernel (doc 23: not a lever), multi-token cache (doc 26: static beat it by 6-28%) are "validated, measured as not worth enabling, left in the tree inactive". Cache has no prefill path (3.8 tok/s vs 366 for -ncmoe) and cannot serve MTP/np>1 verify batches. Hence production uses stock `-ncmoe`.
- Int8 XMX expert GEMM: measured no-go (doc 36-i8g): grouped GEMM reaches 0.3-7% of XMX peak, bound by weight decode + SLM/barrier structure, not DPAS.
- SYCL graphs: -1% (doc 36-lo); launch overhead only ~3.5 ms of a 31.5 ms step.
- Toolchain: oneAPI 2025.3.x returns 0 `matrix_combinations` for bmg_g31 so every joint_matrix kernel silently declined; 2026.0.0+ returns 53. With 2026.1.1 grouped MoE GEMM fires on 100% of prefill MUL_MAT_ID and gives +25.8% prefill at 116K (468 vs 371 tok/s). Probe logs in `logs/oneapi-bump/`. Plausible and internally consistent; but note the upstream sycl_hw/fused-gemm now handles bmg_g31 natively.
- Throughput on B70 (author): 34 tok/s single stream decode, ~60 tok/s aggregate 4 streams, prefill 460-640 tok/s, for Qwen3.8-Flash-Next IQ2_XS (68 GB GGUF, 18-27 expert layers kept on CPU).
- Build-environment trap: identical source built in a different image gave a 2.7x slower IQ4_XS kernel; the shipped image copies prebuilt binaries. This is a reproducibility red flag (we cannot assume a build from the patch matches claims).

README claim checks:
- "67 modified files + 19 new" -> patch shows 86 files; consistent. Verified.
- "MoE cache ties -ncmoe" -> stated by the author, backed by docs; not reproduced by us.
- "+26% prefill from grouped GEMM" -> the PR is upstream, mechanism verified in upstream source; the +26% number itself unreproduced.
- README says `-ncmoe` is "a stock upstream flag, zero custom code": true (upstream `--n-cpu-moe`).
- Production flags (`-ctk q4_0 -ctv q4_0`, `--rope-scaling yarn` at scale 1.0001, etc.) are tuned to the single B70 + 128 GB host + kernel 7.0; none verified on 2 GPUs.

## Upstream status (ggml-org/llama.cpp HEAD a956a852c, checked via git log/grep on our clone)
| Piece | Upstream? |
|---|---|
| qwen4exp (Qwen3.8-Flash-Next) model | YES: 6c84c7d5d (#27742, 2026-08-27) + 36b101543, 0eadefebd (rollback), qwen4exp conv-state commits. MTP: 040ce199a, a8fad21e9 (2026-11-09), 7f51953d7 |
| Grouped MoE XMX GEMM (#29245) | YES: 847f447c3 (2026-10-08); `fused-gemm.cpp` has explicit `__SYCL_TARGET_INTEL_GPU_BMG_G31__` |
| Device-side MoE scheduler | YES: 18c5a95e2 (#30156, 2026-11-10), by cwriter |
| Sparse FA (QSA) for SYCL | YES, different implementation: cd74ef627 (#28796, 2026-09-25), `fattn-sparse.cpp`, `GGML_SYCL_SPARSE_FA`. Repo's multi-row variant not verified upstream |
| TOP_K radix select | YES: 21f6b0d22 (#28670) `topk-radix.cpp` |
| MoE expert cache (host->VRAM hot cache) | YES, different design: `src/llama-moe-cache.{cpp,h}`, d6cf9acb2 (2026-10-07), multi-GPU c811cb8f0, SLRU 33d6135cb, LRFU/MQ c4fb57969, CPU-share `--moe-cache-cpu-share` e95426f16, docs/moe-cache.md. Backend-generic, usable with multiple GPUs. The repo's SYCL-specific cache is superseded |
| SYCL graph record/replay | YES: 7377bada8 (#28725) |
| MUL_MAT_ID -1 skip | YES: 701fd25b3 |
| DPAS FA for quantized KV | YES: f7c01c522 (2026-10-29) |
| Small-N fused MoE GEMV (`GGML_SYCL_MMID_SMALLN`), split-K BF16 GEMV, Q8_0 dense GEMV, spill_guard | NOT found upstream (grep on ggml-sycl for MMID_SMALLN/SPILL_CHECK returns nothing). Unverified that no equivalent exists under other names |
| AVX-512 IQ2_S/IQ2_XXS/Q2_0 CPU dots, IQ expert repack | Not found upstream (upstream has only the baseline IQ2_S x86 dot). Applies to very-low-bit quants only |
| `--context-tiers`, `--fork-min-tokens`, disk prompt cache | Not upstream (upstream has `--slot-save-path` only). Server-level features, not kernels |

## Applicability to our hardware/models
- Hardware: same die family as B65 (BMG-G31) and same driver stack (xe, Ubuntu); single card only, host 128 GB, kernel 7.0. Nothing multi-GPU. PCIe link of the author's host is not documented in the files I read; our Gen3 x16 (~12-13 GB/s real) would be harsher on any CPU-expert upload path, and the author's own result is that the PCIe-bound cache did NOT beat static placement even on their link.
- Qwen3.6-35B-A3B (Qwen3 MoE A3B family): the repo only uses it as a small stand-in test model (21 GiB, `-ngl 0` harness checks); no performance numbers for it as a target. Pieces that generically help any MUL_MAT_ID MoE on SYCL (grouped XMX GEMM, device scheduler, graphs) are already upstream. Quant coverage of the fork-only kernels is IQ2_S/IQ2_XXS/IQ1_M/Q2_0/IQ4_XS-class; Q4_K_M experts for A3B are covered by upstream XMX gather bitmask (Q4_K bit 2048) not by this patch.
- Qwen3.8-Flash-Next (qwen4exp hybrid GDN+MoE+hyper-connection): this is the repo's actual target and the only place the QSA sparse FA, hyper_connect fusion, MTP head and context-tier work matter. The model itself is already supported upstream (see table); the fork-specific gains are on top of that.
- 2x B65 (64 GB total VRAM): the tiering logic exists specifically because 1x32 GB cannot hold the model; with 2 GPUs it may be moot. Patch has no tensor/layer-split awareness (author tested single card only).

## Risks
- No license: cannot legally copy or redistribute the author's code into our tree; can only reimplement ideas.
- Patch base is 1505 commits stale and does not apply to current master (68 conflicts); upstream SYCL code was heavily rewritten (graphs, MoE scheduler, reorder, DPAS FA).
- Reproducibility: build-environment trap (2.7x slower kernel), prebuilt-binary workflow, one unexplained hang accepted into production (watchdog container added), MTP+K-quant 7x cliff unresolved.
- Numbers are single-host, single-GPU, one model; run-to-run spread of 1.5x on 600K decode noted by the author.
- Sleeping/gate containers, litellm hooks, watchdog: operational stack irrelevant to us and not audited for security (not executed).
- 32 GB-specific context tiers; `-ncmoe` values are VRAM-tuned.

## Testable hypothesis
H1: On our 2x B65, Qwen3.6-35B-A3B Q4_K_M with stock upstream HEAD (grouped XMX GEMM + device MoE scheduler + graphs) matches or beats this repo's claimed prefill gain (+26%) without any patch; verify via `llama-bench -p 2048 -n 128` toggling `GGML_SYCL_FG_*`/XMX gather bits and graph env on upstream builds only (via gateway, per our rules; not on the aihost).
H2: Static `--n-cpu-moe` vs upstream `--moe-cache-mib` only matters if experts spill to host; with 64 GB across 2 GPUs A3B Q4_K_M (~21 GB) fits fully, so H2 is expected null (nothing to cache).
H3 (low priority): small-N MoE GEMV only helps concurrent independent decode rows (-np>=2). If we serve concurrent requests, test an upstream re-implementation idea, not this code.

## Verdict
- Overall: **Already upstream** for the MoE-relevant pieces (grouped XMX GEMM, MoE cache concept, qwen4exp, sparse FA, graphs); remaining fork-only items (small-N MoE GEMV, BF16/Q8 split-K GEMV, AVX-512 IQ2 CPU dots, context-tiers, prefix fork, prompt-cache) are **Different arch only / Unproven** for Qwen3.6-35B-A3B Q4_K_M on 2x B65. Not directly applicable; no license; do not adopt the patch.
- Qwen3.8-Flash-Next specific tuning: **Applicable after modification** (would need rebase onto current master and re-proving, and license clearance) - low priority since upstream already runs qwen4exp.
