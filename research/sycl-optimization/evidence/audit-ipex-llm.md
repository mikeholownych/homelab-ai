# Audit: intel/ipex-llm (llama.cpp / Ollama portable part)

Method: shallow clone into `.../scratchpad/audit/ipex-llm/repo` (read only, nothing executed), `gh` API for repo/release metadata, comparison against upstream llama.cpp history. No remote host touched.

## Identity

| Item | Value |
|---|---|
| Repo | https://github.com/intel/ipex-llm (also a fork-mirror `ipex-llm/ipex-llm`, last push 2025-04-27, not archived but stale) |
| Status | **Archived** (`isArchived: true`). README top: "THIS PROJECT IS ARCHIVED ... Patches ... no longer accepted ... has been identified as having known security issues." Archive-notice commit added 5 lines to README. |
| HEAD | `de6bce27133ab250f13fd5d549c197519ce16d30`, 2026-01-28, "Update README.md" (archive notice). |
| Last substantive commit | `197f6531` 2025-10-14 "Update README.md (#13319)"; last functional-ish commits: `6d89c827` 2025-09-12 (PSIRT dependency-confusion fix for oneccl_bind_pt), `25e17090` 2025-08-14 (pin Transformers). The llama.cpp base was last bumped in `f0b600d` 2025-07-09 "update llama.cpp version (#13251)". |
| License | Apache-2.0 (LICENSE verified; GitHub reports `apache-2.0`). The llama.cpp binaries it ships are MIT upstream code with Intel patches. |
| Releases | Latest "stable" `v2.2.0` 2025-04-07; `v2.3.0-nightly` pre-release (portable zip/tgz of llama.cpp and Ollama) 2025-04-16. Nothing newer. The nightly's own body just redirects to `ipex-llm/ipex-llm` releases. |
| llama.cpp base | Docs state "latest version is consistent with `4ad2436`" = `4ad243677bca6c97f14dbc187b2116b51fcb7ffd`, **2025-06-16**. Older pin `d7cfe1f` = 2025-02-25. |

Upstream distance: deployed image is b11347 (2026-10-01). IPEX-LLM's base is ~16 months and several thousand upstream builds older (4ad2436 is mid-June 2025; build number not looked up).

## What exists

- The repository contains **no llama.cpp C++ source**. `docs/`, `python/llm/` (Python transformers optimizations, benchmarks, an NPU `simple.cpp` example), `docker/`, and `apps/`. The llama.cpp/Ollama portable binaries live only in GitHub release artifacts, not in the tree, so the SYCL changes cannot be audited from source here. Claims about its kernels are unverifiable from this repo.
- Docs (`docs/mddocs/Quickstart/`): `llamacpp_portable_zip_gpu_quickstart.md`, `ollama_portable_zip_quickstart.md`, `bmg_quickstart.md` (Arc B580, Ubuntu 25.04 PPA / Windows driver 32.0.101.6449), `flashmoe_quickstart.md`, `vLLM_quickstart.md`.
- FlashMoE: a `flash-moe` binary "built on top of llama.cpp llama-cli" for DeepSeek V3/R1 671B and Qwen3MoE 235B on 1-8 A770/B580 with 128-380 GB CPU RAM (CPU-resident experts, GPU for attention). Requires "do not source oneAPI". This is an expert-offload design for cards too small to hold the model, not a faster in-VRAM MoE kernel.
- No mention in tree of sycl-tla, CUTLASS, joint_matrix, or ESIMD kernels (case-insensitive grep over `*.md` found none; the binaries are not in the tree).
- Battlemage: only B580-class consumer cards documented; nothing for Arc Pro B60/B65/B70 (G21/G31) or the xe kernel driver 7.0.
- Qwen3.6/3.8 architectures (GDN hybrid, qwen35moe) postdate its llama.cpp base, so they cannot load.

## Applicability

- None of our models' architectures are supported by a June-2025 llama.cpp base. Our upstream image (b11347) already has MoE reorder, grouped XMX MoE GEMM at HEAD, oneDNN/oneMKL/DPAS flash attention, tensor split, and MTP speculative decoding, none of which exist in the IPEX-LLM drop.
- Its historic value was ESIMD/XMX and reorder work that Intel upstreamed into ggml-sycl in 2025 (the upstream backend has `esimd.hpp`, ESIMD DMMV kernels, reorder for Q4_0/K-quants). Whatever remains in IPEX-LLM-only forks is unreachable from the tree and behind archived, unpatched binaries.
- FlashMoE idea (experts on CPU, attention on GPU) is already covered upstream by `--cpu-moe` / `--n-cpu-moe` / `-ot`; with 2x32 GB it is unnecessary.

## Risks

- Archived by Intel with a stated "known security issues" notice; binaries are unpatched and nightly-tagged. Do not run on the aihost.
- Portable zips embed their own oneAPI/driver assumptions (Ubuntu 25.04/Windows driver numbers), unverified against xe 7.0.
- Binaries only, no source in tree: not auditable.
- README itself warns that mmap loading in the portable zip may leak data via side channels.

## Testable hypothesis

None worth testing. If a claim surfaces that IPEX-LLM has a unique kernel that beats upstream on B65, the testable form is: obtain the ipex-llm v2.3.0-nightly llama.cpp tgz hash, run `ldd`/`strings` for `joint_matrix`/ESIMD symbols in an isolated container with no GPU, compare against upstream b11347 symbols. Expected result: strict subset of upstream functionality for our models, and incapable of loading qwen35moe.

## Verdict

**Incompatible** (for our models and this deployment: archived, 16 months behind upstream, no Qwen3.6/3.8 architecture support, no source in tree, no Pro-B-series coverage).
Secondary classification: **Already upstream** for any useful SYCL optimization it once contained (ESIMD, reorder, FA with XMX were upstreamed and have since evolved far past it).
