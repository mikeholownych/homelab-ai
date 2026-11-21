# Strix Halo deep bake-off scorecard

Weights: quality 0.30, ttft 0.30, tok_s 0.20, ops 0.20.
Axes are 0-1, higher is better; TTFT and tok/s are ratio-to-best **within the same model**
(see `harness/scorecard.py`). Engines run different artifacts of the same model (llama.cpp GGUF vs vLLM FP8), so this compares engine+artifact pairs, not engines alone.

| engine | model | score | quality | ttft (norm) | tok/s (norm) | ops | ttft geomean s | mean agg tok/s |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| llamacpp | coder30b | 1.000 | 1.00 | 1.00 | 1.00 | 1.00 | 0.87 | 47.5 |
| vllm | coder30b | 0.597 | 1.00 | 0.21 | 0.18 | 1.00 | 4.24 | 8.3 |
| llamacpp | q36_35b | 1.000 | 1.00 | 1.00 | 1.00 | 1.00 | 1.44 | 55.7 |
| vllm | q36_35b | 0.613 | 1.00 | 0.24 | 0.20 | 1.00 | 5.98 | 11.2 |
