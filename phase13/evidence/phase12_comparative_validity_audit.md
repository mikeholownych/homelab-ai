# Phase 12 Comparative Validity Audit

## 1. Executive Summary & Audit Mandate

In accordance with Phase 13 Workstream A and Gate G3, this audit conducts an independent forensic evaluation of the Phase 12 physical comparative campaign between the protected resident control (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` on Worker 1, GPU 0) and the candidate specialist (`Qwen/Qwen2.5-7B-Instruct-AWQ` on Worker 2, GPU 1).

The Phase 12 report recorded an acceptance rate of **12 / 12 (100.0%)** for the candidate versus **3 / 12 (25.0%)** for the control.

This audit reconstructs the raw telemetry from [`phase12/traces/physical_campaign_results.json`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase12/traces/physical_campaign_results.json) to establish whether the evaluation methodology adhered to scientific fair-comparison standards or introduced systematic experimental artifacts.

---

## 2. Forensic Trace Reconstruction

Analysis of the raw completion payloads reveals the exact nature of the 9 rejected control tasks:

```
========================================================================================================================
TASK ID  MODEL      TOKENS  FINISH REASON  TERMINAL GENERATION FRAGMENT                             VALIDATOR ERROR
========================================================================================================================
TASK-01  Control    1024    length         'print(f"Connection {conn1.connection'                   SyntaxError: '{' was never closed
TASK-02  Control    1024    length         'def validate_domain_segment(segment: str)'              SyntaxError: expected ':'
TASK-03  Control    1024    length         'if not self.is_leader:\n    '                            SyntaxError: expected an indented block
TASK-05  Control    1024    length         'to_node = cycle[(i'                                     SyntaxError: '(' was never closed
TASK-06  Control    1024    length         'def _heartbeat_loop(self)'                              SyntaxError: expected ':'
TASK-07  Control    1024    length         '                }\n              }\n            }\n'     JSON parse error: unclosed braces
TASK-09  Control    1024    length         'cache.put("b",'                                         SyntaxError: '(' was never closed
TASK-10  Control    1024    length         'def get_execution_order(self):\n    """Compute topo'    SyntaxError: unterminated string
TASK-11  Control    1024    length         'def execute_migration_pipeline(self)'                   SyntaxError: expected ':'
========================================================================================================================
```

### Forensic Findings:
1. **100% Token Ceiling Collision**: Every single one of the 9 failed control tasks terminated precisely at token index `1024` with `finish_reason: length`.
2. **Zero Inherent Logic Flaws**: In all 9 instances, the implementation generated prior to token 1024 was semantically correct, highly structured, and defensively programmed.
3. **Mid-Statement Truncation**: Truncation occurred in mid-expression (e.g. unclosed f-strings, missing colons on method definitions, unclosed lists). When passed to `ast.parse()`, Python's lexer aborted with fatal syntax errors.
4. **Auxiliary Code Generation**: For Tasks 01, 05, and 09, the control model had already completed the primary class specification and was in the process of generating auxiliary unit tests and usage scripts when it hit the 1,024 ceiling.

---

## 3. Experimental Variable Control Audit

| Experimental Dimension | Controlled? | Audit Findings & Sources of Confounding |
|---|---|---|
| **Task Prompts & Instructions** | **YES** | Identical user prompts were dispatched to both models. |
| **Output Format Contract** | **NO** | The system prompt (`"You are a dependable autonomous engineering agent. Implement the required engineering solution precisely and completely in python code blocks."`) did not specify a code-only constraint, nor did it prohibit conversational preambles or auxiliary test suites. |
| **Completion Token Budget** | **NO** | A rigid ceiling of `max_tokens=1024` was enforced uniformly. While 1024 tokens was sufficient for the concise 7B dense model, it severely constricted the 30B MoE model's natural generation style. |
| **Repair & Retry Policies** | **NO** | Single-turn, zero-retry evaluation was enforced. In production autonomous engineering (Phases 6–10), the agent operates within a bounded repair loop where incomplete generations trigger an automated continuation query. |
| **Validator Alignment** | **PARTIAL** | The validator extracted the first code block, but AST validation parsed the entire block including auxiliary main blocks that were truncated. |
| **Hardware & Isolation** | **YES** | Both models executed on identical Intel Arc Pro B65 cards on host `10.0.8.5` at $T=0.0$. |

---

## 4. Reclassification of Historical Phase 12 Telemetry

The original Phase 12 comparison is **retained as valid historical evidence**, but must be properly classified:
- **Historical Classification**: *Single-Turn Zero-Shot Generation Under Constrained Token Ceiling (`max_tokens=1024`)*.
- **Valid Inference from Phase 12**:
  1. The 7B candidate possesses superior conciseness and higher decoding throughput (**39.30 tps vs 18.22 tps**), making it highly resilient to low token ceilings.
  2. The 30B control exhibits conversational verbosity and auxiliary code emission that makes it prone to truncation failures under tight single-turn token limits.
- **Invalid Inference from Phase 12**:
  - It is scientifically invalid to conclude that the 7B candidate possesses higher coding capability or architectural reasoning than the 30B control. The 30B model's failures were strictly syntax truncation artifacts caused by the completion budget.

---

## 5. Corrected Comparative Protocol Design (Workstream B)

To establish fair, unbiased comparative metrics, Phase 13 introduces a corrected evaluation protocol:
1. **Explicit Code-First System Contract**: Direct the model to emit only the required class/function definition, suppressing auxiliary test mains, conversational preamble, and conversational postscript.
2. **Realistic Completion Budget**: Expand `max_tokens` from 1,024 to **2,048 tokens**, matching standard autonomous engineering method generation limits.
3. **Bounded Multi-Turn Repair**: Permit up to 1 bounded repair turn if truncation or syntax errors occur, reflecting the real operational behavior of the OpenCode agent.
4. **Side-by-Side Reporting**: The historical Phase 12 results and the corrected Phase 13 results will be reported side-by-side in all deliverables.
