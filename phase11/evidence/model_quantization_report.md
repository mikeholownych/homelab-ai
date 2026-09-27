# Phase 11 Model Quantization Report: Hardware Memory Budgets and Intel Arc Pro B65 Compatibility

## Executive Summary

Phase 11 Workstream E evaluated model quantization formats and hardware constraints against the two physical Intel Arc Pro B65 GPUs (16.0 GB VRAM per device). The evaluation established memory feasibility boundaries, KV cache footprint modeling, and explicit maintenance proposal generation for candidate models requiring resident weight swaps.

---

## 1. Intel Arc Pro B65 Hardware Parameters

- **Node**: `10.0.8.5` (Dell Precision T5820)
- **Accelerators**: 2x Intel Arc Pro B65 GPUs
- **Memory Capacity**: 16,384 MB (16.0 GB) per GPU
- **Target Utilization Cap**: 90% (14.4 GB maximum allocatable memory)
- **Protected Control**: `Qwen/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (TP=1 on port 18010)

---

## 2. Memory Footprint Modeling

The memory footprint $M_{\text{total}}$ is evaluated according to:
$$M_{\text{total}} = M_{\text{weights}} + M_{\text{kv\_cache}} + M_{\text{activation}}$$

Where:
- $M_{\text{weights}} = \text{Parameters} \times \text{Bytes\_per\_Weight}$
- $M_{\text{kv\_cache}} = 2 \times N_{\text{layers}} \times D_{\text{hidden}} \times L_{\text{context}} \times B \times \text{Bytes\_per\_KV}$

### Evaluated Model Configurations:

| Model Identity | Format | Params | Context | Weights GB | KV Cache GB | Total VRAM | Compatibility Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `Qwen/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` | `awq-4bit` | 30.5B | 32,768 | 8.5 GB | 3.5 GB | 12.0 GB | `COMPATIBLE_RESIDENT` |
| `microsoft/phi-4-mini-instruct` | `fp8` | 3.8B | 16,384 | 4.2 GB | 2.0 GB | 6.2 GB | `REQUIRES_MAINTENANCE_SWAP` |
| `deepseek-ai/DeepSeek-Coder-V2-Lite-Instruct` | `awq-4bit` | 16.0B | 32,768 | 9.0 GB | 3.0 GB | 12.0 GB | `REQUIRES_MAINTENANCE_SWAP` |
| `meta-llama/Llama-3-70B-Instruct` | `fp16` | 70.0B | 8,192 | 140.0 GB | 8.0 GB | 148.0 GB | `INCOMPATIBLE_VRAM_EXCEEDED` |

---

## 3. Maintenance Proposal Workflow for Physical Swaps

Physical resident swaps on node `10.0.8.5` are strictly prohibited without an approved maintenance proposal:
1. When a non-resident candidate is proposed, `ModelHardwareCompatibilityEvaluator` creates a `MaintenanceProposal` specifying:
   - Proposal ID and timestamp.
   - Target model and revision.
   - Eviction impact and memory budget delta.
   - Fallback/recovery plan.
2. The proposal is registered in `PENDING_APPROVAL` status.
3. Autonomous execution is paused and gated.
4. Activation requires explicit cryptographic approval from an authorized human operator.
