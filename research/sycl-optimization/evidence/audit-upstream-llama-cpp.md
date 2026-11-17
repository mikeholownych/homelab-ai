# Audit: upstream ggml-org/llama.cpp SYCL backend (as of 2026-11-14)

Method: read-only shallow clone (`--shallow-since=2026-05-14`, 3231 commits) into
`/tmp/claude-1000/-home-mike-Projects-aihost/de5aeb0d-6a66-4967-9930-af7864ff8fcb/scratchpad/audit/llama-cpp/repo`.
"In deployed image" = `git merge-base --is-ancestor <commit> 5fc4f3c8` (verified, not inferred from PR dates).
Nothing was built or executed; no remote host touched. Perf numbers below are PR authors' claims, not ours.

## Identity

| Item | Value |
|---|---|
| Upstream master HEAD | `a956a852c9c8bc1fb07206364838ddef299178c0`, 2026-11-14T18:06:52Z, "Fix ctz64 on 32bit (#32273)" |
| License | MIT |
| Deployed image digest | `sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451` (OCI index, one amd64 manifest `sha256:eb20b12e...366d`) |
| Deployed build (from registry index annotations, anonymous GHCR token, no pull) | `org.opencontainers.image.version = b11347`, `revision = 5fc4f3c8c7103ffd0b7ff5ee4855bcc78a3ed5cd` (2026-10-01 19:07 -0700, "hexagon: install rebuilt HTP skels (#29828)"), created 2026-10-02T06:13:11Z |
| Distance deployed -> HEAD | 1040 commits; 69 of 203 SYCL-path commits since 2026-05-14 are NOT in the image |
| How to reproduce the lookup | `GET https://ghcr.io/v2/ggml-org/llama.cpp/manifests/<digest>` with an anonymous pull token, read `annotations` |

Deployed build config (from `.devops/intel.Dockerfile` at 5fc4f3c8): oneAPI 2026.1.1, IGC v2.34.4, compute-runtime 26.18.38308.1, `GGML_SYCL_F16=ON`, `GGML_SYCL=ON`, `GGML_BACKEND_DL=ON`, no `GGML_SYCL_DEVICE_ARCH` (so SPIR-V JIT, not AOT for bmg-g31). CMake defaults at that commit: `GGML_SYCL_GRAPH=ON` (build), `GGML_SYCL_DNN=ON` (oneDNN), Level Zero API ON.

## What exists (state in deployed b11347 vs HEAD)

| Area | Deployed b11347 (5fc4f3c8) | HEAD (a956a852) |
|---|---|---|
| `mul_mat_id` TG (n_tokens=1) | Fused MMVQ path `ggml_sycl_mul_mat_id_mmvq_fused`; lazy per-expert SoA reorder for Q4_K/Q5_K/Q6_K (#24452), Q8_0 not yet. IQ1_M has a plain (non-reordered) fused MMVQ case (`mmvq.cpp:2883`). | Same, plus reordered Q8_0 MoE (#29337), MXFP4 (#29809). |
| `mul_mat_id` PP (batch) | Host path: copies `ids` to host, `stream->wait()`, counting sort, one `ggml_sycl_mul_mat` per active expert (dequant to f16 + oneDNN/oneMKL GEMM). Counting-sort rewrite (#23142) is in. | Device-side grouped XMX GEMM: #29245 (grouped `joint_matrix` kernels, host schedule) + #30156 (schedule built on GPU, no host sync, graph-safe). `GGML_SYCL_MMID_SCHED=1` default. XMX gather types include Q4_K and IQ1_M (`fused-gemm.hpp:42,72`). |
| MoE up/gate fusion | Dense FFN gate+up+GLU fusion only (`MUL_MAT,MUL_MAT,GLU`, q4_K dense, #26779; Q5_K #29375). Fused top-k MoE routing (#25217). **No fused gate/up for `MUL_MAT_ID`** (grep of fusion paths at 5fc4f3c8 finds none). | Grouped GEMM can be "optionally fused" (#29245 text); `GGML_SYCL_XMX_GLU_MAX_COLS` fused gate+up XMX kernel is for reordered mat-vec (dense), not verified for MoE. |
| Flash attention | Kernels: oneDNN SDPA (#25222, f16 and, via #25874, quantized KV), oneMKL-GEMM FA for prefill (#25025, quantized KV, needs `-b>=1024`, prompt>=1024), TILE and VEC (TILE preferred for quantized-KV decode on bmg_g21/g31, #26689; `fattn_vec_nthreads=256` on BMG #25205), sparse FA (#28796, off by default). | Adds DPAS (XMX) FA kernel reading q4_0/q8_0 KV directly, Xe2+ only, decode and <=31 tokens (#31125, `GGML_SYCL_FA_DPAS=1`). |
| XMX / joint_matrix / oneDNN / sycl-tla | oneDNN (SDPA + GEMM) and oneMKL are the XMX consumers. ESIMD DMMV kernels (Q2_K,Q3_K,Q5_K,Q8_0). **No `joint_matrix` in ggml-sycl at 5fc4f3c8, and no sycl-tla/CUTLASS reference at either 5fc4f3c8 or HEAD** (case-insensitive grep over ggml/src/ggml-sycl and docs/backend). | `joint_matrix` in `fused-gemm.cpp` and `fattn-dpas.cpp`; int8 DPAS multi-column mat-vec (#29864, `GGML_SYCL_ENABLE_XMX_ESIMD`). Still no sycl-tla. |
| SYCL graph | Env `GGML_SYCL_ENABLE_GRAPH`, default 0, doc says "no better performance". | Record/replay merged (#28725, 2026-10-22); still off by default; author: negligible on B70, large on A770. |
| Reorder opt (Q4_0, K-quants) | `GGML_SYCL_ENABLE_OPT`, default 1. **The old name `GGML_SYCL_DISABLE_OPT` no longer exists**: #25042 (2026-07-07) renamed all `DISABLE_*` env vars to `ENABLE_*`; `git grep DISABLE` over ggml-sycl at 5fc4f3c8 returns nothing, so a legacy `GGML_SYCL_DISABLE_OPT=...` in a deployment is silently ignored. | Same. PP regression after Q4_0/Q8_0 reorder fixed (#30374), vectorized dequant stores (#30976). |
| KV-cache quant | Works via FA kernels; q4_0/q4_1/q5_0/q5_1/q8_0 supported (#23812 etc.). | Plus DPAS path (q4_0/q8_0, Xe2+). Issue #26396: oneMKL FA regressed 200K prefill ~35% on B70 (closed; `GGML_SYCL_ENABLE_MKL_FA=0` workaround). |
| Speculative decoding | Backend-agnostic server feature; `--spec-type` incl. `draft-mtp` (#25973 shows B70 + Qwen3.6-35B + MTP in use), recurrent-state rollback `ggml_ssm_scan` (#26623). | More draft types (EAGLE3, DFlash...). Multi-column XMX mat-vec (#29864) targets 2-8 token verification. |
| Prompt/prefix cache | `--cache-reuse`, `--cache-ram`, `--ctx-checkpoints`, slots, `--slot-save-path` are in common/server code, not backend code. Not tested by us on hybrid (GDN) models. | Same flags. |
| Multi-GPU | `--split-mode layer` (default) and `tensor` (#24152, N=2 allreduce, BF16-compressed above 32k elems). `row`: SYCL docs still say "not supported"; `ggml_sycl_mul_mat_id` asserts `!buffer_is_sycl_split` so row split cannot serve MoE. Peer copy (#27550), pinned allreduce (#29604). | Faster `comm_exchange` on B70 (#30956), `set_tensor_2d` for split loading (#30358), device-id caching (#31126, #32013). |
| Expert offload flags | `-cmoe/--cpu-moe`, `-ncmoe/--n-cpu-moe N`, `-ot` present in `common/arg.cpp`; draft-model variants (`-cmoed`, `-ncmoed`) at HEAD. | Same. Irrelevant for our models if both fit in 2x32 GB. |
| Hybrid/GDN ops | `gated_delta_net.cpp` (K>1 #23174), `ssm_conv` fusions, delta-net alpha gate fusion (#29687 is after image). | GDN ESIMD / GET_ROWS fusion only as open PRs. |

## Applicability to this deployment

- Qwen3.6-35B-A3B-UD-Q4_K_M (qwen35moe, GDN hybrid, head_dim 256): TG already uses the reordered fused MMVQ id path. PP uses the host-sync per-expert loop in b11347; HEAD replaces it with the grouped XMX GEMM (Q4_K is a supported gather type). PR #23142 (in image) reported +70% PP on B60 for exactly this model family.
- Qwen3.8-Flash-Next IQ1_M: TG works via non-reordered IQ1_M MMVQ (functional, probably bandwidth-inefficient: no reorder for IQ-types except IQ3). PP at HEAD can use the XMX gather path (IQ1_M bit exists). #29245 measured Qwen3.8-Flash-Next UD-IQ4_XS PP 274 -> 368 tok/s (+34%), decode unchanged (its numbers, different quant and GPU).
- 2x B65 on PCIe Gen3: tensor split depends on allreduce latency; PRs #30956 (merged, after image) and #32058 (open) target this. Layer split is the safe default.
- JIT build: first-run kernel compile cost; the doc advises against `SYCL_CACHE_PERSISTENT=1` (crash reports). AOT (`GGML_SYCL_DEVICE_ARCH`) would require building our own image; valid arch string for B65 (G31) not verified for llama.cpp's CMake (Strata docs use `bmg-g31`).
- Known open driver caveat in the Dockerfile comments: compute-runtime 26.x multi-GPU issue (llama.cpp #21747, intel/compute-runtime #921); image pins 26.18, host kernel driver is `xe`. Not verified which side of that issue we are on.

## PR table

Status "in image" = ancestor of 5fc4f3c8 (verified). Merged date is the master commit date.

### Merged, IN deployed image (b11347)

| PR | Title (short) | Merged | Relevance |
|---|---|---|---|
| #23142 | improve MoE prefill throughput (counting sort, contiguous mapping) | 2026-05-22 | Qwen3.6-35B PP, +70% on B60 claim |
| #24452 | reordered Q4_K/Q5_K/Q6_K MoE MUL_MAT_ID | 2026-06-16 | Q4_K_M experts TG |
| #24676 | fix use-after-free async memcpy in MoE prefill | 2026-06-17 | MoE correctness |
| #24152 | `--split-mode tensor` for SYCL | 2026-06-25 | 2-GPU |
| #25217 | fused top-k MoE | 2026-07-13 | MoE routing |
| #25222 | Flash Attention with XMX via oneDNN | 2026-07-15 | FA on B-series |
| #25205 | fattn_vec_nthreads=256 for Battlemage | 2026-07-14 | BMG |
| #25025 | oneMKL GEMM FA for XMX prefill (quantized KV) | 2026-07-31 | has regression #26396 |
| #25874 | oneDNN SDPA for quantized KV | 2026-08-04 | KV quant |
| #26689 | TILE for quantized KV decode on BMG | 2026-08-28 | BMG |
| #26779 | fuse gate+up+GLU for q4_K dense FFN | 2026-08-14 | dense only |
| #26623 | ssm_scan state rollback (MTP/spec for GDN) | 2026-08-14 | hybrid spec decode |
| #28796 | sparse FA | 2026-09-25 | opt-in |
| #28476 | IQ-type handling for MoE | 2026-09-09 | IQ1_M MoE |
| #28931 | extend MMVQ GLU fusion, rms_norm+scale, ssm_conv+silu | 2026-09-23 | GDN/MoE |
| #28953 | fix B70 allocation error >19.3 GB | 2026-09-17 | big-card alloc |
| #29604 | reduce tensor allreduce sync (pinned host buffers) | 2026-09-30 | tensor split |

### Merged, NOT in deployed image (candidates for a rebuild)

| PR | Title (short) | Merged | Relevance |
|---|---|---|---|
| #29245 | grouped MoE XMX GEMM | 2026-10-08 | MoE PP |
| #30156 | device-side MoE scheduler (graph-safe, lifts multi-GPU graph limits) | 2026-11-10 | MoE PP; claims TG may dip at small inputs |
| #29864 | multi-column XMX int8 mat-vec (spec-decode verify, 2-80 cols) | 2026-10-22 | MTP/spec |
| #31125 | DPAS FA for quantized KV | 2026-10-29 | Xe2 KV-quant decode |
| #28725 | SYCL graph record/replay | 2026-10-22 | negligible on B70 per author |
| #30374 | fix PP regression after Q4_0/Q8_0 reorder | 2026-10-17 | Q4_0/Q8_0 only |
| #30976 | vectorized reordered dequant stores (Q4_0, K-quants, IQ3, MXFP4) | 2026-10-29 | Q4_K PP |
| #29696 | wide stores q4_K/q5_K dequant | 2026-10-16 | Q4_K |
| #29337 | reordered Q8_0 MoE | 2026-10-15 | not our quants |
| #30956 | fast `comm_exchange` on B70s | 2026-11-02 | tensor split |
| #30358 | `set_tensor_2d` for faster split loading | 2026-10-26 | load time |
| #30239 | restore ESIMD kernels on FFN path | 2026-10-18 | +2% dense TG |
| #29186 | Q8_0 DMMV ESIMD / MMVQ wide load | 2026-10-02 | Q8_0 |
| #28985 | do not use slow oneDNN reference matmul/fattn | 2026-10-02 | general |
| #29062 | large register file for D=512 FA vec | 2026-10-02 | D=512 only |
| #29605 | FWHT optimizations | 2026-10-08 | not relevant |
| #29608 | staged bulk uploads via pinned ring (load) | 2026-10-08 | load time |
| #30761 | FLASH_ATTN_EXT failures | 2026-10-29 | correctness |
| #31285 | refuse device buffers exceeding VRAM (BMG workaround) | 2026-11-07 | safety, intel/compute-runtime#1047 |
| #31138 | oneDNN FA cache thread-safety | 2026-11-12 | server concurrency |
| #31574 | un-gate oneDNN fused SDPA for Alchemist | 2026-11-10 | not BMG |

### Open SYCL-relevant PRs (as of 2026-11-14), all unmerged and so not in image

| PR | Title (short) | State | Relevance |
|---|---|---|---|
| #30606 | route BMG D=256 single-query decode to FA vector kernel | open, APPROVED | Qwen3.6 head_dim 256; 832 vs 1150 us at kv=65536 (B70 op-level) |
| #31428 | Grouped XMX GEMM without SLM staging (needs #30156) | open, review required, +1295 lines | MoE PP |
| #32058 | comm_exchange_fast V2 + L0 leak stopgap + Xe2/B70 nsm fix + fusion | open | tensor split; touches leak (oneapi-src/level-zero#556) |
| #31762 | GDN ESIMD kernel (S_v=128, kda=0) | open draft | Qwen3.8-27B pp512 +4.3% (author) |
| #31355 / #31379 | fuse recurrent conv windows / GDN + GET_ROWS | open | hybrid models |
| #31753 | fused ADD+RMS_NORM+MUL | open | small |
| #31748 / #31968 | FA tile large register file / FP16 tile tuning | open (31968 draft) | FA |
| #31536 / #31542 | MKL FA mask-broadcast fix / sinks support | open | FA correctness / gpt-oss |
| #31208 | remove host-wait check from fattn-mkl graph checks | open | graphs |
| #31998 | IQ4_NL/IQ4_XS reorder | open | not our quants |
| #31993 | Q4_0 as u4 in oneDNN GEMM | open | Q4_0 only |
| #27861 | GPU LRU cache for host-offloaded MoE experts | open, generic (llama-context level) | only if `-ncmoe` used |
| #31139 | max-alloc size reporting + split MoE cache groups | open | touches backend API; not SYCL perf |
| #31850 | separate stream for expert H2D copies | open, CUDA env vars | no |
| #29506 | build SYCL backend via ExternalProject | open | build only |

## Risks

- b11347 was built with the `DISABLE`->`ENABLE` env rename already in effect: any legacy env in compose files is dead config.
- HEAD moves fast (~25 SYCL commits/month, many AI-assisted per PR disclosures). No regression soak data; #26396 shows prior regressions hit B70 users. Pin by SHA, not `:latest`.
- #30156 states TG may regress at small inputs; must A/B decode separately.
- Perf claims are mostly B60/B70/B580 single-card; none measured on PCIe Gen3 x16 dual B65.
- `xe` driver 7.0 / compute-runtime version interaction with IGC 2.34 inside the image is unverified.

## Testable hypotheses

H1. Rebuilding at a pinned HEAD SHA (or at least including #29245+#30156) improves PP tok/s on Qwen3.6-35B-A3B Q4_K_M and Flash-Next IQ1_M by >=20% with TG within +-3% (A/B of two pinned images, same flags, via gateway from a remote client; see CLAUDE memory: never run inference on the host directly).
H2. `GGML_SYCL_MMID_SCHED=1` vs `=0` isolates #30156 effect without a rebuild at HEAD.
H3. `GGML_SYCL_XMX_GATHER_TYPES` bitmask excluding IQ1_M shows whether the XMX path helps IQ1_M or hurts (HEAD only).
H4. #30606 helps Qwen3.6 decode at long context (D=256, kv>=32k) on G31; test by cherry-picking onto the pinned base.
H5. Layer vs tensor split on dual B65 over Gen3 x16: tensor split gains only after #30956/#29604 allreduce work; measure both in b11347 and HEAD.
H6. AOT (`GGML_SYCL_DEVICE_ARCH`) removes first-run JIT latency and changes nothing else.

## Verdicts

| Item | Verdict |
|---|---|
| Upstream HEAD SYCL work (#29245, #30156, #29864, #31125, #30956) for our models | **Already upstream** (not yet in deployed image): applicable by rebuild, no code changes |
| #30606, #31428, #32058, #31762 | **Unproven** (open, unmerged; need cherry-pick + A/B) |
| IQ1_M TG efficiency (no reorder for IQ1_M) | **Applicable after modification** (would need a reorder/MMVQ kernel; not upstream) |
| Fused MoE gate+up for `MUL_MAT_ID` | **Unproven** (not found in tree; only dense fusion exists) |
| sycl-tla / CUTLASS path | **Incompatible/absent** (not in ggml-sycl; joint_matrix + oneDNN + ESIMD are the XMX routes) |
| Row split on SYCL | **Incompatible** (docs: unsupported; `mul_mat_id` asserts no split buffers) |
| SYCL graph | **Unproven** for our case (off by default, negligible on B70 per author) |
| `GGML_SYCL_DISABLE_OPT` | **Incompatible** (variable removed; use `GGML_SYCL_ENABLE_OPT`) |
