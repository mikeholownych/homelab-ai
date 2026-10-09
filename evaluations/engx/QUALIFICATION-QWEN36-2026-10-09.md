# Qwen3.6-35B-A3B lead qualification (2026-10-09)

## Identity and disposition

- Candidate alias: `candidate/qwen36-lead`, tested remotely through `https://10.0.8.5:8443`.
- Model: `Qwen3.6-35B-A3B-UD-Q4_K_M`, llama.cpp `b11347-5fc4f3c8c`.
- Artifact: `sha256:ac0e2c1189e055faa36eff361580e79c5bd6f8e76bffb4ce547f167d53e31a61`.
- Context: 65,536; selected worker reasoning budget: 8,192.
- Q-BUDGET selected 8,192 as the best measured quality point. Q-TOOLS, Q-LONGCTX, and the mmap/fault snapshots passed. Production promotion and final lifecycle checks remain.

## Q-BUDGET

Stage B used the hard 10-task corpus, three repeats per budget, temperature 0, and up to three attempts per task through the gateway. The gateway reported each requested server budget before the run.

| Budget | Validated | Per repeat | First attempt | Median seconds to validation | Mean seconds/task | Mean tokens/task | Always failed |
|---:|---:|---|---:|---:|---:|---:|---|
| 2,048 | 46.7% | 4/6/4 | 16.7% | 91.1 | 141.0 | 12,279 | H07, H08 |
| 4,096 | 70.0% | 8/7/6 | 36.7% | 108.7 | 189.7 | 13,919 | H08 |
| **8,192** | **76.7%** | 7/8/8 | 63.3% | 155.8 | 253.9 | 17,029 | H08 |

8192 gained two validated task-runs over 4096 (76.7% vs 70.0%) at 1.34x mean time and 1.22x mean tokens. 2048 had substantially lower quality. H08 failed at all three points. Under the operator's quality-over-speed rule, 8192 is selected among the required measured points. Raw results are `results/qbudget-20261008/eng-hard-qwen36-lead-bounded-{2048,4096,8192}.json`.

## Reasoning control and budget report

Two additional requests used the remote candidate alias with `X-AIHost-Reasoning: off` and `low`. Both returned HTTP 200, finish `stop`, and served the expected model. The `off` response had no `reasoning_content`; the `low` response included reasoning content. The gateway evidence chain recorded `thinking=false, reasoning_budget=0` for `off` and `thinking=true, reasoning_budget=2048` for `low`, both on worker `candidate-qwen36-lead`. The probe emitted only response metadata, not model reasoning text.

- `off`: API response `chatcmpl-c805551a18084b22ab468cd6`; gateway worker-selection evidence `c805551a-1808-4b22-ab46-8cd68d0066e6`.
- `low`: API response `chatcmpl-805586a6f1414412a22ad176`; gateway worker-selection evidence `805586a6-f141-4412-a2a2-d176b62de2db`.
- `/v1/models` and the long-context qualification response reported the 8,192 worker budget.

This verifies per-model reasoning control for the `off` and `low` profiles and the selected hard budget. The API output contract was exercised by Q-TOOLS structured output, tool-call formatting, streaming, and agent-loop checks, as well as the Q-LONGCTX context-limit rejection.

## Q-TOOLS

All seven synthetic categories passed all three trials: single tool call, `tool_choice=none`, named tool choice, parallel calls, streaming calls, structured output, and agent loop. All 20 recorded Nexus replay cut points passed. Evidence: `results/qualify-20261009/qualify-tools-qwen36-lead-bounded-8192-2026-10-09.json`.

The artifact-digest capability evidence verifies `tools`, `parallel_tool_calls`, `structured_output`, and `streaming`. The output-contract evidence is recorded in this qualification report and the Q-LONGCTX result.

## Q-LONGCTX and Q-MMAP

All 12 exact-token needle probes passed at 16,384, 32,768, 49,152, and 55,296 target tokens, each at 10%, 50%, and 90% depth. The largest counted prompt was 55,833 tokens; throughput at this depth was about 921-968 prompt tokens/s and 43 tokens/s decoding. An over-context prompt counted at 67,327 tokens received HTTP 400 in 0.14 seconds with the exact 65,536 context limit. Evidence: `results/qualify-20261009/qualify-longctx-qwen36-lead-bounded-8192-2026-10-09.json`.

The before/after host snapshots bracket the long-context probes. Candidate worker port 8002 reported 127 major faults at both snapshots; its 22,134,528,992-byte GGUF had 22,134,530,048 bytes cached at both snapshots. The host-wide major-fault counter increased from 128,981 to 129,011 during the interval. Snapshot files: `results/qualify-20261009/qwen36-lead-bounded-8192.mmap-{before,after}.prom`.

## Promotion and final gate

Qwen3.6 was promoted to the lead pool at reasoning budget 8,192 in commit `998189a`. Post-reboot and post-rollback-restoration
production requests passed through both promoted aliases. See `QUALIFICATION-QFINAL-2026-10-09.md` for the system checks and
the recorded rollback limitation.
