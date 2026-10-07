# Accuracy comparison on ai-5820-01 (same model: Qwen3-Coder-30B-A3B-Instruct, greedy decoding)

| Metric | vLLM 0.29 + AWQ-4bit (GPU0) | llama.cpp SYCL + Q4_K_M GGUF (GPU1) |
|---|---|---|
| HumanEval pass@1 (164, bwrap sandbox) | 91.5% (150) | 93.3% (153) |
| Needle retrieval, 4k/16k/37k tokens (9 cases) | 9/9 | 9/9 |
| Tool calls: correct function (20) | 20/20 | 20/20 |
| Tool calls: exact arguments (20) | 19/20 (dropped a directory from a path) | 20/20 |
| Code-edit fidelity, hidden tests (8) | 8/8 | 8/8 |
| Decode (free text / code edit, via gateway) | ~18 / ~58 tok/s (ngram spec) | ~58 / ~62 tok/s |
| Cold prefill (20k tokens) | ~5 s | ~19-21 s (warm prefix: <1 s) |

Method notes: first run had two harness bugs (code-fence regex; needle sizes beyond the context window)
that were found by inspecting failures and fixed before these numbers. 164-problem HumanEval has a
standard error of about 2 points, so the 3-problem gap is not significant alone; every metric points
the same direction.
