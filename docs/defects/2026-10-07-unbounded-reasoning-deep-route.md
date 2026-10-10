# DEFECT: unbounded reasoning on the deep route

- **Opened:** 2026-10-07 (found during the 2026-10-06 model evaluation, Phase B)
- **Status:** RESOLVED (2026-10-07). Remediated via Design 02 (W-REASON); bounded budgets (8192/4096) and total output bounds deployed in release f31218c and verified in production.
- **Severity:** high. Requests can consume minutes and tens of thousands of tokens and end without producing an answer.
- **Scope:** `engineering/deep` (worker `b0-live-llama-deep-worker2`, Qwen3.5-27B Q4_K_M, llama.cpp `5fc4f3c8c`). It probably
  applies to any route served by a reasoning-capable model.

## Observed (evidence)
Evidence lives in `ai-5820-01:~/engx/evidence/UNBOUNDED_REASONING/`.
- **Production configuration:** the deep worker runs with llama.cpp's default `--reasoning-budget -1` (unrestricted) and template-default
  thinking. The gateway applies no output bound when the client omits `max_tokens` (`orchestrator_runtime/runtime.py:499`
  clamps only a supplied value). Nexus never sends `max_tokens` (`nexus-code/cli/src/client.ts`, request payload).
- **Benchmark (same model, flags and image as production, 16384 max_tokens, thinking on, engx hard corpus, 3 reps):**
  - Qwen3.5-27B: 53.3% validated vs 70.0% with thinking off.
  - 33 of 67 attempts terminated at the output limit (`finish_reason=length`).
  - 37 attempts emitted no usable final answer.
  - About 10 h for 30 task runs.
- **Same condition, Flash-Next GSQ Coder (64K):** nearly every attempt consumed the full 16384-token output limit in about 15 minutes
  without an answer (1 pass in the first 16 task runs). With thinking off, the same model scored 80.0%.

## Production consequence (inferred from the above, not yet observed in Nexus telemetry)
A hard Nexus request routed to deep (`review`, `escalate`, `architecture`, `debug-hard`) can reason until the context ceiling.
- It consumes tens of thousands of tokens and several minutes, then ends with `finish_reason=length` and no final answer.
- Nexus reports this as `output_truncated`.
- It is a likely contributor to the Nexus context/latency issues.
- The failure belongs to SERVING_CONFIGURATION or REASONING_BUDGET_EXHAUSTION, not MODEL_CAPABILITY.

## Requirement (operator)
Fail closed. A client must not be able to request, or accidentally obtain, unlimited reasoning by omitting `max_tokens` or
equivalent controls.

## Remediation design: enforcement boundaries to evaluate
1. **Worker-side hard reasoning budget** (`--reasoning-budget N`, `--reasoning-budget-message`) as the final fail-safe.
2. **Route/profile reasoning policy selected by the client** (Nexus chooses a profile; the gateway/worker enforce its bounds).
   The client chooses, and the server enforces.
3. **Gateway-enforced total generation/output bounds**, including a default when the client omits `max_tokens`, sized from the
   worker's live limits.
4. **Telemetry** that reports reasoning-budget exhaustion distinctly from timeout, output-limit truncation, validator failure and
   ordinary model failure.

## Not decided
- The budget value. 4096 is only the first bounded qualification point (`THINKING_ON_BOUNDED_4096`, in progress). The value is
  chosen from the measured reasoning-token distributions and acceptance data, possibly with more budget points.
- Whether thinking should be on at all for the deep route. Superseded 12:30Z: bounded thinking >= thinking-off for every model tested (see update below).

## Update 2026-10-07 12:30Z: bounded-condition evidence (evaluations/engx/REPORT-2026-10-07.md)
- With `--reasoning-budget 4096` and an end-of-budget instruction, SERVING_CONFIGURATION_FAILURE fell to 0 in all four bounded runs.
  Qwen3.5-27B (prod deep model) went from 53.3% unbounded to 70.0% bounded.
- Flash-Next unbounded, from server logs: 42/44 completions at 64K and 7/7 at 32K ended at exactly the 16384-token ceiling.
- 4096 is binding for Qwen3.8, Qwen3.6 and Flash-Next (budget reached on about 100% of attempts). A budget sweep (2048/8192) is
  required before choosing the production value.
- The enforcement-boundary evaluation is in section 7 of the report. Recommendation: (1) worker budget, (3) gateway default total
  bound and (4) telemetry are mandatory. (2) client profiles select only and can only lower the limits.
