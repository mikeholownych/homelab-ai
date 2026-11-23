# R-text smoke: Qwen3.8-27B Q4_K_M on ai-ms-s1-max-01 (Task 6)

Verdict: **PASS** (shortlist entry #1; entries #2-#4 not needed).

## Setup
- Host: `ai-ms-s1-max-01` (10.0.8.6), 122 GiB unified, GTT total 65.87 GB.
- Artifact: `/var/lib/local-ai/models/gguf/qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf` (16,464,440,224 B).
  Copied from ai-5820-01 (same file serving the 5820 lead); sha256 verified on MS-S1:
  `322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482` (matches inventory `artifact_digest`).
- Engine: `ghcr.io/ggml-org/llama.cpp@sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184` (production HIP image).
- Temp container `llama-hip-rtext-smoke` as `aihost-runtime`, loopback `127.0.0.1:8190`, run **beside** the production
  Coder-30B worker (`llama-hip-qwen3-coder-30b`, :8101, never stopped):
  `-c 65536 -np 1 --jinja -ngl 99 -fa on --metrics`. `HIP_LAUNCH_BLOCKING` not needed.
- Load time ~5 s (page cache warm after copy). Model loaded with 1 slot, n_ctx_slot 65536.

## Checklist (`r-text-qwen38-27b-smoke.json`, driver `r-text-smoke.py`)
| Step | Result |
|---|---|
| Load `-c 65536 -np 1 --jinja -ngl 99` | OK, no OOM beside production |
| Chat completion | OK ("pong"; reasoning content emitted by template) |
| Tools round-trip (`prompts/orch_tools.json`, calculator 17*19) | OK: valid `calculator{"expression":"17*19"}` call, final answer `323` |
| No HIP garbage output | OK (coherent output, single-slot) |
| >32k prompt (44,909 prompt tokens) | OK, no OOM; prefill 300.8 tok/s |

## Performance
- Short prompt TTFT: 0.57 s (streamed). Decode: ~12.6 tok/s (79.5 ms/token); ~10.6 tok/s at 45k context.
- 44.9k-token prompt: TTFT 149 s (prefill 558 -> 306 tok/s as context grows). Fine for interactive short/medium
  turns; long-context cold prefill is slow (dense 27B on Strix Halo bandwidth). Not a kill under "unusable TTFT for
  interactive use" for typical turns, but a concern for large-context first turns (prompt caching helps follow-ups).

## Memory
- GTT used: 39.3 GB (Coder-30B only) -> 59.7 GB peak with both loaded (of 65.9 GB). Only ~6 GB headroom, so running
  Qwen3.8-27B at 64k *beside* Coder-30B Q8 is tight; a permanent co-tenant deployment needs a smaller ctx/quant or
  a decision on which model stays resident.

## Restore / production state
- Smoke container stopped (`podman stop`); GTT back to 39.29 GB.
- `llama-hip-qwen3-coder-30b.service` active (since 05:33 UTC, never restarted), `/health` ok on :8101.
- Pre-existing: production journal shows `unauthorized: Invalid API Key` warnings from an unauthenticated client
  (probe/scrape); not caused by this task.

## Host GGUF inventory (after task)
- `models/gguf/Qwen3-Coder-30B-A3B-Instruct-Q8_0.gguf` 32.5 GB (hardlink of `models/Qwen3-Coder-30B-A3B-Instruct-GGUF/...`) - production
- `models/gguf/qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf` 16.5 GB - **new**
- `models/Qwen3.6-35B-A3B-GGUF/Qwen3.6-35B-A3B-UD-Q6_K.gguf` 29.3 GB
- `models/Qwen3-4B-Instruct-2507-GGUF/Qwen3-4B-Instruct-2507-Q8_0.gguf` 4.3 GB
- `/var/lib/local-ai`: 1.0 TB, ~735 GB free.
