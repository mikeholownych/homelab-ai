# Window 3: model load / reload under failure (backlog: "default mmap and --no-mmap")

Run on ai-5820-01 GPU0 (worker1 stopped after an idle-gateway check, reconcile timer paused, production restored by `harness/restore_baseline.sh` every time: rc 0, gateway ready, 2/2 workers).
Image `localhost/sycl-research/llama@sha256:6cd97c37…` (the promoted one), Qwen3.6-35B-A3B Q4_K_M, production flags, ESIMD=0, research server on :18100/:18101, not via the gateway.
Harness: `harness/window3_load_failure.sh`. Logs: `load-run1-mmap-ok-nommap-invalid-flag.log` (mmap valid; its `--no-mmap` half invalid), `load.log` (modes none, dio).

Finding about the flag: this build has no `--no-mmap`; it uses `-lm/--load-mode {auto,none,mmap,mlock,mmap+mlock,dio}` (`error: invalid argument: --no-mmap`). Run 1 `nommap` rows are invalid and are not results.

| Case | auto/mmap (default) | `-lm none` | `-lm dio` |
|---|---|---|---|
| A clean load to healthy, then a request | 98 s, ok | 97 s, ok | 97 s, ok |
| B SIGKILL 10 s into load, then reload | unit inactive, reload 97 s, ok | inactive, 97 s, ok | inactive, 97 s, ok |
| C second server on the busy GPU | fails cleanly, first stays healthy and serves | same | same |
| host RAM after load (used) | ~6.2 GB | ~6.7 GB | ~6.7 GB |
| kernel `Timedout job` after each mode | 32 (unchanged) | 32 | 32 |

Conclusions: load time is the same in all three modes (about 97 s, dominated by device upload); there was no mmap hang, no stuck process after SIGKILL during load, and reloading after a kill needed no cleanup; mmap versus no-mmap makes no difference here, so keep the default. Case C fails with an explicit message
(`cannot allocate 18543 MiB … 9605 MiB free of 32656 MiB`, exit due to model loading error) and does not disturb the running server. Observation: the colliding process takes a general protection fault in libc during exit after the failed load
(`dmesg`: llama-server … in libc.so.6, once per mode run); it is exit-time only, with the failure already reported, but worth knowing if a supervisor ever restarts a worker into a full GPU.
Limits: one model (the 22 GB MoE), one GPU, memory-resident files (page cache warm: buff/cache about 52 GB), so a cold-cache load from disk was not measured.

## Nexus Code tool-definition tokens per turn (backlog 620, 2026-11-17)

Method: imported every `toolDefinition` from `nexus-code/cli/src/core/capability_definitions/*.ts` (36 tools, compact JSON).
Size 17,012 characters. Token count is an estimate (no exact tokenizer call: that needs a client key, which was not read):
about 4.3k tokens at 4 chars/token, 5.7k at the gateway's conservative 3 chars/token. That is roughly 7-9% of a 64K context.

Verdict: not material. The tool block is the constant prefix of every request, so after the first turn it is served from the
prefix/slot cache (the gateway keeps a conversation on one worker), and it costs prefill only once per conversation.
No reduced-tool-set A/B was run (the item says only if material). Caveat: assumes the CLI sends all 36 tools; a per-mode subset would be smaller.
Re-measure exactly with `qualify.py`'s `/v1/tokenize` path if tool count grows past ~60.

## HEAD router and sleep-idle flags (backlog 638, 2026-11-17)

`llama-server --help` of the deployed image (`sha256:6cd97c37…`): router mode is opt-in (`--models-dir`, `--models-preset`,
`--models-max` default 4, `--models-memory-margin`, `--models-autoload` default on, all "default: disabled" unless a models dir
or preset is given). `--sleep-idle-seconds` defaults to -1 (disabled). Neither flag is in the production worker units
(grep count 0 in both), so both features are inert in production. Any use needs its own gate: a sleeping worker would break the
gateway's health and idle assumptions (the idle check greps for activity, a sleep/wake cycle reloads the 22 GB model, ~97 s).

## Gateway load sweep and long/short interleave (backlog 616, 625, part of 623; 2026-11-17)

Run from the controller through the authenticated TLS gateway only (`evaluations/engx/gateway_load.py`, playbook
`probe_mode: load`, idle gate passed, qualification client, quota 60 rpm). Deployed image, `-np 1` workers.
Raw: `gateway/load-1-load-engineering-{lead,deep}.json`. Prompt shape: ~1k tokens, 128 max tokens, streamed; 3 requests per
concurrency level per client slot.

| Route | Concurrency | statuses | TTFT p50 / p95 (s) | TPOT p50 (ms) | chunk gap p95 (ms) |
|---|---|---|---|---|---|
| lead | 1 / 2 / 4 | all 200 | 0.08 / 4.22 (first request cold), 0.28 / 0.36, 0.85 / 0.91 | 17.9 / 17.8 / 18.2 | 16-17 |
| deep | 1 / 2 / 4 | all 200 | 0.15 / 1.67, 0.72 / 0.82, 2.00 / 2.10 | 56.5 / 56.5 / 56.4 | 54-55 |

- Decode speed (TPOT, chunk gaps) is flat across concurrency: requests are serialised, not slowed. TTFT rises about linearly with
  concurrency (queue wait behind a single slot). No 429/503/timeouts up to 4 concurrent, so the gateway queue absorbs it; the
  queue bound itself was not reached (a 503/429 threshold test needs a larger, deliberately saturating run: 623 stays open).
- Interleave (about 10k-token prompt, long -> short -> long, same prefix): lead long-1 TTFT 6.7 s cold, short 0.23 s, long-2 0.26 s
  with 10016/10020 prompt tokens served from cache; deep: 14.0 s, 0.43 s, 0.31 s, again 10016 cached. The intervening short
  request does NOT evict the long prefix on the deployed build with the default `--cache-ram`, so no raised-cache comparison is
  needed for this shape. Not tested: several different long conversations alternating (capacity, item 632).

## Cache capacity with alternating long conversations (backlog 632, 2026-11-17)

`gateway_load.py --scenario alternate` (playbook `probe_mode: alternate`): three distinct ~18k-token prefixes A, B, C sent A B C A B C
through the gateway to each route (raw: `gateway/alt-1-load-engineering-{lead,deep}.json`).

| Route | Round 1 TTFT (cold) | Round 2 TTFT | Round 2 cached tokens |
|---|---|---|---|
| lead (Qwen3.6-35B) | 10.0-10.1 s | 0.32-0.35 s | 18018 of 18022 for A, B and C |
| deep (Flash-Next) | 25.3-25.4 s | 0.74-0.79 s | 18018 of 18022 for A, B and C |

All three conversations were still cached after the other two had run, so the deployed `--cache-ram` default holds at least
3 x 18k tokens per worker without eviction, a 30-40x TTFT difference. Host RAM at the time: 10 GB used, 50 GB available of 61.
Not measured: the point at which eviction starts (more or longer conversations; 64K-token ones), and idle-vs-active eviction order.
Those need a larger run; at 18k tokens the three-way case already costs 10-25 s per cold turn.

## Hybrid-model checkpoint: continuation vs mid-prompt fork (backlog 630, 2026-11-17)

`gateway_load.py --scenario fork` (raw: `gateway/fork-1-load-engineering-{lead,deep}.json`). One ~18k-token conversation, four steps, `-np 1`.

| Step | lead TTFT / cached of prompt | deep TTFT / cached of prompt |
|---|---|---|
| cold | 10.4 s / 0 of 18020 | 25.4 s / 0 of 18020 |
| continuation (same prefix + one new turn) | 1.6 s / 15968 of 18032 | 3.8 s / 15968 of 18032 |
| fork at mid-prompt (first half shared, second half new) | 8.7 s / 0 of 15020 | 21.3 s / 0 of 15020 |
| original again (after the fork) | 10.1 s / 0 of 18020 | 25.0 s / 0 of 18020 |

- Continuation reuses the prior state up to a checkpoint (15968 tokens; the last ~2k are recomputed), so an agent that only appends
  is cheap: 6x faster on lead, 7x on deep.
- A fork inside the prompt gets NO reuse on these hybrid (recurrent + attention) models: the shared first half is recomputed in full,
  and it also cost the earlier conversation its cache (original-again was cold). This is the opposite of the alternating test, where
  complete repeats of three conversations were all retained, so the loss comes from the fork, not from capacity.
- Consequence: anything that rewrites earlier history (context compaction, edited system prompt or tool list mid-session, a regenerated earlier
  turn) pays a full prefill on lead/deep (10-25 s at 18k, about 6.7-14 s per 10k). Nexus Code should keep the prefix append-only; this
  is also why the tool block (item 620) must stay byte-stable across turns.
- Not tested: the Coder-30B full-attention model (not deployed; item 627), and `-np 2` slots.

## Trace replay from a real Nexus session (backlog 631, 2026-11-17)

`gateway_load.py --scenario replay`: the local Nexus session with the most tool-call cut points under 120k characters (digest
`1121b29305cd`; content is sent to the gateway only, never written: the result files hold shapes, token counts and timings),
replayed as eight successive agent steps (2 to 46 messages, 6.5k to 10.6k prompt tokens), once per route. Raw:
`gateway/replay-1-load-engineering-{lead,deep}.json`.

| Route | Step 1 (cold) | Step 2 | Steps 3-8 cached share | Whole 8-step session |
|---|---|---|---|---|
| lead | 0 of 6491 cached | 76% | 96-97% | 13.5 s |
| deep | 0 of 6491 cached | 76% | 97% | 35.8 s |

Each step re-uses everything except the newest turn plus a ~300-token tail (the checkpoint granularity), so an append-only agent
session is almost entirely prefix-cached: cold prefill happens once. TTFT is blank for most steps because the model answered with
a tool call (no text delta); wall time per step is in the raw rows. The replay shows the intended workload shape is the cheap
case from the fork test; a rewrite of earlier history would break it (see the fork section). One session only, no sanitised corpus.

## test-backend-ops on the production build (backlog 636, 2026-11-17)

Build: `test-backend-ops` compiled from llama.cpp a956a852 with the production (old-stack, `8766c027`) `intel.Dockerfile`
and only `-DLLAMA_BUILD_TESTS=OFF` -> `ON` (Dockerfile copy kept out of the repo; the build used `docker build --target build`).
The binary was copied to the host research dir and run INSIDE the deployed image (`sha256:6cd97c37…`, its libraries and
runtime stack) on GPU0 with `GGML_SYCL_ENABLE_XMX_ESIMD=0`, one worker1 outage, idle gate and restore trap
(`harness/window3_backend_ops.sh`; restore rc 0; kernel `Timedout job` count unchanged at 32).

| Op | Result on SYCL0 (Arc Pro B65) | Not supported (skipped by the harness) |
|---|---|---|
| MUL_MAT_ID | 1152 / 1152 passed | 8 |
| FLASH_ATTN_EXT | 4375 / 4375 passed | 1335 |
| MUL_MAT | 2427 / 2427 passed | 625 |

Run 1 (`run1-f8-abort/`) aborted in all three ops at `convert.cpp:773: fatal error: unsupport data type=f8_e4m3`: the SYCL backend
has no f8_e4m3 dequantisation and the test suite does not skip those cases, so test-backend-ops crashes instead of reporting
"not supported". Before the abort: MUL_MAT_ID 130 OK, MUL_MAT 159 OK, FLASH_ATTN_EXT 4297 OK, 0 failures. Run 2 excludes
f8_e4m3 cases with `-p '^(?!.*f8_e4m3)'` (`harness/backend_ops_filter.sh`) and completes.

Reading: no numerical mismatch against the CPU reference in any supported MUL_MAT_ID (MoE routing, all quant types incl. q4_K,
IQ types), MUL_MAT or flash-attention case on the deployed build. Limits: f8_e4m3 is untested (none of our models use it), and an
unsupported f8 case aborting the process is an upstream test-suite gap worth a one-line mention if reported.

## Slot-reuse split: Coder-30B (full attention) vs Qwen3.6-35B-A3B (hybrid) (backlog 627, 2026-11-17)

Research server on GPU0 (production image and flags, `-np 1`, `-c 65536`, port 18100, not via the gateway), same ~18k-token four-step
client for both models (`harness/window3_slot_reuse.sh`, `harness/slot_reuse_client.py`; llama-server `timings`: `cache_n` reused,
`prompt_n` computed). One worker1 outage, idle gate, restore rc 0, `Timedout job` count unchanged at 32.

| Step | Coder-30B (full attention): computed / reused, wall | Qwen3.6 (hybrid): computed / reused, wall |
|---|---|---|
| cold | 18013 / 0, 16.9 s | 18015 / 0, 14.7 s (first request on a fresh server includes kernel warm-up) |
| continuation | **19 / 18005, 0.46 s** | 2064 / 15963, 1.69 s |
| fork at mid-prompt | **6009 / 9004, 5.3 s** | 15015 / **0**, 8.7 s |
| original again | 9009 / 9004, 7.4 s | 18015 / **0**, 10.2 s |

- Full attention (Coder): the KV cache is truncated at the first differing token, so a continuation is essentially free and a fork
  keeps everything before the divergence point (half the prompt here). Returning to the original then reuses that same shared half.
- Hybrid (Qwen3.6; Flash-Next behaved the same through the gateway): reuse needs a stored recurrent-state checkpoint, taken every
  ~2k tokens, so a continuation recomputes up to ~2k tokens and any divergence inside the prompt discards everything, including the
  earlier conversation. This matches the gateway fork test (same 8.7 s fork and ~10 s return on lead).
- Consequence for model choice and client design: a workload that edits or compacts earlier context favours the full-attention Coder model;
  an append-only agent loop is cheap on either. If Coder-30B is ever routed again, the gateway's affinity map is worth more there
  than on the hybrids.

## vLLM XPU feasibility on one B65 (backlog 628, 2026-11-17)

`harness/window3_vllm_xpu.sh`: `docker.io/vllm/vllm-openai-xpu:v0.29.0` (already in the aihost-runtime store), research server on :18200
(not via the gateway), GPU0 with worker1 stopped, idle gate, restore trap (rc 0 each time; `Timedout job` count unchanged at 32).

| Attempt | Result |
|---|---|
| Qwen2.5-7B-Instruct-AWQ (cached; `--quantization awq`, 8k context) | **Runs.** Healthy after 141 s. 1060-token prompt, 39 tokens out: TTFT 0.44 s (first), 0.13 s, 0.06 s; decode gap p50 about 24 ms (about 42 tok/s). Proves the image drives the B65 (device found, kernels run). |
| Our Qwen3-Coder-30B-A3B Q4_K_M GGUF (`--tokenizer` and `--hf-config-path` pointing at the HF repo's config/tokenizer files) | **Did not load (3 attempts).** vLLM 0.29.0 stops during config resolution in `transformers`: it reads the `.gguf` as a JSON config (`UnicodeDecodeError`, "not a valid JSON file"), with and without `--hf-config-path`. It never reached the model or the GPU, so this says nothing about MoE kernels. |

Conclusion: the engine is feasible on this hardware for a dense AWQ model, and the comparison harness (`harness/engine_probe_client.py`) works against it,
but Coder-30B was not demonstrated. The remaining routes need HF-format weights: FP8 is about 31 GB (does not fit with KV cache on a 32 GB card),
BF16 is about 61 GB with online FP8 quantisation (a 61 GB download and about 61 GB of host RAM pressure). That was judged out of
proportion for an engine comparison whose weights would differ from our GGUFs anyway (the KL gate would not apply). Logs: `run1/`, `run2/`,
`vllm-xpu-coder-gguf.logtail`. Side effect to know: an accidental root-podman pull of the same image was killed before it completed; the root store holds no vllm image.
