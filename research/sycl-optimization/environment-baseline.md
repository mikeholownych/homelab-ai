# Environment baseline (ai-5820-01) — captured 2026-11-14

Status: Phase 0 in progress. Everything below was observed on the live host (read-only), not taken from prior documents.

## Deviations from the task brief's "historical context"

| Brief said | Observed |
|---|---|
| Worker 1: Qwen3-Coder-30B-A3B Q4_K_M | **Qwen3.6-35B-A3B-UD-Q4_K_M.gguf** (22.1 GB), GPU 0, :8000, `--reasoning-budget 8192` |
| Worker 2: Qwen3.5-27B Q4_K_M | **Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M** (2 shards), GPU 1, :8001, `--reasoning-budget 4096` |
| Rootless Podman containers | systemd units (`aihost-llama-worker{1,2}.service`) running `podman run` as user `aihost-runtime` |
| llama.cpp SYCL | stock upstream `ghcr.io/ggml-org/llama.cpp` image, no local patches |

Workstream A's "primary target" model (Qwen3-Coder-30B-A3B) is not deployed; the nearest deployed MoE is Qwen3.6-35B-A3B. A Qwen3-Coder GGUF is not on the host (to be confirmed).

## Runtime identity

| Item | Value |
|---|---|
| Image | `ghcr.io/ggml-org/llama.cpp@sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451` (image id c287635a3cc7) |
| llama.cpp | version 0.5.0-dev, **build 11347**, commit `5fc4f3c8c7103ffd0b7ff5ee4855bcc78a3ed5cd`, image created 2026-10-02 |
| Compiler / oneAPI | IntelLLVM / DPC++ 2026.1.1 (2026.1.1.20260724), oneAPI 2026.1 in image |
| Included tools | llama-server, llama-bench, llama-perplexity, llama-batched-bench, llama-fit-params, libggml-sycl.so |
| Host kernel | 7.0.0-42-generic, `xe` driver |
| Host compute runtime | libze-intel-gpu1 26.22.38646.7, libze1 1.28.6, libigc2 2.36.5, intel-opencl-icd 26.22.38646.7 |
| GPU firmware | GuC 70.58.0 (xe/bmg_guc_70.bin), HuC 8.2.10, DMC 2.6 |
| GPUs | 2x Battlemage G31 [8086:e222] at PCI 51:00.0 and 93:00.0 (renderD128/renderD129) |
| Host | Xeon W-2123, 61 GiB RAM, uptime 5d at capture, Ubuntu (26.04 package suffixes) |
| Other images present | `localhost/aihost/llama-sycl-qualification` (sha256:1bd92baa…), `vllm/vllm-openai-xpu`, alpine, hello-world |

## Worker launch arguments (production, verbatim from unit files)

Both workers: `podman run --rm --network host --ipc host --security-opt no-new-privileges --device local-ai.intel/gpu=all`,
`ONEAPI_DEVICE_SELECTOR=level_zero:0,1`, `ZE_AFFINITY_MASK={0|1}`, `SYCL_PI_LEVEL_ZERO_USE_IMMEDIATE_COMMANDLISTS=1`,
models mounted read-only at `/models`; server args
`-c 65536 --host 127.0.0.1 --jinja -np 1 -fa on -b 4096 -ub 2048 --metrics --lazy-mode on -ngl 99` plus reasoning budgets.
CPUAffinity: worker1 `0 1 4 5`, worker2 `2 3 6 7`. Unit files: `/etc/systemd/system/aihost-llama-worker{1,2}.service`
(managed by Ansible; research must never edit them — experiments use separate units/containers).

## Gateway

`aihost-orchestrator-gateway.service`, release `t5820-gateway-4d8ab8b80ef3334c0d8519397220a4b238c60d57` (newest dir under
`/var/lib/aihost/releases`), port 8010. `aihost-inference-policy.service` enforces the gateway-only network policy.

## Observed production steady state (from worker1 log, not a benchmark)

Decode about 59.5 t/s on a 181-token generation (slot print_timing, task 1496662). Used only as a sanity anchor.

## Model identity

SHA-256 computation running in the background on the host
(`~/sycl-research/evidence/model-sha256.txt` on ai-5820-01); will be copied into `evidence/` when complete.

## Research-window policy

Operator suspended the gateway-only and no-local-origin rules for this bounded research window (2026-11-14). At the end the
experimental servers are torn down and the gateway-only end-state re-verified. Production unit files are not modified.

## Recovery (baseline restoration)

Production units are untouched; stopping them is the only disruptive action. Restoration is:
`sudo systemctl start aihost-llama-worker1.service aihost-llama-worker2.service` followed by health checks through the gateway.
Scripted version: `harness/restore_baseline.sh` (to be written and tested before the first stop).
