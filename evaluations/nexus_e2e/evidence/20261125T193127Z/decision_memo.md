# Local Coding Quality Levers — Campaign Decision Memo (Task 4)

**Date:** 2026-11-26  
**Spec:** `docs/superpowers/specs/2026-11-25-local-coding-quality-levers-design.md`  
**Plan:** `docs/superpowers/plans/2026-11-25-local-coding-quality-levers.md`  
**Evidence:**
- Stage 1/2 baselines: `evaluations/nexus_e2e/evidence/20261124T191124Z/`
- Lever 1 (BoN vs solo-1 / repair): `evaluations/nexus_e2e/evidence/20261125T193127Z/bon_vs_solo.md`
- Lever 2 (Candidate bake-off): `evaluations/nexus_e2e/evidence/20261125T193127Z/candidates/{devstral-small2,glm47-flash}/`
- Lever 3 (Complementarity β): `evaluations/nexus_e2e/evidence/20261125T193127Z/complementarity.md`

---

## Executive Summary

1. **Harness-first wins over blind sampling, and execution repair wins over both:** On `engx-hard` (10 tasks, `max_tokens=8192`, `engineering/lead` `Qwen3.8-27B-UD-Q4_K_M`, `reasoning=on/4096`), execution-gated Best-of-3 (`bon3-lead`, `temp=0.2`, `max_attempts=1`) beat single-shot `solo-lead-1` (`90.0%` vs `80.0%`, `+10.0 pts`), but **sequential test-feedback repair** (`solo-lead`, `max_attempts=3`) achieved **`96.7%`** (`29/30`) at **slightly fewer mean tokens** (`8,289` vs `8,362`) and **lower mean wall time** (`429.4s` vs `470.6s`).
2. **Both on-disk non-Qwen challengers fail coding qualification cleanly:** Through the durable candidate transaction on `ai-5820-01` (`sha256:6cd97c37...` SYCL image, `head-a956a852`), `devstral-small2` (`Devstral-Small-2-24B-Instruct-2512-Q4_K_M`, `reasoning=off`) and `glm47-flash` (`GLM-4.7-Flash-Q4_K_M`, `reasoning=on/4096`) passed latency/tool-call probes (**4/4** latency, **2/2** multi-turn tool calls) with no infinite-loop bug, yet scored **`0/4` (`0.0%`)** on `{H02-cron-next, H03-json-patch, H07-sqlite-rebuild, H08-glob}` vs **`11/12` (`91.7%`)** for `solo-lead` and **`8/12` (`66.7%`)** for `solo-deep` / `solo-rocm`. **Reject both challengers for `deep` and `lead`.**
3. **Production routing currently inverts measured quality:** In `inventory/production/host_vars/ai-5820-01.yml`, `escalate-retry`, `escalate-after-failure`, and `deep-tasks` escalate **away from** `lead` (`96.7%`) **to** `deep` (`Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M`, `86.7%`, deterministic `0/3` on `H07-sqlite-rebuild`), while `orchestrator_gateway_pool_quality_weights` ranks `deep: 3.0 > rocm: 2.5 > lead: 2.0`. Previously `lead` held only `coding.routine` (`12/12`); we have now completed live CAIS `coding.complex` qualification for `lead` (`9/10` tasks, `19/20` trials, `pass_lower_bound: 0.7176`, granted locally in `inventory/production/cais/` as `q-coding.complex-412a2b3ad304-b1d7481e`).
4. **Role & pin disposition (no live inventory/gateway swap without PR review & converge):**
   - **`lead` (`worker1`, `Qwen3.8-27B-UD-Q4_K_M`, `reasoning=on/4096`):** **KEEP.** Live CAIS `coding.complex` is now **granted** in `inventory/production/cais/` (`q-coding.complex-412a2b3ad304-b1d7481e`); deliver ledger via PR/converge and fix the inverted escalation/auto weights in a follow-up PR.
   - **`deep` (`worker2`, `Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M`, `reasoning=on/4096`):** **RETAIN SHORT-TERM ONLY; DO NOT SWAP TO ON-DISK CANDIDATES; TARGET FOR FUTURE REPLACEMENT** once an external B65-sized challenger beats `86.7%` (ideally `≥ 96.7%`) and clears CAIS.
   - **`rocm` (`ai-ms-s1-max-01`, `Qwen3.8-27B-UD-Q4_K_M`, `reasoning=off`):** **STOP TREATING AS CODING PEER OR QUALITY DIVERSITY.** It solves zero tasks beyond `lead` (`0` unique tasks over `lead` across 30 trials) while failing `H08-glob` `0/3` and decoding at `~12.6 tok/s`. Keep it strictly in its general/long-context + visual-bolt-on role (removing its `quality_first` preference over `lead` on coding requests), or benchmark an on-disk MoE (`Qwen3.6-35B-A3B UD-Q6_K`, `28.7 GiB` GTT, `37.7 tok/s`) / external Strix candidate (`Gemma 4 26B-A4B`, `Qwen3-Coder-Next 80B-A3B Q4_K_M`) in a dedicated window.
   - **Stage 3 collaboration:** **REMAIN FROZEN.**

---

## 1. Lever 1 — Best-of-N vs Single-Sample & Sequential Repair (`engx-hard`, 10 tasks)

| Arm | Rep × Tasks | Max attempts / N | Temp | Accepted % | Oracle coverage % | Mean tokens/task | Mean secs/task | Notes |
|-----|-------------|------------------|------|------------|-------------------|------------------|----------------|-------|
| `solo-lead-1` | 1 × 10 | 1 / 1 | 0.0 | **80.0%** (8/10) | n/a | 6,051 | 335.1s | Failed `H03-json-patch`, `H08-glob` |
| `bon3-lead` | 1 × 10 | 1 / 3 | 0.2 | **90.0%** (9/10) | 90.0% | 8,362 | 470.6s | `mean_samples_run=1.3`; fixed `H03` on sample 2; `H08` 0/3 |
| `solo-lead` (Stage 1) | 3 × 10 | 3 / 1 | 0.0 | **96.7%** (29/30) | n/a | **8,289** | **429.4s** | `H08` **3/3**, `H03` 2/3, all others 3/3 |

**Decision:**
- Execution-gated `bon3` beats single-shot `solo-1` (`+10.0 pts` for `+2,311` tokens), confirming execution selection recovers variance on tasks like `H03-json-patch`.
- However, **at matched token budget (`8,289` vs `8,362` mean tokens), sequential repair with pytest feedback outperforms blind BoN-3 by `+6.7 pts`** (`96.7%` vs `90.0%`). On `H08-glob`, blind `temp=0.2` resampling failed all 3 draws, whereas test feedback inside `solo-lead` resolved `H08-glob` `3/3`.
- **Action:** Keep test-feedback repair primary in `engx` and Nexus loops; keep `best_of_n.py` as a fallback only for single-shot tasks lacking iterative feedback.

---

## 2. Lever 2 — On-Disk Challenger Bake-Off (`ai-5820-01` GPU 0 via `controller_candidate_transaction.yml`)

Both candidates ran on `ai-5820-01` under the live SYCL runtime (`localhost/sycl-research/llama@sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9`, `head-a956a852`, `GGML_SYCL_ENABLE_XMX_ESIMD=0`, `-c 65536 -np 1`), and both transactions returned `"phase": "restored_verified"` (`3/3` production workers healthy post-run).

### 2.1 Probe & Coding Results (`{H02, H03, H07, H08}`, `max_attempts=3`, `max_tokens=8192`, `temp=0`)

| Model (Arm) | Artifact SHA-256 (short) | Reasoning | Probe Latency (4 reqs) | Probe Tools (2 multi-turn cases) | Subset Pass (`{H02,H03,H07,H08}`) | Mean tok/task | Mean secs/task | Failure Profile |
|---|---|---|---|---|---|---|---|---|
| `solo-lead` (`Qwen3.8-27B-UD-Q4_K_M`) | `322e194f` | `on / 4096` | — | — | **11/12 (91.7%)** | 8,289 *(10 tasks)* | 429.4s *(10 tasks)* | `H03` 2/3; `H02,H07,H08` 3/3 |
| `solo-deep` (`Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M`) | `93558718` | `on / 4096` | — | — | **8/12 (66.7%)** | 9,489 *(10 tasks)* | 399.0s *(10 tasks)* | `H07` **0/3**; `H02` 2/3 |
| `solo-rocm` (`Qwen3.8-27B-UD-Q4_K_M`) | `322e194f` | `off` | — | — | **8/12 (66.7%)** | 4,850 *(10 tasks)* | 185.0s *(10 tasks)* | `H08` **0/3**; `H02` 2/3 |
| `cand-devstral-small2` (`Devstral-Small-2-24B-Q4_K_M`) | `d14ba9ed` | `off` | **4/4 PASS** (med `0.175s`, TTFT `0.0567s`) | **2/2 PASS** (`tool_calls→tool_calls→stop`) | **0/4 (0.0%)** | 10,458 | 143.0s | All 4 failed `hidden` stage (`H02` `0-10/5,30`; `H03` `/a/01`; `H07` row `(3,2,31)!=(3,2,30)`; `H08` `*/*.txt`) |
| `cand-glm47-flash` (`GLM-4.7-Flash-Q4_K_M`) | `29837ed2` | `on / 4096` | **4/4 PASS** (med `0.131s`, TTFT `0.0477s`) | **2/2 PASS** (`tool_calls→tool_calls→stop`) | **0/4 (0.0%)** | 21,258 | 573.4s | **3/4 failed `visible` stage** (`H02` untouched dt; `H07` SQL `repr(...)` error; `H08` `src/*.py`); `H03` failed `hidden`; ~27 tok/s decode, no infinite-loop bug |

**Diagnostic notes:**
- **`devstral-small2`:** Clean format compliance (`finish=stop` on all attempts) and passed visible tests on all 4 tasks by attempt 2, but could not repair subtle hidden edge cases even when hidden `AssertionError` feedback was supplied (`temp=0` repeated identical token counts on `H03` `[2047, 2140, 2140]` and `H08` `[1176, 1176, 1176]`).
- **`glm47-flash`:** No Jan-2026 loop regression on SYCL `head-a956a852` (terminated `stop` on all 12 calls at ~27 tok/s), and multi-turn tool calls passed cleanly. However, it burned `21,258` tokens/task (2.6× `solo-lead`, 2.2× `solo-deep`) while failing basic visible pytest suites on 3/4 tasks.

**Decision:** **Reject both `devstral-small2` and `glm47-flash` for coding (`deep` or `lead`).** Leave both candidate profiles in `ai-5820-01.yml` as archived test records only, or prune in cleanup; do not promote.

---

## 3. Lever 3 — Complementarity ($\beta$) & Monoculture Diagnosis

From `evaluations/nexus_e2e/evidence/20261125T193127Z/complementarity.md`:

| Pair (A vs B) | Shared scope | A % | B % | Both pass | Only A | Only B | $\beta$ (both fail) | Union % | Takeaway |
|---|---|---|---|---|---|---|---|---|---|
| `solo-lead` vs `solo-deep` | 30 paired trials | 96.7% | 86.7% | 25 | 4 (`H07`×3, `H02`#3) | 1 (`H03`#3) | 0.0000 | 100.0% | Across tasks (ever-solved), `solo-deep` solves **0** tasks `lead` didn't solve (`Only B ever = —`), while missing `H07` 0/3 |
| `solo-lead` vs `solo-rocm` | 30 paired trials | 96.7% | 86.7% | 25 | 4 (`H08`×3, `H02`#2) | 1 (`H03`#3) | 0.0000 | 100.0% | Same `Qwen3.8-27B` GGUF (`sha256:322e194f`); `Only B ever = —`; `reasoning=off` loses `H08` 0/3 |
| `solo-deep` vs `solo-rocm` | 30 paired trials | 86.7% | 86.7% | 22 | 4 (`H08`×3, `H02`#2) | 4 (`H07`×3, `H02`#3) | 0.0000 | 100.0% | Disjoint blind spots (`H07` vs `H08`), both strictly dominated by `solo-lead` (`96.7%`) |
| `solo-lead` vs `cand-devstral-small2` | 4 rep-1 subset | 100.0% | 0.0% | 0 | 4 | 0 | 0.0000 | 100.0% | Challenger adds **0** solves |
| `solo-lead` vs `cand-glm47-flash` | 4 rep-1 subset | 100.0% | 0.0% | 0 | 4 | 0 | 0.0000 | 100.0% | Challenger adds **0** solves |
| `cand-devstral-small2` vs `cand-glm47-flash` | 4 rep-1 subset | 0.0% | 0.0% | 0 | 0 | 0 | **1.0000** | 0.0% | Both fail all 4 subset tasks |

**Caveat:** `engx-hard` has only 10 tasks (`solo-lead` hits 10/10 across reps), so low $\beta$ between `lead` and `deep`/`rocm` reflects `lead` solving almost the entire small corpus rather than genuine non-Qwen diversity. Before evaluating any multi-model ensemble or router, expand the evaluation corpus (`> 50`–`100` held-out tasks or the Nexus pack).

---

## 4. Per-Role Recommendations & Action Plan

### 4.1 `lead` (`ai-5820-01` GPU 0 — `Qwen3.8-27B-UD-Q4_K_M`, `reasoning=on/4096`) — **KEEP & PROMOTE ROUTING PRIORITY**
- **Evidence:** Highest measured coding acceptance (`96.7%`, `29/30`), zero always-fail tasks on `engx-hard`, live CAIS `coding.routine` grant `q-coding.routine-412a2b3ad304-85f81041` (`12/12 = 100%`), and live CAIS `coding.complex` bundle `evaluations/cais/results/2026-11-26/coding.complex-322e194ff797-20261126T124250Z.json` (`19/20` trials, `9/10` tasks passed, `pass_lower_bound: 0.7176 >= 0.45`, `context_envelope: 10,798`, `rescore` 0 mismatches).
- **CAIS Grant Recorded (Repo):** Granted locally in `inventory/production/cais/` as `q-coding.complex-412a2b3ad304-b1d7481e` (`expires_at: 2027-01-25T15:01:39+00:00`, `cais_cli verify` valid=true); deliver to `/var/lib/aihost/cais` on `ai-5820-01` via reviewed PR + gateway converge per `docs/operations/cais.md`.
- **Follow-up Routing Fix (Separate PR after ledger delivery):** Stop `escalate-retry`, `escalate-after-failure`, and `deep-tasks` from routing away from `lead` (`96.7%`) to `deep` (`86.7%`), and fix `orchestrator_gateway_pool_quality_weights` (currently `deep: 3.0 > rocm: 2.5 > lead: 2.0`, and `code/tools` requests under `engineering/auto` select `rocm`/`lead` with `reasoning=off`).

### 4.2 `deep` (`ai-5820-01` GPU 1 — `Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M`, `reasoning=on/4096`) — **RETAIN SHORT-TERM ONLY; REPLACE WHEN A STRONGER B65 MODEL QUALIFIES**
- **Why not replace today:** Both on-disk alternatives (`devstral-small2`, `glm47-flash`) scored `0/4` vs `deep`'s `8/12` on the same subset, and `deep` holds valid CAIS `coding.routine` (`12/12`) + `coding.complex` (`8/10` in bundle `coding.complex-935587187e4b-20261122T131947Z.json`) grants on `sha256:6cd97c37...`.
- **Why replace next:** `deep` trails `lead` by `-10.0 pts` (`86.7%` vs `96.7%`), fails `H07-sqlite-rebuild` deterministically (`0/2` in CAIS + `0/3` in Stage 1), uses more tokens (`9,489` vs `8,289`), runs an extreme `IQ1_M` (`1.75 bpw`) quant, and carries Qwen Community / MaaS license constraints.
- **Next B65-fit candidates (requires external download + candidate transaction + CAIS):**
  1. **`Nanbeige4.3-33B`** (Q4_K_M / UD-Q4 fits 32 GiB B65; check exact VRAM + 64k KV headroom on SYCL).
  2. **`Gemma 4 26B-A4B`** (Apache 2.0 MoE, ~16–18 GB Q4, fits B65 comfortably; run SYCL long-prompt smoke first).
  3. **`gpt-oss-20b`** (Apache + usage policy, ~12–16 GB Q4; strong tool/reasoning control per CAIS fleet survey).
  4. **`Qwen3.6-35B-A3B UD-Q4_K_M`** (`sha256:ac0e2c11...`, already on `ai-5820-01`; optional re-test on SYCL `head-a956a852`, noting prior `2f494061` CAIS run missed bars at `6/10` complex).

### 4.3 `rocm` (`ai-ms-s1-max-01` — `Qwen3.8-27B-UD-Q4_K_M`, `reasoning=off`) — **RESET ROLE / DO NOT CLAIM CODING DIVERSITY**
- **Hardware & artifact facts verified on `ai-ms-s1-max-01`:** `122 GiB` RAM, **`61.35 GiB`** usable GTT pool (`0.5 GiB` VRAM carve-out; `≥ 8 GiB` headroom gate → `≤ ~53 GiB` total model + KV + runtime). Current `Qwen3.8-27B-UD-Q4_K_M` (`16.5 GB`, identical `sha256:322e194f...` to `lead`) decodes at **`~12.6 tok/s`** (`149s` prefill at `44.9k` tokens) and leaves `~20 GB` headroom for on-demand `R-ocr` / `R-img` bolt-ons. In `engx-hard` with `reasoning=off`, it achieves **`86.7%`** (`185.0s` mean wall, `4,850` tokens), solves `H07` `3/3`, but fails `H08-glob` **`0/3`** and adds **0** unique task solves over `lead`.
- **Two clear paths (operator choice):**
  - **Path R1 (Zero-download Capability Mix — recommended short-term):** Keep `ai-ms-s1-max-01` strictly as **general / long-context text + visual bolt-on host** (`R-ocr`, `R-img`), stop sending coding-shaped `engineering/auto` traffic there preferentially over `lead` (adjust `pool_quality_weights` so `lead > rocm` for coding), and optionally evaluate the already-on-disk **`Qwen3.6-35B-A3B UD-Q6_K`** (`28.7 GiB` GTT peak leaving `32.6 GiB` free, **`37.7→73.8 tok/s`** decode, `5.31s` 8k cold TTFT per `research/rocm-strix-halo/evidence/20261121T073429Z/recommendation.md`) if fast interactive throughput / GTT headroom for concurrent bolt-ons outweighs sharing `Qwen3.8-27B`'s weights.
  - **Path R2 (True non-Qwen or Strix-sized replacement — requires download):** Evaluate **`Gemma 4 26B-A4B`** (Apache 2.0 MoE, non-Qwen diversity, preserves bolt-on GTT headroom) or **`Qwen3-Coder-Next 80B-A3B Q4_K_M`** (`45.2 GiB` GGUF, `~49 GiB` total at `64k` leaving `~12 GiB` free — sole-tenant coding only, incompatible with concurrent `R-ocr`/`R-img`). Note: `DeepSeek V4.1 Flash IQ1` (`~121 GiB`) and `gpt-oss-120b` (`59–61 GiB` weights) **do not fit** the `61.35 GiB` GTT pool under the `8 GiB` headroom gate.

### 4.4 Stage 3 Collaboration & Harness Roadmap
- Keep Stage 3 triple frozen.
- Next engineering lever: build out the **Nexus E2E multi-turn agent pack (`≥ 50`–`100` tasks)** so harness improvements (repro-first tests, targeted BoN fallback, executable-critique gates) and future candidate models are measured off the `96.7%` ceiling of 10-task `engx-hard`.
