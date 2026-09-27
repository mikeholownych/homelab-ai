# Phase 4 Model-Evaluation Boundary Specification
## Candidate Model and Quantization Evaluation Program for Intel Arc Pro B65

---

## 1. Objective and Scope

This document specifies the experimental protocol for evaluating candidate models and quantization topologies on Intel Arc Pro B65 hardware in Phase 4.

The frozen control baseline is:
- **Control Model**: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
- **Control Quantization**: AWQ-4bit
- **Control Topology**: TP=2 spanning dual B65 cards (or TP=1 per card where measured feasible)
- **Serving Runtime**: vLLM XPU (`vllm-openai-xpu` / Level Zero `libze-intel-gpu1=26.22.38646.7`)
- **Serving Parameters**: `max_model_len=16384` (64K max), `tool_call_parser=qwen3_coder`

No candidate models or quantizations are activated or deployed in Phase 3. This specification defines the evaluation boundary to be executed in Phase 4.

---

## 2. Candidate Configuration Candidates

Each candidate is evaluated as an indivisible deployed software/hardware tuple:

| Candidate ID | Model Identifier | Architecture | Quantization Format | Target Topology | Context Limit | Expected Memory Footprint |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `cand-qwen25-32b-int4` | `Qwen/Qwen2.5-Coder-32B-Instruct` | Dense Coder | AWQ-4bit / GPTQ-4bit | TP=2 | 32,768 | ~22.4 GiB per card |
| `cand-qwen38-27b-tp1` | `cyankiwi/Qwen3.8-27B-AWQ-INT4` | MoE Coder | AWQ-4bit | TP=1 (Per B65) | 16,384 | ~24.0 GiB (1 Card) |
| `cand-deepseek-lite-fp8`| `deepseek-ai/DeepSeek-Coder-V2-Lite` | MoE Coder | FP8 | TP=1 (Per B65) | 16,384 | ~16.8 GiB (1 Card) |
| `cand-phi4-fp8` | `microsoft/phi-4` | Dense SLM | FP8 | TP=1 (Per B65) | 16,384 | ~15.2 GiB (1 Card) |

**Rule**: Model suitability will never be inferred from parameter counts, active MoE parameters, or generic leaderboard rankings (e.g., LMSYS, HumanEval). It must be proven on local physical hardware against the representative engineering task cohort.

---

## 3. Evaluation Metrics and Hard Gates

### 3.1 Primary Reliability Metrics
1. **Independent Task Acceptance Rate ($A_R$)**: Fraction of registered tasks accepted by `IndependentValidator` in clean sandboxes without human intervention ($A_R = N_{\text{accepted}} / N_{\text{registered}}$).
2. **First-Pass Acceptance Rate ($F_R$)**: Tasks accepted without requiring retry or bounded repair.
3. **Scope Compliance ($S_C$)**: Percentage of attempts generating mutations strictly within authorized paths (`ScopeGuard` violations = 0).
4. **Tool-Contract Fidelity ($T_F$)**: Compliance with structured JSON / tool schema contracts (zero malformed tool calls or unparsed completions).
5. **Effective Pre-Validation Repair Rate ($R_E$)**: Percentage of review findings that result in successful repair rather than budget exhaustion.

### 3.2 Secondary Resource Metrics
1. **Host Memory Reserve**: Minimum host available memory during initialization and steady-state inference (must preserve $\ge 8.0$ GiB operational reserve).
2. **GPU Allocation Headroom**: Peak VRAM allocation relative to 31.89 GiB physical capacity.
3. **Time to Accepted Deliverable**: Wall-clock seconds from work order admission to supervisor terminal acceptance.
4. **Token Generation Efficiency**: Tokens per second and prompt prefill latency under concurrency 1 and 2.

---

## 4. Matched Comparison Protocol: Homogeneous vs. Heterogeneous Worker Pairs

In Phase 4, multi-worker cooperative configurations will be evaluated across three matched arrangements under identical compute budgets:

1. **Homogeneous Pair**: Two identical workers (e.g., `Author` [cand-A] + `Reviewer` [cand-A]).
2. **Heterogeneous Pair**: Complementary worker specialization:
   - High-capacity author (e.g. 30B Coder) + Fast strict reviewer (e.g. Phi-4 FP8 or DeepSeek Lite).
3. **Single-Worker Control**: Single model performing authoring with independent validator (no cooperative reviewer).

### Evaluation Cohort
Every candidate configuration will be subjected to the full 4-class engineering cohort:
- 10 Defect Repair tasks
- 10 Multi-File Implementation tasks
- 10 Test Development tasks
- 10 Maintainability / Refactoring tasks

Total: 40 tasks per candidate configuration, with all attempts, timeouts, and failures recorded.
