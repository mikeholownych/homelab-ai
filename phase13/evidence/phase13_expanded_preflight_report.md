# Phase 13 Expanded Preflight Verification Report

**Document Identifier**: `phase13_expanded_preflight_report.md`  
**Proposal Reference**: `MAINT-PROP-EXPANDED-HETERO-GPU1`  
**Host Target**: Dell Precision T5820 (`10.0.8.5`)  
**Audit Timestamp**: Sun 2026-09-27 23:06:10 UTC  
**Preflight Result**: `ALL_GATES_PASSED_READY_FOR_CAMPAIGN`

---

## 1. Preflight Verification Checklist

| Gate ID | Verification Item | Target Invariant | Measured Value / State | Result |
|---|---|---|---|---|
| **PRE-01** | Worker 1 Independent Serving | Route `engineering/b0` served independently via port 8000 | Returns HTTP 200 with `engineering/b0` | **PASS** |
| **PRE-02** | Workload Drain (Worker 2) | In-flight requests on Worker 2 must be exactly 0.0 | `num_requests_running=0.0`, `num_waiting=0.0` | **PASS** |
| **PRE-03** | Active Task Check | Zero child sandboxes under OpenCode runner PID 3130937 | `pgrep -P 3130937` -> 0 children | **PASS** |
| **PRE-04** | Candidate Snapshot on Disk | Pinned revision `b25037543e9394b818fdfca67ab2a00ecc7dd641` | All 9 model and tokenizer blobs present | **PASS** |
| **PRE-05** | Baseline Config Backup | Worker 2 `vllm-config.yaml` digest matches baseline | `641c9402ebbc56f5d599512894f72a02304fd6615edbb7a2875ab48f93f4e08b` | **PASS** |
| **PRE-06** | Gateway Config Backup | Gateway environment digest matches baseline | `16b7be5bbe4a189dc8730ae2726530820d78e7b13564631a693d332b454c0970` | **PASS** |
| **PRE-07** | Protected Process Continuity | PIDs 986, 2093382, 3130937 running uninterrupted | 100% continuous uptime; 0 signal restarts | **PASS** |
| **PRE-08** | GPU Health & Memory Headroom | GPU 0 & GPU 1 operational; memory idling at baseline | GPU 0: 27,869 MiB (85%), GPU 1: 27,853 MiB (85%) | **PASS** |
| **PRE-09** | Forwarding Tunnel Health | Experimental port 18000 forwards cleanly to Worker 1 | HTTP 200 completion probe verified | **PASS** |

---

## 2. Preflight Disposition

All 9 mandatory preflight gates have passed. The system is certified ready to execute the authorized expanded physical campaign.
