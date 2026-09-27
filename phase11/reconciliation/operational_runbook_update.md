# Phase 11 Operational Runbook Update: Hardware Sizing and Live Inference Qualification

## 1. Scope & Objective

This runbook update establishes operational standards, hardware sizing boundaries, and qualification procedures for the Autonomous Engineering System's Evidence-Driven Model and Agent Optimization framework on the Dell Precision T5820 platform.

It supersedes all prior guidance that assumed a 16.0 GB per-GPU limit and codifies Level D real-inference qualification requirements.

---

## 2. Authoritative Hardware Profiles

### 2.1 Dell Precision T5820 Accelerator Profile
- **Physical Accelerators**: 2x Intel Arc Pro B65 GPUs
- **PCI Identifiers**: `0000:51:00.0` (GPU 0), `0000:93:00.0` (GPU 1)
- **Physical VRAM Capacity**: **32,656.00 MiB (31.8906 GiB / 34.24 GB decimal)** per card.
- **Maximum Allocatable Size per Process**: **31,023.20 MiB (30.296 GiB)**.
- **Aggregate Physical VRAM**: **65,312.00 MiB (63.78 GiB)**.
- **Default Runtime System Reservation**: **1,024.00 MiB** per card.
- **Usable Single-Card Envelope**: **31,632.00 MiB** (30.89 GiB).

### 2.2 Resident Serving Configuration
- **Model**: `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`
- **Context Length (`max-model-len`)**: 65,536 tokens
- **Serving Architecture**: Independent Tensor-Parallelism 1 ($TP=1$) workers pinned per GPU:
  - GPU 0: `vllm-xpu-tp1-worker1` on port `8010` (forwarded to local `127.0.0.1:18010`)
  - GPU 1: `vllm-xpu-tp1-worker2` on port `8011` (forwarded to local `127.0.0.1:18011`)
- **Memory Footprint**: ~27,865 MiB allocated per card (85% utilization), leaving ~3,158 MiB dynamic headroom for activation memory and burst requests.

---

## 3. Model Sizing and Memory Admission Gates

Before attempting to deploy or swap any candidate model configuration, the optimizer or operator MUST verify memory admission against the following deterministic rules:

### Rule 1: Single-Card Admission ($TP=1$)
A candidate model is admissible on a single GPU if and only if:
$$\text{Memory}_{\text{model}} + \text{Memory}_{\text{KV}}(C) + \text{Memory}_{\text{overhead}} \le 31,023\text{ MiB}$$
Where:
- $\text{Memory}_{\text{overhead}} = 1,024\text{ MiB}$
- $\text{Memory}_{\text{KV}}(C) = \frac{4 \times L \times D \times C}{1024^2}\text{ MiB}$ ($L$ = layers, $D$ = hidden dimension, $C$ = context length).

### Rule 2: Multi-Card Partitioned Admission ($TP=2$)
If single-card admission fails, the model may be admitted if:
$$\frac{\text{Memory}_{\text{model}}}{2} + \text{Memory}_{\text{KV\_per\_card}}(C) + \text{Memory}_{\text{overhead}} \le 31,023\text{ MiB}$$
And total aggregate memory does not exceed 62,000 MiB.

### Rule 3: Fail-Closed Rejection
Any candidate model with estimated footprint exceeding 62,000 MiB (such as dense 70B FP16 models at ~140,000 MiB) MUST be rejected fail-closed during preflight without contacting the runtime daemon or issuing container commands.

---

## 4. Context Optimization Strategy (Targeted Symbol Context)

When constructing context prompts for code maintenance, defect repair, or refactoring:
1. **Never dump uncurated multi-file source directories** into the prompt context when AST slicing is available.
2. **Apply Targeted Symbol Distillation**:
   - Extract only the direct callers, callees, type definitions, and enclosing class/function signatures relevant to the task objective.
   - Maintain docstring and parameter annotations while omitting unrelated helper definitions.
3. **Target Efficiency Gains**:
   - Typical prompt token reduction: **40.0% – 65.0%**.
   - Preserves 100% acceptance rate on unit and functional regression suites.

---

## 5. Live Level D Real-Inference Qualification Procedure

To qualify model and agent candidates against live serving endpoints:

### Step 1: Endpoint & Tunnel Preflight Check
Verify that the forwarding tunnel and endpoint are responsive:
```bash
curl -s http://127.0.0.1:18010/v1/models -H "Authorization: Bearer hermes-agent-local-auth-token-20260925-b65"
```
Expect HTTP 200 with the active model ID.

### Step 2: Strict Operational Boundaries
- **Concurrency**: Set max concurrent workers to 1 ($N=1$). Do not parallelize evaluations against the live worker.
- **Token Limits**: Set `max_tokens` between 512 and 1024 tokens.
- **Temperature**: Set to 0.0 or 0.1 for deterministic, reproducible code generation.

### Step 3: Execution and Paired Trace Archival
Run the paired comparative campaign:
```bash
python3 phase11/reconciliation/run_real_comparative_campaign.py
```
Verify:
1. Prompt and completion token counts recorded for both control and candidate.
2. Complete raw JSON responses archived in `phase11/reconciliation/traces/`.
3. Generated code extracted to test files and verified by automated test runners.
4. Independent validator acceptance rate $\ge 100\%$.

---

## 6. Incident Response & Rollback Procedures

### Scenario A: Incorrect VRAM Parameters in Configuration
If an operator or pipeline accidentally deploys configurations with inaccurate VRAM ceilings (e.g. 16 GB):
1. Stop running optimization tasks.
2. Re-verify host capacity: `ssh mike@10.0.8.5 "/usr/bin/xpu-smi discovery -d 0,1"`
3. Reset configuration to use default `PHYSICAL_B65_VRAM_MIB` (32,656 MiB).
4. Run regression suite: `pytest phase11/tests/test_hardware_eval.py`.

### Scenario B: Inference Endpoint Unresponsive
If queries to `127.0.0.1:18010` timeout or return connection refused:
1. DO NOT restart the remote podman containers blindly.
2. Check the local SSH forwarding tunnel: `ps aux | grep "ssh -N -T.*18010"`.
3. If the tunnel died, restart only the SSH tunnel with the identical flag set.
4. Verify endpoint health: `curl -s http://127.0.0.1:18010/v1/models`.
