# Phase 7 Qualification Report: Resource & Dependency Containment (Workstream E)

## 1. Executive Summary

Workstream E evaluates hardware resource containment, VRAM utilization envelopes, and scratch workspace hygiene across sustained operations on the Dell Precision 5820 Tower.

Key Outcomes:
1. **GPU VRAM Envelope Containment**: Dual TP=1 topology strictly confines Qwen3-Coder 30B AWQ to the physical 31.89 GiB VRAM capacity across the two Intel Arc Pro B65 GPUs.
2. **Ephemeral Workspace Hygiene**: Ephemeral directories created by `ConcurrencyManager` and `IndependentValidator` are deterministically deleted upon task conclusion, preventing disk exhaustion.
3. **Process Leak Prevention**: Worker executions operate in controlled sub-processes or isolated containers with no orphan processes left running.

---

## 2. Hardware Resource Envelope (T5820 Host)

### Physical Specifications:
- **Host**: Dell Precision 5820 Tower (`10.0.8.5`)
- **GPUs**: 2x Intel Arc Pro B65 (16 GiB VRAM per card, 32 GiB total physical; 31.89 GiB addressable)
- **PCIe Topology**: Dual discrete PCIe Gen4 slots
- **Model Topology**: Dual TP=1 vLLM instances behind `orchestrator_gateway` (PID 742882 on port 8010)

### VRAM Feasibility Analysis:
| Configuration | Model(s) | Required VRAM | Available VRAM | Feasibility |
|---|---|---|---|---|
| Historical Colloquial "TP=2" | Qwen3-Coder 30B AWQ | ~18.5 GiB (split 2x 9.25 GiB) | 31.89 GiB | Feasible |
| Attempted Simultaneous Heterogeneous | Qwen3 30B (18.5G) + Phi-4 FP8 (16.2G) + K-V cache | ~39.7 GiB | 31.89 GiB | **Mathematically Infeasible** (OOM) |
| **Actual Dual TP=1 Production Topology** | Qwen3-Coder 30B AWQ (Worker 1 on GPU 0, Worker 2 on GPU 1) | 14.8 GiB per GPU | 15.94 GiB per GPU | **Feasible & Stable** |

---

## 3. Ephemeral Workspace Lifecycle & Leak Auditing

### 3.1 Concurrency Workspaces
- Workspaces are provisioned at `/tmp/ws_{work_order_id}_{rand}/`.
- Protected from copying `.git` or caching artifacts (`__pycache__`).
- Upon task completion, `ConcurrencyManager.release_workspace()` executes `shutil.rmtree(..., ignore_errors=True)`.
- Verified in `test_concurrent_execution.py`: Zero leftover directories observed in `/tmp/ws_*` after release.

### 3.2 Independent Validation Sandboxes
- Created per validation execution at `/tmp/val_sandbox_{rand}/`.
- Cleaned up via `try ... finally` context managers in `IndependentValidator`.
- Audit verified that sandbox directories do not accumulate during sustained cohort runs.

### 3.3 Disk Footprint Bounds
- The SQLite WAL file maintains a bounded size (`PRAGMA wal_autocheckpoint=1000`).
- Content-addressed artifact store (`ArtifactStore`) writes immutable, deduplicated payload blobs with SHA-256 keys, preventing uncontrolled data bloat.
