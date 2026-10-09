# Flash-Next gateway qualification (2026-10-08)

Candidate: Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M, artifact
`sha256:935587187e4b734ef8bbdf37ce19c897cc63830f59135715c7d1458c12faf6a2`.
Qualification ran from the controller through the TLS gateway at
`https://10.0.8.5:8443`, using the restricted `candidate/flashnext-deep` alias
with the gateway-confirmed reasoning budget of 4096. No inference workload was
started on the host.

## Evidence

- Q-BUDGET: 2048 reached 80% (9/7/8), 4096 reached 90% (9/9/9), and 8192
  reached 90% (9/9/9). At 8192, median time to validation was 495.1 s and mean
  tokens per task 14,149, versus 271.5 s and 9,176 tokens at 4096. H07 failed
  in all three repeats at every budget. The serving decision remains 4096.
  See [QBUDGET-2026-10-08.md](QBUDGET-2026-10-08.md) and the raw run records in
  `results/qbudget-20261008/`.
- Q-TOOLS: all seven synthetic checks passed 3/3 each: single tool call,
  `tool_choice=none`, named tool choice, parallel calls, streamed calls,
  structured output, and a hidden-test-graded agent loop. All 20 Nexus replay
  cut points passed the structural tool-call/answer check.
- Q-LONGCTX: all 12 planted-fact retrieval probes passed at 16,384, 32,768,
  49,152, and 59,392 target tokens, with facts placed at 10%, 50%, and 90%.
  Exact tokenizer counts for the largest prompts were 59,910–59,913. A 67,335
  token prompt was rejected by the gateway with HTTP 400 in 0.14 s, identifying
  the 65,536 token context limit.
- Q-MMAP: before/after snapshots bracket the long-context run in
  `results/qualify-20261008/flashnext-deep-bounded-4096.mmap-{before,after}.prom`.
  Worker 8003's major-fault counter remained 91; the second GGUF shard's cached
  pages increased from 1.76 GB to 2.33 GB. The first shard remained fully
  cached at approximately 29.6 GB.

Machine-readable evidence is in
`results/qualify-20261008/qualify-tools-flashnext-deep-bounded-4096-2026-10-08.json`
and
`results/qualify-20261008/qualify-longctx-flashnext-deep-bounded-4096-2026-10-08.json`.
Both records bind the results to the serving artifact digest and contain only
verdicts, token counts, timings, and tool names; Nexus session contents are not
stored.

## Reasoning profile verification (2026-10-09)

With the same artifact served through the candidate alias, remote `off` and
`low` profile requests both returned HTTP 200 and finish `stop`. The `off`
response had no `reasoning_content`; `low` returned reasoning content and the
gateway evidence chain recorded a 1,024-token effective budget (25% of the
4,096 worker cap). The `worker_selected` records show `thinking=false,
reasoning_budget=0` for `off`, and `thinking=true, reasoning_budget=1024` for
`low`. Only response metadata was retained. See
`results/qualify-20261009/flashnext-reasoning-profile-probe.json`.

## Disposition

Flash-Next passed the remote tool and context qualification gates at the
4096-token reasoning budget. Its long-context probes passed through 59,913
counted prompt tokens, with clean gateway rejection above the advertised
context. Reasoning on/off profile control is also verified for this artifact.
This evidence supports the selected deep-pool candidate; final promotion and
reboot/rollback checks are recorded in `QUALIFICATION-QFINAL-2026-10-09.md`.
