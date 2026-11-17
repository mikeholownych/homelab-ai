# Audit: snailium/llama.cpp-sycl-intel-b70

Audit date 2026-11-14. Read-only: cloned, never built or executed (Dockerfile/CI/scripts only read). Upstream reference: ggml-org/llama.cpp HEAD `a956a852c9c8bc1fb07206364838ddef299178c0` (2026-11-14).

## Identity
| Field | Value |
|---|---|
| Owner (GitHub API) | snailium; NOT a GitHub fork (`fork:false`, parent null); 11 stars; 2 open issues (#43 dev image ready, #37 request for B70 compute check) |
| Default branch | main (also `dev`) |
| Pinned HEAD | `d384a9136f7fb5ce31cd736efd467c1135ca2407` (2026-11-13 12:18 UTC, github-actions[bot] "build(stable): auto-advance vendored subtree to v1.0.0") |
| GitHub pushed_at | 2026-11-14 05:02 UTC (active; bots advance the vendored tree) |
| Commits | 89 |
| License | MIT ("Copyright (c) 2026 Snailium and contributors"; vendored llama.cpp keeps its own MIT LICENSE) |
| What it is | A Docker packaging/CI repo around a **vendored, unmodified copy of upstream llama.cpp**. `llama.cpp/.subtree-upstream` records tag v1.0.0, b12359, commit `b1b770d90d94cad9e9ea5b993bdbc383a522fb28` ("examples : remove explict version from test-cmake (#32191)", 2026-11-13). |
| Divergence from upstream | **Zero.** `diff -rq` of the vendored `llama.cpp/` against a worktree of upstream at b1b770d90 (excluding .git and .subtree-upstream) reports no differences (0 lines of output). Upstream at that commit is 28 commits behind HEAD a956a852c. So "no merge-base" is by design: the vendored commit is a squash with no ancestry (README line ~188). No SYCL code is changed by this repo. |

## What it really changes (files/functions)
No source changes to ggml-sycl, MoE, or cache code (verified byte-identical). Its content:
- `.devops/intel.Dockerfile`: builds with `icx/icpx`, `-DGGML_SYCL=ON -DGGML_SYCL_F16=ON -DGGML_SYCL_DEVICE_ARCH=bmg-g31 -DGGML_SYCL_DNN=ON -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON -DGGML_NATIVE=OFF`, AOT for Battlemage G31, no `GGML_SYCL_DISABLE_OPT`. Pins (in-file): ONEAPI 2026.2.0-devel-ubuntu26.04, level-zero 1.32.0, compute-runtime 26.35.39758.10, IGC v2.41.5, igdgmm 22.10.0, with a fix removing the base image's older bundled libigc that shadows the pinned IGC (otherwise AOT fails "Incompatible interface in IGC: IGC_OCL_DEVC"). STATUS.md lists different pins (oneAPI 2026.1.2, IGC v2.40.13, CR 26.31): docs and Dockerfile are inconsistent; the Dockerfile is authoritative.
- CI workflows auto-advance the vendored subtree to the newest upstream release tag (stable) or b tag (dev), rebuild, and benchmark; issue-driven benchmark reports under `benchmark/results/`.
- Docs: GOLDEN-CONFIG.md, B70-TUNING.md, B70-SYCL-KNOWLEDGE.md, B70-MAX-CONTEXT.md, B70-PCIE-LINK-RATE.md, LEVEL-ZERO-VERSION-DISCREPANCY.md, incident writeups.

Claims verified or refuted against code:
- "SYCL matmul path does not use B70 XMX (upstream TODO)" (STATUS.md, B70-SYCL-KNOWLEDGE section 7): **FALSE/STALE for the code it vendors.** The same vendored tree contains `fused-gemm.cpp` (grouped MoE XMX GEMM using `joint_matrix`) and `fattn-dpas.cpp` (DPAS FA). The note was last updated 2026-09-24, before upstream #29245 (2026-10-08) and DPAS FA (2026-10-29); it is true only for dense MUL_MAT.
- "Building upstream llama.cpp with oneAPI 2026.1 yourself fails (ggml_sycl_init, NEO assertion)": contradicted by the da3dsoul repo, which builds and runs on B70 with oneAPI 2026.1.1 plus IGC 2.34.4 / compute-runtime 26.18 (different driver stack, so not a direct refutation; the "version triangle" is a driver-compat issue, not a source issue). Treat as unverified generalization.
- `SYCL_CACHE_PERSISTENT=0` mandatory (SIGSEGV with =1 on Xe2 under 2026 oneAPI): plausible, from their incident notes; unverified by us.
- Performance: Qwen3.8-27B (DENSE) Q4_K_M + Q8_0 MTP draft, MTP3, q8_0 KV, 128K ctx on one B70: prefill 440-530 tok/s, decode 40-45 tok/s short, ~21 tok/s deep (self-reported, golden config; evidence in `benchmark/results/`). Decode at depth ~21-25 ns per KV position per full-attention layer, same on Vulkan and SYCL (upstream issue #26581 cited).
- B70-PCIE-LINK-RATE.md: valuable operational note: B70 sits behind an Intel PCIe switch; read the *switch upstream port* link (their box: 16 GT/s x8 downgraded), not the endpoint (reports 2.5GT/s x1, misleading).
- `pcie_aspm=off` mitigation for card dropout on a B450 board (board-specific).

## Upstream status
Everything built is upstream by construction (it IS upstream at v1.0.0 / b12359). Relevant upstream features present in that vendored tree: grouped MoE XMX GEMM (#29245), device-side MoE scheduler (18c5a95e2 verified an ancestor of b1b770d90 via `git merge-base --is-ancestor`), sparse FA, graphs, MoE cache, DPAS FA for quantized KV, qwen4exp support and MTP.
Their image therefore is a convenient reference build, not a source of new optimizations.

## Applicability to our hardware/models
- Hardware: exactly our GPU die family (B70 = BMG-G31; B65 same die, fewer EUs). Single B70 only; their host is an AMD B450 platform with the card running at PCIe 4.0 x8 via a switch; ours is Gen3 x16 on 2 GPUs. No multi-GPU data (they say "improve docs for multi-GPU" is a wanted contribution).
- Models: dense Qwen3.8-27B + MTP + mmproj. No MoE benchmarks at all, no Qwen3.6-35B-A3B, no Qwen3.8-Flash-Next hybrid arch. So nothing here validates MoE performance.
- Useful transferable bits for us: `GGML_SYCL_DEVICE_ARCH=bmg-g31` AOT (avoid JIT startup problems), q8_0 KV for large context, Q8_0 MTP draft quantization to avoid the draft's buffer reserve OOM, `ZES_ENABLE_SYSMAN=1`, `SYCL_CACHE_PERSISTENT=0`, driver "triangle" pins (compute-runtime 26.35, IGC 2.41.5, L0 1.32.0), PCIe link-reading rule. These are config knowledge, all env/build-level.

## Risks
- Bot-advanced vendored tree and auto-promoted "stable": no human review gate on upstream changes; image tags move.
- Docs drift (pins, XMX claim) and mixed historical/current guidance.
- "Prebuilt only" advice and `docker` workflow is not ours; ghcr images are third-party binaries (not audited, not pulled).
- Single-card, single-model (dense 27B), single host (B450) evidence; stability issues are board-specific.

## Testable hypothesis
H1: On our 2x B65 host, an upstream-HEAD build using this Dockerfile's flags (AOT `bmg-g31`, `GGML_SYCL_DNN=ON`, `GGML_SYCL_F16=ON`, oneAPI/IGC/CR pins as listed) starts without JIT crashes and runs Qwen3.6-35B-A3B with the XMX grouped MoE path active (check `fg_pick_combo` log line). Tests build/config reproducibility only.
H2: Their claim of ~21 ns per KV position per full-attention layer is architecture-level on BMG; on Qwen3.6-35B-A3B (hybrid GDN, few full-attn layers) the deep-context penalty should be much smaller than on dense 27B. Measure decode at 0/32K/128K via the gateway.
H3: PCIe: verify our own link by reading upstream bridge ports (per their note) before attributing any expert-offload slowness to Gen3.

## Verdict
- As optimization source: **Already upstream** (zero code delta; byte-identical to upstream b1b770d90).
- As build/config reference for B70-class (BMG-G31): **Directly applicable** (flags, AOT arch, driver pins), still **Unproven** on 2 GPUs / MoE models.
- Its XMX-not-used claim: **false for current code** (stale).
