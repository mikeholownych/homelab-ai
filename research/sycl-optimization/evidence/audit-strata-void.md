# Audit: Jumbomuffin777/Strata-Void

Method: shallow clones of the fork and of its upstream (`Niko1221/Strata`) into separate dirs under `.../scratchpad/audit/strata-void/repo` and `.../strata-upstream/repo`; read only, no scripts/builds executed, no remote host touched.

## Identity

| Item | Value |
|---|---|
| Repo | https://github.com/Jumbomuffin777/Strata-Void, created 2026-10-08, pushed 2026-10-15, 3 stars, MIT, GitHub `isFork: true`, parent `Niko1221/Strata` |
| HEAD | `fda1174e2dc02c6bd3e06f12cdf296ed7721768a`, 2026-10-11, "Validate Intel Arc coding agents and port upstream tool protocol fixes". **Single commit in the clone (history squashed/flattened, `git log | wc -l` = 1)**, so per-change provenance is not auditable. CHANGELOG says it branched from upstream `a5682fe`. |
| Owner | account `Jumbomuffin777`, created 2024-09-18, 0 followers, 4 public repos. LICENSE: "Copyright (c) 2026 Niko1221 and the Strata contributors / Copyright (c) 2026 Jumbomuffin777 (the Strata Void changes)". |
| Upstream | https://github.com/Niko1221/Strata: created 2026-09-24, 44,149 stars, MIT, last push 2026-11-12, HEAD `13eedf552417a6a791a7d13c6597e24300ee3a09` (2026-11-12). Description: "Qwen3.8-Flash-Next on any consumer hardware: one-click install, Strata inference engine, OpenAI/Anthropic API". |
| Identity verdict | Verified: it is a real fork of a real, popular project, truthfully labelled ("An experimental fork of Strata", upstream credited, acknowledgements file, upstream-source commit hashes listed in the commit message). Not an impersonation. |

## What it actually is

- **Not a llama.cpp patchset.** Strata is a separate inference engine (CUDA, HIP, and a community SYCL port) specialised for Qwen3.8-Flash-Next (hybrid GDN + MoE, 512 experts, 10 routed/token), with its own GGUF "pack" format, expert cache, MTP drafter, and server. It uses ggml only for dequant tables / quantizer parity (`sycl/third_party/ggml/ggml-common.h`, `ggml_cuda_host.cu`); kernels are SYCLomatic (dpct) migrations of its CUDA kernels (`sycl/src/**/*.dp.cpp`, 206 files under `sycl/`).
- The Intel Arc SYCL engine itself was written by another person (`maxfridbe`, upstream PR #423 per `docs/INTEL_ARC.md`) and is in upstream Strata. Void's own additions, by README: (1) Task-Parallel Requests (planner + subtasks across batch slots; implemented in Python `serve/task_parallel.py`, 83 KB, and `serve/context_pool.py`), (2) "fast IQ4_XS/IQ4_NL -> FP16 prompt dequant" in SYCL, (3) `--slot-context`, (4) shared-context reuse, (5) retrieval hook, (6) tool-call protocol fixes ported from upstream.
- Declared hardware: B70 32 GB + **B65 32 GB (8086:e222, bmg-g31)** + B60 24 GB. Same card family as ours.

## Code vs README claims

- SYCL diff against current upstream: files only in Void's `sycl/`: `include/strata/env_flag.hpp`, `include/strata/split_trace.hpp`, `src/kernels/moe_prefill_bench.cpp`, `tests/`. 85 files in `sycl/src` differ simply because Void is a stale snapshot (upstream has since added `iq4_lut.hpp`, `moe_fused_iq.dp.cpp`, `qsa_prompt_attn_esimd.hpp`, `dflash2`, `copy_queue.hpp` and others that Void lacks). The "new IQ4 dequant kernels" claim could not be isolated as a Void-only addition: `dequant_bf16.dp.cpp` and `dequant_s2.dp.cpp`/`iq_kernels.dp.cpp` differ from upstream, but without history (squashed) cannot be attributed. Treat as **unverified**.
- The CHANGELOG for void-v0.1.1 is candid: "Server protocol fixes, not a new SYCL kernel optimization"; "No native kernel change or new benchmark speedup." That matches the code diff. The headline "~2x prompt reading (334 -> 659 tok/s at 16K)" is in docs/BENCHMARKS.md only (results are claimed, JSON summaries exist in `bench/results`, reproducibility not checked).
- Task-Parallel: README is upfront that single-stream tok/s is unchanged (~40-45) and total compute is higher. That is a server-orchestration feature irrelevant to SYCL kernel speed; also needs the Strata engine, not llama.cpp.
- Upstream's own docs say Strata maintainers have no Intel GPU, and the 0.1.39 SYCL port was untested on Arc by maintainers; all Arc numbers are community-reported. Upstream INTEL.md data (B70, PCIe Gen3 x8, Coder IQ1_M): decode 78 tok/s greedy (with MTP draft), prompt 790 tok/s at 2.2K; llama.cpp SYCL on same GGUF 23-25 decode / ~150 prompt. Those llama.cpp numbers date to 2026-10-01 or earlier and use a different build; not comparable to b11347 or HEAD without re-measurement. Also notes failed experiments: `joint_matrix` expert kernels were 1.4-3x slower than dp4a, one hung the GPU; fused dequant+GEMM via `joint_matrix` was 4-5x slower than dequant + oneMKL.

## Applicability to our stack

- Our deployment is llama.cpp upstream; Strata cannot be dropped in. It would be a separate engine with its own pack format and a docker dev image.
- Ideas transferable in principle (modification required, not code): keep all experts resident in VRAM, oneMKL GEMM over dequantized experts for prefill (llama.cpp's own per-expert path already does dequant+oneDNN/oneMKL; HEAD adds grouped XMX), MTP drafter (upstream has `--spec-type draft-mtp`).
- Strata is the only artifact here whose model target (Qwen3.8-Flash-Next IQ1_M-class quants, 512 experts) matches ours, and its claim that llama.cpp SYCL decodes the Coder IQ1_M at 23-25 tok/s on a B70 is a concrete number to re-test against b11347/HEAD, since 69 relevant SYCL commits landed after that.

## Risks / supply-chain observations

- Stale squashed fork by a low-reputation account (0 followers, 3 stars) of a fast-moving 44k-star project; upstream is strictly more current and attributable. Use upstream `Niko1221/Strata` if anything.
- `sycl/tools/Dockerfile` bases on a **third-party, mutable tag**: `ghcr.io/snailium/llama.cpp-sycl-intel-b70/llama-sycl-b70:stable` (not Intel, not Strata, not pinned by digest). Upstream Strata does the same, per its own docs. Unaudited community base image.
- `setup.py` (4442 lines, 261 KB), `setup.sh`, `START-HERE.bat` auto-install Python via apt/winget/python.org with `sudo`/`Invoke-WebRequest`+silent installer, download prebuilt binaries from `Niko1221/Strata/releases/latest`, pull weights from Hugging Face (and `hf-mirror.com`), pip-install pinned requirements. Reviewed grep-level only: no obfuscation, no base64/eval, no `curl|sh`; downloads are checksummed (sha256 on shards). Standard but broad privileged behaviour; do not run on the host.
- Binary data blobs committed: `data/draft_vocab*.bin`, `data/expert-profile*.bin` (type `data`, not inspected beyond file type).
- Claims of "50.6 tok/s live" and agent-workflow validation are single-sample, self-reported, and the README says the lifecycle controller and private infra are not included.
- `FUNDING.yml` / Buy-me-a-coffee in upstream README (benign, noted).
- No malware indicators found; no evidence of impersonation. Verdict on trust: low-to-moderate, not malicious as far as reviewed.

## Testable hypothesis

If llama.cpp SYCL at HEAD (after #29245/#30156/#29864) still decodes Flash-Next IQ1_M at roughly a third of Strata's reported rate on a B65, then the gap is attributable to (a) IQ1_M lacking a reordered MMVQ kernel in ggml-sycl and (b) MTP acceptance rather than raw kernel bandwidth (Strata's own docs say its kernels reach only 130-160 GB/s of a 600 GB/s card, "the same class llama.cpp reaches"). Test: same GGUF, via gateway, llama.cpp b11347 vs pinned HEAD, with and without `--spec-type draft-mtp`; compare decode tok/s per accepted-token. Strata itself is not needed for this.

## Verdict

**Different arch only** (separate engine, not llama.cpp; Void adds orchestration and bench docs, essentially no new SYCL kernels).
Secondary: **Applicable after modification** only as an idea source (resident experts, MTP, oneMKL dequant GEMM), and **Unproven** for its performance claims on our hardware. Not relevant to llama.cpp's SYCL MoE path as code. Prefer upstream Niko1221/Strata over this fork if the engine is ever evaluated, and run it only in an isolated container.
