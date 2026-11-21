# Model shortlist — Phase 2a (`ai-ms-s1-max-01`)

Host: `ai-ms-s1-max-01` (`10.0.8.6`, lab only) · ~61 GiB coarse APU pool
(`gfx1151`) · ROCm 7.2.0.

**Shared small probe (smoke, all engines):** `Qwen3-4B-Instruct-2507`
**Mid-size smoke + deep entry:** `Qwen3-Coder-30B-A3B-Instruct`
**Deep-consideration set (5):** Qwen3-Coder-30B-A3B, Qwen3.6-35B-A3B,
Qwen3.6-27B, Qwen3-Coder-Next (80B-A3B), GLM-4.7-Flash.

Spec: `docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-engine-selection-design.md`.

## Platform envelope (verified 2026-11-21 over SSH)

- `rocminfo`: `gfx1151` (agent + ISA) and `aie2p` present; `/opt/rocm` →
  `/opt/rocm-7.2.0` (`.info/version` = `7.2.0`).
- `rocm-smi --showmeminfo`: GTT total 65,868,955,648 B (**61.35 GiB**), VRAM
  carve-out 0.5 GiB. System RAM 122 GiB (the 61.35 GiB GTT pool is the
  engine-usable ceiling; GTT/carve-out is not changed by this campaign).
- `/var/lib/local-ai`: 1.0 TiB volume, 1004 GiB free, `models/` empty.
- Artifact sizes/revisions below were read from the Hugging Face API on
  2026-11-21; nothing has been downloaded (Task 4 downloads).

## Fit gates used

- Budget: weights + KV cache at target context + ~2 GiB runtime overhead must
  leave **≥ 8 GiB** free of 61.35 GiB (i.e. ≤ ~53 GiB total). Aim ≥ 12 GiB where
  possible; record measured actuals in 2b/2c.
- KV estimate = fp16 KV, full-attention layers only (hybrid linear-attention
  layers carry a small fixed state, not counted). Estimates only.
- Open license, pinable revision (HF commit SHA, plus sha256 for GGUF files).
- Target context ≥ 32k (probe: 32k; interactive coding members: 64k–128k).

## Candidates

- **Qwen3-4B-Instruct-2507 (shared small probe, not a deep member)** —
  dense 4B, Apache-2.0, native ctx 262,144 (36 layers, 8 KV heads, head_dim
  128 → ~144 KiB/token KV). Classic dense Qwen3 architecture, chosen so smoke
  isolates *engine* failure from *model-architecture* failure.
  - GGUF `Q8_0` 3.99 GiB; HF BF16 safetensors 7.49 GiB
  - Target ctx 32,768 → KV ~4.5 GiB; total ≈ 10.5 GiB (GGUF) / ≈ 14 GiB (HF)
  - Engines: llama.cpp (GGUF), vLLM (HF), SGLang (HF)
- **Qwen3-Coder-30B-A3B-Instruct (mid-size smoke + deep)** — MoE ~30.5B total /
  ~3.3B active (128 experts, 8/token), Apache-2.0, native ctx 262,144 (48
  layers, 4 KV heads, head_dim 128 → ~96 KiB/token KV). Agentic-coding model
  card; mature architecture expected to be supported by all three engines; also the
  Qwen3-Coder MoE class referenced in Strix Halo community reports.
  - GGUF `Q8_0` 30.25 GiB (fallback `Q6_K` 23.37 GiB); HF FP8 29.03 GiB
    (BF16 56.87 GiB rejected: no headroom)
  - Target ctx 65,536 → KV ~6 GiB; total ≈ 38 GiB (GGUF Q8_0) / ≈ 37 GiB (FP8)
  - Engines: llama.cpp (GGUF), vLLM (FP8), SGLang (FP8)
- **Qwen3.6-35B-A3B (deep)** — MoE ~36B total / ~3B active (256 experts,
  8/token), Apache-2.0, native ctx 262,144, hybrid attention (30 linear + 10
  full layers; ~20 KiB/token KV). Newest Qwen coding-agent MoE; card cites
  agentic coding and recommends vLLM/SGLang (`sglang>=0.5.10`). Includes a
  vision tower (not exercised).
  - GGUF `UD-Q6_K` 27.30 GiB (alt `UD-Q5_K_XL` 24.77 GiB); HF FP8 34.89 GiB
    (BF16 66.97 GiB rejected: exceeds pool)
  - Target ctx 131,072 → KV ~2.5 GiB; total ≈ 32 GiB (GGUF) / ≈ 39 GiB (FP8)
  - Engines: llama.cpp (GGUF), vLLM (FP8), SGLang (FP8) — hybrid
    linear-attention kernels on gfx1151 are unproven; 2b must confirm
- **Qwen3.6-27B (deep, dense reference)** — dense 27B, Apache-2.0, native ctx
  262,144, hybrid attention (48 linear + 16 full layers; ~64 KiB/token KV).
  Dense quality/latency-floor reference against the A3B MoEs (decode is
  memory-bandwidth-bound, so expect much lower tok/s than the MoEs).
  - GGUF `Q6_K` 20.98 GiB (alt `Q8_0` 26.63 GiB); HF FP8 28.75 GiB (BF16
    51.75 GiB rejected: headroom < 8 GiB once KV is added)
  - Target ctx 131,072 → KV ~8 GiB; total ≈ 31 GiB (GGUF) / ≈ 39 GiB (FP8)
  - Engines: llama.cpp (GGUF), vLLM (FP8), SGLang (FP8) — same hybrid-kernel
    caveat as Qwen3.6-35B-A3B
- **Qwen3-Coder-Next (80B-A3B) (deep, large-model probe)** — MoE ~80B total /
  ~3B active (512 experts, 10/token), Apache-2.0, native ctx 262,144, hybrid
  attention (12 full layers; ~24 KiB/token KV). Card: long-horizon tool use,
  error recovery; needs `sglang>=0.5.8`. The only candidate that stresses the
  pool; tests whether a bigger-but-sparse coder beats the 30–35B class.
  - GGUF `Q4_K_M` 45.20 GiB (single file); third-party AWQ 4-bit 44.93 GiB
    (`cyankiwi`, not first-party). Official FP8 (74.86 GiB) and BF16
    (148.41 GiB) rejected: do not fit.
  - Target ctx 65,536 → KV ~1.5 GiB; total ≈ 49 GiB, ≈ 12 GiB free (131,072
    stretch: ≈ 50 GiB)
  - Engines: llama.cpp (GGUF), vLLM (AWQ, third-party quant), SGLang (AWQ,
    unverified). Expect to be the most fragile pair; per-pair failure only drops
    that pair.
- **GLM-4.7-Flash (deep, non-Qwen coding MoE)** — MoE ~31B total
  (64 routed experts, 4/token), MIT, native ctx 202,752, MLA attention
  (kv_lora_rank 512 → ~53 KiB/token KV *if* the engine keeps the compressed
  cache). Card targets agentic tasks (τ²-Bench, Terminal Bench 2). Only
  non-Qwen family in the set, for diversity.
  - GGUF `Q6_K` 23.00 GiB (alt `Q8_0` 29.66 GiB); HF AWQ 18.41 GiB
    (`QuantTrio`, third-party). BF16 (58.16 GiB) rejected: ~3 GiB headroom.
  - Target ctx 65,536 → KV ~3.3 GiB with MLA; total ≈ 28 GiB. If an engine
    expands MLA to full per-head KV the cache is ~58 GiB at 64k and the pair
    fails the fit gate — 2b/2c must record actual KV allocation.
  - Engines: llama.cpp (GGUF), vLLM (AWQ), SGLang (AWQ). Card says vLLM/SGLang
    required main-branch builds at release (Jan 2026); re-verify against the
    pinned images.

## Rejected

Hard-gate failures and deliberate non-selections, each with reason. Fit
numbers are weights only unless noted; limit is ≈ 53 GiB total.

- **gpt-oss-120b** (GGUF Q8_0/MXFP4 59.03 GiB, F16 60.88 GiB; HF repo carries two ~61 GiB MXFP4 copies):
  weights alone consume 96% of the 61.35 GiB pool; no KV/headroom. Rejected on
  fit. (Would need a GTT change, which is out of scope.)
- **Qwen3.8-Flash-Next** (~180B params; smallest GGUF `UD-IQ1_S` 61.82 GiB):
  does not fit; license is `other` (qwen-community-1.0), not plainly
  redistributable.
- **DeepSeek-V4.1-Flash** (~763B params; smallest GGUF `UD-IQ1_S` 216.98
  GiB): does not fit.
- **Llama 4 Scout 17B-16E** (109B total; `Q4_K_M` 60.87 GiB, `Q5_K_M` ≥ 71
  GiB; best fit `UD-Q3_K_XL` 45.65 GiB / `UD-Q2_K_XL` 39.47 GiB): Q4 does not
  fit; the fitting quants are Q3/Q2 (quality-degraded vs. the quant policy);
  Llama community license (`other`). HF BF16 weights ~200+ GiB.
- **GLM-4.5-Air** (106B; `Q4_K_M` 67.97 GiB, `Q4_K_S` 62.4 GiB; `Q3_K_S`
  49.04 GiB): Q4 does not fit; Q3 is quality-degraded and leaves < 8 GiB after
  KV; superseded by GLM-4.7-Flash for this host.
- **Qwen3-Coder-Next FP8 / BF16** (74.86 / 148.41 GiB): do not fit (GGUF Q4_K_M
  and third-party AWQ kept).
- **Qwen3-Coder-30B-A3B BF16** (56.87 GiB), **Qwen3.6-35B-A3B BF16**
  (66.97 GiB), **Qwen3.6-27B BF16** (51.75 GiB), **GLM-4.7-Flash BF16** (58.16
  GiB), **Gemma-4-31B-it BF16** (58.25 GiB): BF16 safetensors fail the headroom
  gate once KV is added; quantized artifacts of the same models are used
  instead.
- **Gemma-4-31B-it (dense)** and **Gemma-4-26B-A4B-it (MoE)** (Apache-2.0;
  GGUF `Q6_K` 23.47 GiB / `UD-Q6_K` 21.58 GiB; both fit): *not selected* —
  shortlist capped at 5, and Qwen3.6-27B already covers the dense reference
  with first-party FP8 for vLLM/SGLang. Reserve candidates if a slot opens.
- **gpt-oss-20b** (GGUF `Q8_0` 11.28 GiB; HF 25.63 GiB; Apache-2.0, fits
  trivially): *not selected* — MoE already covered by three A3B-class members
  at higher expected coding quality; reserve alternate probe.
- **Qwen3-32B dense**, **Qwen3-30B-A3B-Instruct-2507**: *not selected* —
  superseded by Qwen3.6-27B and Qwen3-Coder-30B-A3B respectively.
- **DeepSeek-R1-Distill-Qwen-32B** (GGUF `Q6_K` 25.04 GiB; fits): *not
  selected* — older reasoning distill; thinking-only traces hurt TTFT and tool
  contract probes; no V3/R1-class model fits (V4.x rejected above).
- **Qwen3.5-4B / 9B**: *not selected as probe* — hybrid-attention
  architecture adds model-level risk to what must be an engine-only smoke
  probe.
- Anything only available as a floating "latest" tag without a commit SHA: none
  found among the above (all pinned below).

## Download pins

Destination root on host: `/var/lib/local-ai/models/<slug>/`. Revisions are
Hugging Face commit SHAs read 2026-11-21. GGUF sha256 values are the LFS object
IDs; safetensors repos are pinned by commit SHA (verify per-file LFS sha256 at
download time and record it in the Task 4 evidence).

### Shared probe — Qwen3-4B-Instruct-2507

| Format | Repo | Revision | File | Size | sha256 |
| --- | --- | --- | --- | --- | --- |
| GGUF | `unsloth/Qwen3-4B-Instruct-2507-GGUF` | `a06e946bb6b655725eafa393f4a9745d460374c9` | `Qwen3-4B-Instruct-2507-Q8_0.gguf` | 3.99 GiB | `391c1e410fd9f4cf2de2b510273b56a84c19ce18f4fa3bfb3774031dac4ef068` |
| HF BF16 | `Qwen/Qwen3-4B-Instruct-2507` | `cdbee75f17c01a7cc42f958dc650907174af0554` | all `*.safetensors` + config/tokenizer | 7.49 GiB | per-file at download |

### Mid-size — Qwen3-Coder-30B-A3B-Instruct

| Format | Repo | Revision | File | Size | sha256 |
| --- | --- | --- | --- | --- | --- |
| GGUF Q8_0 | `unsloth/Qwen3-Coder-30B-A3B-Instruct-GGUF` | `b17cb02dd882d5b6ab62fc777ad2995f19668350` | `Qwen3-Coder-30B-A3B-Instruct-Q8_0.gguf` | 30.25 GiB | `4ff1cff607804037bf6d2168249c570baa4e1621292b159c0e06591e0d7c3066` |
| GGUF Q6_K (fallback) | same | same | `Qwen3-Coder-30B-A3B-Instruct-Q6_K.gguf` | 23.37 GiB | `100b5121d09553fb1af3b873b21fb3ec3da5c306fc5cb09bd338c48e21b10875` |
| HF FP8 | `Qwen/Qwen3-Coder-30B-A3B-Instruct-FP8` | `dcaee4d4dfc5ee71ad501f01f530e5652438fde0` | all `*.safetensors` + config/tokenizer | 29.03 GiB | per-file at download |

### Qwen3.6-35B-A3B

| Format | Repo | Revision | File | Size | sha256 |
| --- | --- | --- | --- | --- | --- |
| GGUF UD-Q6_K | `unsloth/Qwen3.6-35B-A3B-GGUF` | `a483e9e6cbd595906af30beda3187c2663a1118c` | `Qwen3.6-35B-A3B-UD-Q6_K.gguf` | 27.30 GiB | `4fe53b148b46f9b88830e2a3055c5b15c3a4d1e3ddc9a1384a108d8b9d59f043` |
| GGUF UD-Q5_K_XL (alt) | same | same | `Qwen3.6-35B-A3B-UD-Q5_K_XL.gguf` | 24.77 GiB | `25233af7642e3a91bd52cc4aeefdbd4a117479088e06cf1aea5b6bedb443c506` |
| HF FP8 | `Qwen/Qwen3.6-35B-A3B-FP8` | `c653bba46dfa06e9658dcc0b0dc87fe4685f14a2` | all `*.safetensors` + config/tokenizer | 34.89 GiB | per-file at download |

### Qwen3.6-27B

| Format | Repo | Revision | File | Size | sha256 |
| --- | --- | --- | --- | --- | --- |
| GGUF Q6_K | `unsloth/Qwen3.6-27B-GGUF` | `82d411acf4a06cfb8d9b073a5211bf410bfc29bf` | `Qwen3.6-27B-Q6_K.gguf` | 20.98 GiB | `ec1805fe87e6519c461c1ed2d179865464a875ed241032ead65a354f979cfe14` |
| HF FP8 | `Qwen/Qwen3.6-27B-FP8` | `a56219b8202864dc6d3e565be5ff1eea01f54cb4` | all `*.safetensors` + config/tokenizer | 28.75 GiB | per-file at download |

### Qwen3-Coder-Next (80B-A3B)

| Format | Repo | Revision | File | Size | sha256 |
| --- | --- | --- | --- | --- | --- |
| GGUF Q4_K_M | `unsloth/Qwen3-Coder-Next-GGUF` | `ce09c67b53bc8739eef83fe67b2f5d293c270632` | `Qwen3-Coder-Next-Q4_K_M.gguf` | 45.20 GiB | `9e6032d2f3b50a60f17ce8bf5a1d85c71af9b53b89c7978020ae7c660f29b090` |
| HF AWQ 4-bit (third-party) | `cyankiwi/Qwen3-Coder-Next-AWQ-4bit` | `c92cabfad08cadb011dc169cabb3e6da621b0719` | all `*.safetensors` + config/tokenizer | 44.93 GiB | per-file at download |

### GLM-4.7-Flash

| Format | Repo | Revision | File | Size | sha256 |
| --- | --- | --- | --- | --- | --- |
| GGUF Q6_K | `unsloth/GLM-4.7-Flash-GGUF` | `0d32489ecb9db6d2a4fc93bd27ef01519f95474d` | `GLM-4.7-Flash-Q6_K.gguf` | 23.00 GiB | `f5bdc431802d7a3dab3be5a50ad0848a5569fd45c98c5e2ad83412c87cd887dc` |
| HF AWQ (third-party) | `QuantTrio/GLM-4.7-Flash-AWQ` | `88e3d3d913c0d97c8f505cdc03433c48226bedc3` | all `*.safetensors` + config/tokenizer | 18.41 GiB | per-file at download |

Total if every artifact above were downloaded: ~362 GiB — fits the 1004 GiB
free, but Task 4 should download only what 2b needs (probe + mid-size first).

## Engine coverage

"Artifact" = a pinned file in a format the engine consumes exists above.
"Verified" is **not** claimed anywhere: every cell is an untested expectation
until Phase 2b/2c produce evidence. Risk notes mark where failure is likely.

| Model | llama.cpp HIP | vLLM ROCm | SGLang |
| --- | --- | --- | --- |
| Qwen3-4B-Instruct-2507 (probe) | GGUF Q8_0 | HF BF16 | HF BF16 |
| Qwen3-Coder-30B-A3B (mid-size) | GGUF Q8_0 / Q6_K | HF FP8 (FP8 kernel support on gfx1151 unproven; fall back to a 16-bit-activation path if needed) | HF FP8 (same caveat) |
| Qwen3.6-35B-A3B | GGUF UD-Q6_K | HF FP8 — hybrid linear-attention risk | HF FP8 — hybrid risk; `sglang>=0.5.10` per card |
| Qwen3.6-27B | GGUF Q6_K | HF FP8 — hybrid risk | HF FP8 — hybrid risk; `sglang>=0.5.10` per card |
| Qwen3-Coder-Next 80B-A3B | GGUF Q4_K_M | AWQ (third-party) — hybrid + quant risk | AWQ (third-party) — hybrid + quant risk; `sglang>=0.5.8` per card |
| GLM-4.7-Flash | GGUF Q6_K | AWQ (third-party) — MLA/KV-size risk | AWQ (third-party) — MLA/KV-size risk |

Smoke pairing (2b), per engine: probe model + Qwen3-Coder-30B-A3B in the
engine's native format from the table. Per the spec, a per-model failure drops
only that engine×model pair; systemic failure drops the engine. SGLang
unavailability on ROCm 7.2.0 must be recorded as `unavailable`, not zero tok/s.
