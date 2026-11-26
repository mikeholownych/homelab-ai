# Model / role reset (do not assume current pins)

Sources: `reports/CAIS fleet model survey.md` (2026-11-22), capability-mix design, LiveBench/local guides (vendor-suspect), local Stage-1 results.

## Current fleet (as measured)

| Role | Artifact | Issue |
|---|---|---|
| lead | Qwen3.8-27B Q4 | Best engx-hard solo (96.7%); generalist, not proven orchestrator |
| deep | Flash-Next IQ1 | Worse than lead on hard; Community/MaaS license; extreme quant |
| rocm | **same** Qwen3.8-27B Q4 | Capacity clone; reasoning mode off; always fails H08 |

Capability-mix design already argued: lead=orchestrator, deep=coding, rocm=general/long-ctx **not** coder-first — then cutover put **same 27B** on lead+rocm for sameness.

## Deployable challengers (B65 / Strix fit) — from CAIS survey

Non-exhaustive; bake-off required; boards are suspect:

| Candidate | Why challenge current pin | Fit |
|---|---|---|
| **Devstral Small 2 24B** | Non-Qwen agentic SWE; Apache | B65 + Strix |
| **GLM-4.7-Flash** | MIT MoE; family diversity | B65 + Strix |
| **gpt-oss-20b** | Tool/reasoning control loops | B65 + Strix |
| **Gemma 4 31B / 26B-A4B** | Apache control; SYCL smoke first | B65 + Strix |
| **Qwen3-Coder-30B** | Still on disk; failed prior CAIS complex — only as control | B65 + Strix |
| **gpt-oss-120b / Qwen3-Coder-Next / DeepSeek V4.1 Flash IQ1** | Strix sole-tenant ceiling plays | Strix only |

## Role reframes (mutually exclusive products — pick deliberately)

**R1 — Coding max:** Best single coding agent scaffold + best coding weights on 5820; ROCm = failover capacity or bigger sole-tenant coder — **not** a third critic.

**R2 — Capability mix (original intent):** Distinct artifacts: orchestrator ≠ coder ≠ long-ctx/general (+ visual bolt-ons). Collaboration optional and late.

**R3 — Diversity panel:** Intentionally different families for rare independent review — only valuable if findings are **externally grounded** (tests/spec/static analysis) and acted on.

Current fleet is accidentally a weak hybrid of R1+R2 (two coding Qwens + clone) optimized for none of them cleanly.

## Candidate refresh ([local model candidates](9b10d5b7-b260-4ad3-8a4a-deb7d32b991b))

Vendor boards remain suspect; use CAIS as ground truth. Fit notes assume ~61 GiB GTT on MS-S1 (tighter than many public Strix benches).

| Role | Keep / challenge | Notes |
|---|---|---|
| **Lead** | Keep Qwen3.8-27B as baseline; challenge with **GLM-4.7-Flash** | 27B still best-evidenced local agent-loop dense; Gemma 4 31B weak as orchestrator (tool/loop issues) |
| **Deep** | **A/B/C:** current Flash-Next-Coder IQ1 vs **Nanbeige4.3-33B** vs **Devstral Small 2** | Confirm artifact = ISTA pruned coder (~29.6 GiB resident), not Unsloth 74 GiB IQ1; Community license / MaaS risk; Nanbeige = family break + heavier KV |
| **ROCm** | **Do not** keep same 27B as quality peer; prefer **Gemma 4 26B-A4B** (general) or **GLM-4.7-Flash** (agent-capable) | gpt-oss-120b / Nemotron Super likely exceed 61 GiB+KV; Flash-Next full on ROCm ≈ clone if deep stays Flash-Next-Coder |

### Evaluation pitfalls (from same brief)

1. Match generation caps / thinking on|off / effort across A/Bs — agent scores collapse under tight caps.
2. Record file sha + size; “IQ1_M” labels are ambiguous across repos.
3. Same-family peers fail alike → router sees no signal.
4. SYCL vs HIP vs Vulkan numbers do not transfer; pin runtime digests in every comparison.
5. Score **cost per solved task**, not pass rate alone (dense 27B can be much slower than small-active MoE).
