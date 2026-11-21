# ROCm Strix Halo harness

Wrappers in this directory should invoke
`../../sycl-optimization/harness/engine_sweep_client.py` for timed sweeps against
`127.0.0.1:<port>` (OpenAI-compatible chat completions). Use curl-based smoke helpers
for quick health and probe checks before deeper runs.

## gfx1151 starting points

| Engine | Notes |
| --- | --- |
| **llama.cpp** | CMake: `-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1151` |
| **vLLM** | Prefer `TRITON_ATTN`; do not assume `FLASH_ATTN` on this stack |
| **SGLang** | May be unavailable on stock ROCm 7.2 — record **unavailable** with evidence; do not invent zero tok/s |

If an engine cannot start in container or native form, archive the blocker under
`evidence/<ts>/` and move on; smoke phase is pass/fail/unavailable, not fabricated metrics.

## Phase 2b smoke scripts

All scripts run **on the lab host** (`mike@10.0.8.6`, rootless podman); sync with
`rsync -a harness prompts mike@10.0.8.6:rocm-bake/research/rocm-strix-halo/`, run, then
rsync `evidence/<ts>/` back.

| Script | Purpose |
| --- | --- |
| `download_probe_models.sh probe\|mid\|all` | Pinned HF downloads with sha256 verify → `/var/lib/local-ai/models/` |
| `run_smoke_{llamacpp_hip,vllm_rocm,sglang_rocm}.sh [probe\|mid]` | One engine x model smoke (ports 8101/8102/8103); needs `EVIDENCE_DIR` |
| `smoke_openai.sh BASE_URL MODEL PROMPT OUT` | Chat/tools request; `tools_supported=false` instead of failing |
| `stop_engine.sh` | Remove `rocm-bake-*` containers, kill `/tmp/rocm-bake-engine.pid` |

Engine exit codes: `0` pass, `1` fail, `2` unavailable (SGLang writes `UNAVAILABLE.md`).
Images are pinned by digest in each script. `HSA_OVERRIDE_GFX_VERSION` is never set
(gfx1151 native); vLLM forces `TRITON_ATTN`. Podman graphroot on the host was moved to
`/var/lib/local-ai/podman-mike/storage` (root fs only has ~50 GiB free).

## Phase 2c deep bake-off

| Script | Purpose |
| --- | --- |
| `run_deep_bakeoff.sh ENGINE MODEL` / `all "e:m ..."` | One engine x model pair on the lab host (`llamacpp\|vllm` x `coder30b\|q36_35b`); writes `evidence/<ts>/deep/<engine>/<model>/metrics.jsonl` |
| `deep_probe.py warm\|quality` | Warm-prefix TTFT and tool-call contract probes (complements `engine_sweep_client.py`) |
| `scorecard.py <evidence/<ts>/deep>` | Weighted scores -> `scorecard.md` (SGLang has no deep runs: UNAVAILABLE in smoke) |
| `download_probe_models.sh q36_35b` | Pinned Qwen3.6-35B-A3B GGUF + FP8 downloads |

Run notes and caveats: `evidence/<ts>/deep/NOTES.md`; request shapes: `prompts/deep_batch_note.md`.
