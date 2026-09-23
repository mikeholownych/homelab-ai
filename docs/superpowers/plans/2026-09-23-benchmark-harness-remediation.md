# Benchmark Harness Remediation (B0 / BH1–BH20)

- Date: 2026-09-23
- Status: implemented (design record + audit preservation)
- Baseline: B0 (see `benchmark/b0-matrix`) — frozen vLLM runtime identity
- Disposition: BENCHMARK_HARNESS_REMEDIATION_REQUIRED (audit) -> remediated (see Final Report)

## 1. Purpose

The pre-existing `roles/benchmarking/files/run_benchmark.py` harness produced
evidence that could not be defended: real-mode PASS documents were schema-INVALID,
real mode could not be driven from the playbook (`--model` was never passed), and a
server error discarded every collected observation (`NOT_RUN`). This plan records
the audit findings and the targeted remediation so every future physical benchmark
is attributable, immutable, schema-valid, and honest about what could not be measured.

## 2. Audit findings preserved (full report: audit was reviewed against a live
   dual-xe B0 host on 2026-09-23)

Critical blockers

- **A. Real-mode PASS is schema-INVALID.** The harness hard-coded
  `vram_gib_per_gpu` and `system_ram_gib` to `None` while `benchmark.schema.json`
  required a measured `value`+`unit` for every metric in a PASS branch. Executing the
  schema on a genuine measured PASS emits:
  `Additional properties are not allowed ('reason','status') at ['telemetry','vram_gib_per_gpu','observed']`
  so a truthful physical PASS can never validate.
- **B. Real mode broken via playbook.** `playbooks/benchmark.yml` / role never pass
  `--model` (nor revision/artifact/quantization/guardrail/identity args); the CLI
  `parser.error`es without `--model`, so real mode cannot be invoked by Ansible at all.
- **C. Telemetry fail-open.** A run can PASS with `telemetry_source: unavailable`;
  GPU power/temp are optional; nothing invalidates a run that loses telemetry.

Gaps

- D. No inter-token latency, no p95/p99, raw TTFTs discarded.
- E. Prefill rate computed as `prompt_tokens / generation_seconds` (wrong object);
  only a single ~10-token prompt was used; concurrency=1.
- F. No boot_id / systemd InvocationID / container-ID / image digest / harness
  hash / workload hash binding.
- G. `correctness.observed.summary: "Output verified"` was fabricated without any
  check.
- H. Every request iterated serially; the first client error turned the whole run
  into `NOT_RUN` and deleted records.
- I. No warmup; the first request counted in metrics.
- J. PSU guardrail math is correct (`2*200+250=650 <= 950*0.8=760`), but only runs
  when the correct host vars are supplied; there is no fail-closed thermal path.
- K. `site.yml` includes the `benchmarking` role with `mode: simulated` on every
  convergence, overwriting `benchmark.json` each time.
- L. Evidence is a single overwritten file; no run id; nothing consumes it
  (`aggregate_validation.py` never reads benchmark evidence).
- M. Simulated and physical evidence share one path namespace; neither is deleted,
  but they cannot be told apart authoritatively.

Host science observed (constrained platform):

- Two Intel Battlemage xe GPUs: card1 `0000:51:00.0`, card2 `0000:93:00.0`
  (`8086:e222`), each with its own xe hwmon (hwmon4, hwmon5).
- GPU temperature: MEASURED (multiple `temp*_input`, ~21-31 C idle).
- GPU power draw: UNSUPPORTED — xe hwmon exposes `power1_cap`/`power1_crit` labels
  but **no `power1_input`**; there is no usable power measurement on this platform.
- GPU utilization / memory: UNSUPPORTED — no `gpu_busy_percent`, no
  `mem_busy_percent`, no gt/freq sysfs on this xe stack.
- Host CPU/RAM: MEASURED via `/proc/stat`, `/proc/meminfo`.
- `/tokenize` endpoint available (200); `/v1/tokenize` 404 — vLLM exposes tokenize
  at `/tokenize`. `/v1/models` returns the served model id.

## 3. Evidence layout (immutable, run-addressed)

Root: `benchmarking_evidence_dir` (default `/var/lib/aihost/evidence`).

```
<evidence_dir>/
  benchmarks/
    <benchmark_run_id>/            # run-addressed, created O_EXCL, never overwritten
      manifest.json                # full run card (validates vs benchmark.schema.json)
      environment.json             # live identity bindings (boot/InvocationID/container/image/GPU/versions)
      workload.json                # prompt/output classes, targets vs observed tokens
      raw/
        requests.jsonl             # every raw request observation incl. warmup
        telemetry.jsonl            # timestamped telemetry samples
      metrics.json                 # percentiles + derived rates
      validity.json                # VALID/INVALID/INCOMPLETE + machine reasons
      summary.json                 # human summary
      SHA256SUMS
    simulated/                     # mutable simulated projection ONLY
      benchmark.json               # simulated:true, authoritative:false
      simulated-index.json
```

Physical evidence is only ever written through `mkdir(exist_ok=False)`: a repeated
run id fails instead of clobbering. `site.yml` (simulated) writes only under
`benchmarks/simulated/`. `validity.json` + `raw/*` are preserved for INVALID and
INCOMPLETE runs — failed runs are evidence, never silently deleted.

## 4. Identity binding (fail-closed)

A physical run records: `benchmark_run_id`, `baseline_id`, `config_id`, git SHA +
dirty state, `boot_id`, systemd `InvocationID` + `NRestarts`, container ID + image
digest (podman), served model id (`/v1/models` vs configured), vLLM/Podman/kernel/
Level Zero versions, per-GPU identity (card, PCI BDF, hwmon), TP size, gpu mem
util, max_model_len, enforce_eager, tool_call_parser, and harness
version/`__source_hash__`. If required identity cannot be established the run is
recorded INVALID (never PASS).

## 5. Workload (deterministic, reproducible)

Prompt classes: `short` 1K, `medium` 4K, `large` 16K, `very_large` 32K,
`max_near_window` ~64K (skipped unless enabled). Output classes: 128/512/2048.
Concurrencies: 1/2/4/8. Deterministic synthetic content; server-side `/tokenize`
gives authoritative token counts (fallback to estimated counts is recorded as
`estimated`, never silently asserted). Target vs observed tokens + deviation %
recorded. First `warmup_requests` samples are recorded but excluded from metrics.

## 6. Metrics definitions

- TTFT(ms) = request start -> first token chunk arrival (streaming).
- ITL(ms) = inter-token latency from per-chunk arrival times (per-chunk token counts).
- e2e(latency ms) = request start -> [DONE]/finish.
- decode throughput (tok/s) per request = completion_tokens / decode_interval
  (decode_interval = e2e - ttft), aggregated as total_tokens/total_decode_interval.
- req/s = measured requests / group wall time.
- prompt tokens/s is **not** `prompt_tokens / generation_seconds`; true prefill
  duration is not retrievable from the streaming API, so it is recorded
  unavailable/unsupported with a machine reason (never invented).
- Percentiles p50/p95/p99 + min/max/mean/count for every distribution.
- Metrics for warmup samples are excluded; per-request failures are preserved in
  raw and surfaced in `validity.json` and `metrics.json` request counts.

## 7. Failure taxonomy (monotonic codes, preserved as evidence)

`CLIENT_ERROR`, `HTTP_ERROR`, `TIMEOUT`, `INVALID_RESPONSE`, `OOM`,
`DEVICE_LOST`, `SERVICE_RESTART`, `SERVICE_INVOCATION_CHANGED`,
`MODEL_IDENTITY_CHANGED`, `TP_TOPOLOGY_CHANGED`, `TELEMETRY_LOST`,
`SAFETY_ABORT`, `HARNESS_ERROR`, `WORKLOAD_TOKEN_DEVIATION`,
`CORRECTNESS_FAILURE`, `SERVICE_UNREACHABLE`, `REQUEST_CONNECTION_FAILED`.

## 8. Validity model

`validity.state` in `{VALID, INVALID, INCOMPLETE}` surfaced in `validity.json`
and mirrored in the manifest. INVALID causes: safety abort, telemetry loss while
requiring fail-closed sensors, invocation/restart change mid-run, model identity
mismatch, TP topology change, workload token deviation beyond threshold, material
correctness failure. INCOMPLETE: interrupted before completion. Every reason is
machine-readable `{code, detail}`. A SAFETY_ABORTed or INVALID run still writes
its raw observations + validity file — `NOT_RUN` is reserved for pre-run refusal.

## 9. Safety

PSU budget: estimated = `gpu_count*tp_dp_w + base`; limit = `psu * (1-headroom)`.
B0: `2*200 + 250 = 650 <= 950*0.8 = 760` -> permitted. Refusal -> INVALID
`POWER_BUDGET_EXCEEDED` with the math recorded. Thermal: per-GPU peak temp; if the
required fail-closed sensor set is missing at start or is lost mid-run ->
INVALID/TELEMETRY_LOST; exceeding abort temperature -> INVALID/SAFETY_ABORT with
observations preserved. No telemetry loss is classified as a passing run.

## 10. B0 matrix

Encoded in `roles/benchmarking/files/b0-matrix.json` (data only, consciously NOT
executed by this remediation). Sequential stop/elimination conditions and the 11
load points (W01-W11) are described there; matrix runs are a separate authorized
campaign.

## 11. Schema / compatibility strategy

- `schemas/benchmark.schema.json` v2.0.0 keeps the legacy top-level run-card
  shape (system/model/execution/duration/telemetry/correctness/failure_criteria/
  os_tuning/safety) and adds `benchmark_run_id`, `baseline_id`, `config_id`,
  `started_at`, `completed_at`, `validity`, and optional `identity`/`workload`.
- PASS no longer demands a measured value for telemetry that is genuinely
  UNSUPPORTED on the platform (vram, system RAM, GPU power); it still requires
  measured generation throughput, TTFT, and GPU temperature. Nothing weakens the
  requirement that measured-capable metrics be real.
- Separate schemas for `environment`, `workload`, `metrics`, `validity`
  components, registered in `scripts/validate_contract.py`.
- Simulated fixtures updated consciously to v2; existing contract tests continue
  to assert that simulated output stays schema-valid and non-physical.

## 12. Concurrency / streaming

`ThreadPoolExecutor(max_workers=concurrency)`; one task per request records raw
per-chunk event timing; TTFT/ITL/e2e derived from the same timestamps; group wall
time = start of first task -> end of last completion. `raw/requests.jsonl` holds
the complete per-request record including warmup and failures.
## 13. BH19 live HARNESS_VALIDATION results (2026-09-23)

Ran the remediated harness in real mode against the live vllm.service on
ai-5820-01 (systemd runner, not podman). Evidence bundles written under
`/var/lib/local-ai/evidence/benchmarks/<run_id>/`, run cards mirrored to
`benchmark-hv*.json`.

- hv01 (c1, floor 30, pre-fix): FAIL/INVALID `WORKLOAD_TOKEN_DEVIATION`
  (observed 963 vs declared 1024, 5.96% > 5%). Proved the fail-closed workload
  guard works — and that `_deterministic_filler` under-filled short budgets by
  whole-chunk repeat arithmetic.
- hv02 (c8, floor 1): PASS/VALID, 6 measured, 0 failed, sentinel PASS, decode
  ~7.17 tok/s mean per request.
- hv03 (c1, floor 5.0 + frozen artifact sha): PASS/VALID, 2 measured, 0 failed,
  sentinel PASS, decode 8.07 tok/s mean, TTFT ~250 ms, ITL p50 ~120 ms, prompt
  deviation 0.29%.

Live calibration of every prompt class against the served tokenizer:
short/medium/large/very_large/max_near_window all converge to <=0.3% within 3-6
iterations (convergent filler + exact-remainder padding).

Live-platform findings folded into this remediation:
- The original throughput finding is preserved: 30 tok/s was unachievable
  per-request on this hardware (~7-8 tok/s mean observed). The earlier 5.0
  tok/s floor was itself a semantic defect because it made performance an
  invalidity gate. The floor and its role/CLI wiring were removed; throughput
  remains measured in the distributions and B0 uses
  `performance_assessment: NOT_EVALUATED` while establishing reference data.
- image_digest/image_ref are null at runtime because the deploy is a systemd
  runner (no podman container); B0 frozen image digest is carried as declared
  attribution on run cards via `--artifact-sha256`/`benchmarking_model_artifact_sha256`.
- `discover_gpu_topology()` enumerates DRM connector nodes (card*-DP-*, card*-HDMI-*)
  alongside the two physical cards; env schema accepts nullable connector rows and
  physical cards (card1 0000:51:00.0/hwmon4, card2 0000:93:00.0/hwmon5) are both
  captured. Connector rows are noise; acceptable in evidence, noted for future
  tightening of the detector.

All bundles from these runs validate against the five benchmark contracts via
`scripts/validate_contract.py`.

## 14. BF throughput-validity remediation (2026-09-23)

The pre-B0 gate detected the floor defect before W01, so no B0 workload was
executed. The matrix elimination rule now covers only the device-error budget;
thermal, power, telemetry, identity, service, and correctness invalidation
remain fail-closed. The blocked B0 campaign records and the original finding
are preserved as immutable evidence. B0 will establish performance
distributions first and bind a new matrix hash after this remediation.

- Previous matrix SHA-256: `b7fed49879bae6611ac780cba07bade04e0fc1bc9b99d3760294dfff6b8959db`
- Remediated matrix SHA-256: `09a631eb7f11b6842c19ff324a994f2f8484de13a5ec03740603014084c1107b`
