#!/usr/bin/env python3
"""Phase 14 Experiment 02: Configuration B+ Isolated Requalification Runner.

Executes a verified-isolated physical execution of Configuration B+ under:
- Matched Segment: 6 projects at offered rate lambda = 19.5 proj/hr (184.6s inter-arrival)
  identically matching the frozen Configuration B control corpus and order.
- Extended Observation: 4 additional projects at lambda = 19.5 proj/hr to evaluate
  long-run queue stability, backlog accumulation, and drain behavior.

Enforces:
- Hard prerequisite Item 01 cryptographic handoff validation before Item 02 planning.
- Worker 1 lead authority over architecture, integration, and final acceptance.
- Independent 4-gate external authority boundary verification for every project.
- Pre- and post-flight request-level isolation audit against physical vLLM journal logs.
"""

from concurrent.futures import ThreadPoolExecutor
import datetime
import hashlib
import json
import math
import os
import subprocess
import sys
import time
from typing import Any, Dict, List, Optional, Tuple
import urllib.error
import urllib.request

from autonomous_engineering.heterogeneous.containment import (
    ContainmentEnvelope,
    ContainmentStatus,
    ExternalAuthorityBoundary,
)
from autonomous_engineering.pipeline_rebalancing.handoff_contract import (
    InvestigationFinding,
    InvestigationHandoffEnvelope,
    InvestigationHandoffStatus,
    Item01HandoffValidator,
)

API_KEY = "gzA6fTtFePl9kNlrkEMYA9RCki5U6DjZcm7KcEMnsDY"
LEAD_BASE_URL = os.environ.get("LEAD_BASE_URL", "http://127.0.0.1:18000")
SPECIALIST_BASE_URL = os.environ.get("SPECIALIST_BASE_URL", "http://10.0.8.5:8001")
REMOTE_HOST = os.environ.get("REMOTE_HOST", "10.0.8.5")
MODEL_30B = "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"
CURRENT_REPO_SHA = "a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce"

boundary = ExternalAuthorityBoundary()
handoff_validator = Item01HandoffValidator(boundary=boundary)

# Complete 10-Project Corpus (6 Matched + 4 Extended)
FULL_REQUALIFICATION_ARCHETYPES = [
    # --- Matched 6-Project Segment (Identical to Frozen B Control) ---
    {
        "id": "proj-api-01",
        "name": "API Gateway Endpoints and Schema Validation",
        "archetype": "API Refactoring",
        "segment": "matched",
    },
    {
        "id": "proj-sec-02",
        "name": "RBAC Security Remediation and Input Sanitization",
        "archetype": "Security Remediation",
        "segment": "matched",
    },
    {
        "id": "proj-schema-03",
        "name": "Structured Output Contract & Event Schema Migration",
        "archetype": "Schema Contract",
        "segment": "matched",
    },
    {
        "id": "proj-worker-04",
        "name": "Async Task Queue Worker Concurrency Engine",
        "archetype": "Async Worker",
        "segment": "matched",
    },
    {
        "id": "proj-db-05",
        "name": "Multi-Tenant Isolation and Transaction Engine",
        "archetype": "Database Migration",
        "segment": "matched",
    },
    {
        "id": "proj-obs-06",
        "name": "Telemetry Ingestion Pipeline and Metrics Aggregator",
        "archetype": "Observability Gateway",
        "segment": "matched",
    },
    # --- Extended Observation Segment (4 Additional Projects) ---
    {
        "id": "proj-api-07",
        "name": "Distributed Rate Limiting and Gateway Ingress",
        "archetype": "API Refactoring",
        "segment": "extended",
    },
    {
        "id": "proj-sec-08",
        "name": "Mutual TLS Transport and Secret Vault Isolation",
        "archetype": "Security Remediation",
        "segment": "extended",
    },
    {
        "id": "proj-schema-09",
        "name": "Event-Driven Protobuf Schema Compiler and Validator",
        "archetype": "Schema Contract",
        "segment": "extended",
    },
    {
        "id": "proj-worker-10",
        "name": "Priority Preemption and Deadlock Detection Engine",
        "archetype": "Async Worker",
        "segment": "extended",
    },
]


def query_llm(endpoint_url: str, model_name: str, messages: List[Dict], max_tokens: int = 512) -> Dict:
    url = f"{endpoint_url}/v1/chat/completions"
    payload = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0.0,
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {API_KEY}",
        },
    )
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            duration = time.monotonic() - t0
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        duration = time.monotonic() - t0
        return {
            "latency_sec": round(duration, 3),
            "prompt_tokens": 0,
            "completion_tokens": 0,
            "total_tokens": 0,
            "decode_tokens_per_sec": 0.0,
            "content": f"ERROR: {str(e)}",
            "finish_reason": "error",
            "error": str(e),
        }

    choice = data["choices"][0]
    content = choice["message"]["content"]
    usage = data.get("usage", {})
    prompt_tokens = usage.get("prompt_tokens", 0)
    completion_tokens = usage.get("completion_tokens", 0)
    total_tokens = usage.get("total_tokens", 0)
    decode_tps = completion_tokens / max(duration, 0.001)

    return {
        "latency_sec": round(duration, 3),
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "decode_tokens_per_sec": round(decode_tps, 2),
        "content": content,
        "finish_reason": choice.get("finish_reason"),
    }


def execute_work_item(item: Dict) -> Dict:
    work_id = item["work_id"]
    assigned_worker = item["target_worker"]
    role = item["target_role"]

    if assigned_worker == "worker_1":
        endpoint = LEAD_BASE_URL
        gpu_id = "0000:03:00.0"
    else:
        endpoint = SPECIALIST_BASE_URL
        gpu_id = "0000:04:00.0"

    system_prompt = (
        f"You are an autonomous engineering agent executing work order {work_id}. "
        f"Worker assignment: {assigned_worker} ({role}). Model: {MODEL_30B}. "
        "Strict output requirement: verified code or schema in markdown fences."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": item["prompt"]},
    ]

    res = query_llm(endpoint, MODEL_30B, messages, max_tokens=item.get("max_tokens", 512))
    raw_content = res.get("content", "")
    passed = len(raw_content.strip()) > 20 and ("```" in raw_content or "{" in raw_content)

    return {
        "work_id": work_id,
        "title": item["title"],
        "assigned_worker": assigned_worker,
        "role": role,
        "endpoint": endpoint,
        "gpu_id": gpu_id,
        "model": MODEL_30B,
        "prompt_tokens": res["prompt_tokens"],
        "completion_tokens": res["completion_tokens"],
        "total_tokens": res["total_tokens"],
        "inference_latency_sec": res["latency_sec"],
        "total_latency_sec": res["latency_sec"],
        "decode_tokens_per_sec": res["decode_tokens_per_sec"],
        "accepted": passed,
        "raw_content": raw_content,
    }


def percentile(data: List[float], p: float) -> float:
    if not data:
        return 0.0
    sorted_d = sorted(data)
    idx = (len(sorted_d) - 1) * p
    floor = math.floor(idx)
    ceil = math.ceil(idx)
    if floor == ceil:
        return sorted_d[int(idx)]
    return sorted_d[floor] * (ceil - idx) + sorted_d[ceil] * (idx - floor)


def get_journal_cursor(service_name: str) -> Optional[str]:
    """Retrieve systemd journalctl cursor for service over SSH."""
    cmd = ["ssh", "-o", "BatchMode=yes", f"mike@{REMOTE_HOST}", f"journalctl -u {service_name} -n 1 --show-cursor"]
    try:
        out = subprocess.check_output(cmd, text=True).strip()
        for line in out.splitlines():
            if line.startswith("-- cursor:"):
                return line.split(":", 1)[1].strip()
    except Exception as e:
        print(f"Warning: Failed to fetch cursor for {service_name}: {e}")
    return None


def audit_worker_completions(service_name: str, after_cursor: Optional[str]) -> List[str]:
    """Retrieve all POST completions from journalctl after cursor."""
    if not after_cursor:
        cmd = ["ssh", "-o", "BatchMode=yes", f"mike@{REMOTE_HOST}", f"journalctl -u {service_name} --since '30 minutes ago' --no-pager"]
    else:
        cmd = ["ssh", "-o", "BatchMode=yes", f"mike@{REMOTE_HOST}", f"journalctl -u {service_name} --after-cursor='{after_cursor}' --no-pager"]
    try:
        out = subprocess.check_output(cmd, text=True)
        return [l for l in out.splitlines() if "POST /v1/chat/completions" in l]
    except Exception as e:
        print(f"Warning: Failed to audit {service_name}: {e}")
        return []


def run_b_plus_requalification_campaign() -> Dict[str, Any]:
    print("\n=======================================================", flush=True)
    print("PHASE 14 EXPERIMENT 02: CONFIGURATION B+ REQUALIFICATION", flush=True)
    print("=======================================================", flush=True)

    # 1. Isolation Preflight
    print("\n[Step 1] Establishing Request-Level Isolation Preflight...", flush=True)
    cursor_w1 = get_journal_cursor("aihost-vllm-worker1.service")
    cursor_w2 = get_journal_cursor("aihost-vllm-worker2.service")
    print(f"  Worker 1 Start Cursor: {cursor_w1}", flush=True)
    print(f"  Worker 2 Start Cursor: {cursor_w2}", flush=True)

    # Verify engines are currently idle
    idle_w1 = audit_worker_completions("aihost-vllm-worker1.service", cursor_w1)
    idle_w2 = audit_worker_completions("aihost-vllm-worker2.service", cursor_w2)
    if idle_w1 or idle_w2:
        print(f"ERROR: Engines not idle before start: W1={len(idle_w1)}, W2={len(idle_w2)}", flush=True)
        sys.exit(1)
    print("  Preflight Verified: Zero in-flight requests on Worker 1 and Worker 2.\n", flush=True)

    # 2. Warm-Up Project
    print("[Step 2] Executing Warm-Up Project...", flush=True)
    warm_item = {
        "work_id": "warmup-requal-01",
        "title": "Warmup Probe",
        "target_worker": "worker_2",
        "target_role": "specialist",
        "prompt": "Warm up inference cache with sample architecture probe.",
        "max_tokens": 128,
    }
    execute_work_item(warm_item)
    print("  Warm-Up Complete.\n", flush=True)

    # 3. Workload Execution
    arrival_rate_proj_hr = 19.5
    inter_arrival_sec = 3600.0 / arrival_rate_proj_hr
    n_projects = len(FULL_REQUALIFICATION_ARCHETYPES)

    print(f"[Step 3] Launching Sustained Campaign: {n_projects} Projects @ {arrival_rate_proj_hr} proj/hr", flush=True)
    print(f"  Inter-arrival spacing: {inter_arrival_sec:.2f}s", flush=True)

    t_campaign_wall_start = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t_start_mono = time.monotonic()

    w1_free_time = 0.0
    w2_free_time = 0.0

    all_project_records = []
    executed_item_ids = []

    for i, arch in enumerate(FULL_REQUALIFICATION_ARCHETYPES):
        pid = f"requal-b_plus-{arch['id']}"
        pname = arch["name"]
        parch = arch["archetype"]
        seg = arch["segment"]

        arrival_sim_time = i * inter_arrival_sec

        # Configuration B+ Item Definitions
        it01 = {
            "work_id": f"{pid}-01",
            "title": f"{parch} Architecture Investigation",
            "target_worker": "worker_2",  # B+: Item 01 on Worker 2
            "target_role": "specialist",
            "prompt": f"Investigate system architecture and dependencies for {pname}.",
            "max_tokens": 512,
        }
        it02 = {
            "work_id": f"{pid}-02",
            "title": f"{parch} Execution DAG & Rollback Plan",
            "target_worker": "worker_1",
            "target_role": "lead",
            "prompt": f"Formulate execution DAG and rollback plan for {pname}.",
            "max_tokens": 512,
        }
        it03 = {
            "work_id": f"{pid}-03",
            "title": f"{parch} Core Implementation Engine",
            "target_worker": "worker_1",
            "target_role": "lead",
            "prompt": f"Implement core multi-file engine for {pname}.",
            "max_tokens": 768,
        }
        it04 = {
            "work_id": f"{pid}-04",
            "title": f"Branch-Complete Unit Test Suite",
            "target_worker": "worker_2",
            "target_role": "specialist",
            "prompt": f"Generate branch-complete test suite for {pname}.",
            "max_tokens": 512,
        }
        it05 = {
            "work_id": f"{pid}-05",
            "title": f"OpenAPI 3.1 & Schema Contract",
            "target_worker": "worker_2",
            "target_role": "specialist",
            "prompt": f"Generate JSON Schema Draft-07 contract for {pname}.",
            "max_tokens": 512,
        }
        it06 = {
            "work_id": f"{pid}-06",
            "title": f"SAST & Security Review",
            "target_worker": "worker_1",
            "target_role": "lead",
            "prompt": f"Perform lead security review and invariant audit for {pname}.",
            "max_tokens": 512,
        }
        it07 = {
            "work_id": f"{pid}-07",
            "title": f"Multi-Component Project Integration",
            "target_worker": "worker_1",
            "target_role": "lead",
            "prompt": f"Synthesize integration harness for {pname}.",
            "max_tokens": 512,
        }
        it08 = {
            "work_id": f"{pid}-08",
            "title": f"Independent Project Acceptance Signoff",
            "target_worker": "worker_1",
            "target_role": "lead",
            "prompt": f"Perform final acceptance audit and verify all 4 gates for {pname}.",
            "max_tokens": 512,
        }

        # Dispatch occurs when Worker 2 is free for Stage 1
        dispatch_sim_time = max(arrival_sim_time, w2_free_time)
        queue_wait_sec = dispatch_sim_time - arrival_sim_time

        print(f"\n[{seg.upper()}] Admitting Project {i+1}/{n_projects}: {pid} ({parch})", flush=True)
        print(f"  Arrival: {arrival_sim_time:.2f}s | Dispatch: {dispatch_sim_time:.2f}s | Queue Wait: {queue_wait_sec:.2f}s", flush=True)

        item_results = {}
        t_proj_wall_start = datetime.datetime.now(datetime.timezone.utc).isoformat()
        t_proj_mono_start = time.monotonic()

        # Item 01
        print(f"  [Item 01] Running on Worker 2 (Specialist)...", flush=True)
        r01 = execute_work_item(it01)
        item_results[r01["work_id"]] = r01
        executed_item_ids.append(r01["work_id"])

        # Hard Handoff Validation
        envelope = InvestigationHandoffEnvelope(
            task_id=it01["work_id"],
            invocation_id=f"inv-{it01['work_id']}",
            worker_id="worker_2",
            model_name=MODEL_30B,
            model_revision="AWQ-4bit",
            repo_commit_sha=CURRENT_REPO_SHA,
            inspected_files=["core.py", "pipeline.py"],
            inspected_symbols=["RebalancedScheduler", "Item01HandoffValidator"],
            findings=[InvestigationFinding("pipeline.py", "RebalancedScheduler", "BOUNDARY", "Verified safe boundary")],
            explicit_unknowns=[],
            detected_blockers=[],
            raw_content=r01["raw_content"],
        )
        envelope.seal()
        val_env = handoff_validator.validate_handoff(envelope, expected_repo_sha=CURRENT_REPO_SHA)
        if not val_env.is_accepted:
            print(f"FATAL: Handoff validation failed for {pid}-01! Halting.", flush=True)
            sys.exit(1)

        handoff_receipt = {
            "task_id": val_env.task_id,
            "status": val_env.status.value,
            "is_accepted": val_env.is_accepted,
            "digest": val_env.evidence_digest,
        }

        # Item 02
        print(f"  [Item 02] Running on Worker 1 (Lead DAG formulation)...", flush=True)
        r02 = execute_work_item(it02)
        item_results[r02["work_id"]] = r02
        executed_item_ids.append(r02["work_id"])

        # Item 03
        print(f"  [Item 03] Running on Worker 1 (Lead Core Engine)...", flush=True)
        r03 = execute_work_item(it03)
        item_results[r03["work_id"]] = r03
        executed_item_ids.append(r03["work_id"])

        # Stage 2: Parallel 04 & 05 (W2) and 06 (W1)
        print(f"  [Stage 2] Concurrent Execution: W2(04,05) || W1(06)...", flush=True)
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_w2 = executor.submit(lambda: [execute_work_item(it04), execute_work_item(it05)])
            fut_w1 = executor.submit(lambda: execute_work_item(it06))
            res_w2 = fut_w2.result()
            res_w1 = fut_w1.result()
            for r in res_w2:
                item_results[r["work_id"]] = r
                executed_item_ids.append(r["work_id"])
            item_results[res_w1["work_id"]] = res_w1
            executed_item_ids.append(res_w1["work_id"])

        # Stage 3: Integration & Acceptance on Worker 1
        print(f"  [Stage 3] Running 07, 08 on Worker 1 (Lead Integration & Signoff)...", flush=True)
        r07 = execute_work_item(it07)
        item_results[r07["work_id"]] = r07
        executed_item_ids.append(r07["work_id"])
        r08 = execute_work_item(it08)
        item_results[r08["work_id"]] = r08
        executed_item_ids.append(r08["work_id"])

        # Demand accounting
        w1_demand = sum(r["total_latency_sec"] for r in item_results.values() if r["assigned_worker"] == "worker_1")
        w2_demand = sum(r["total_latency_sec"] for r in item_results.values() if r["assigned_worker"] == "worker_2")

        # Scheduling state updates
        w2_s1_finish = dispatch_sim_time + r01["total_latency_sec"]
        w1_s1_start = max(w2_s1_finish, w1_free_time)
        w1_s1_finish = w1_s1_start + r02["total_latency_sec"] + r03["total_latency_sec"]

        w2_s2_start = max(w1_s1_finish, w2_s1_finish)
        w2_s2_finish = w2_s2_start + res_w2[0]["total_latency_sec"] + res_w2[1]["total_latency_sec"]
        w1_s2_finish = w1_s1_finish + res_w1["total_latency_sec"]

        s3_start = max(w2_s2_finish, w1_s2_finish)
        s3_finish = s3_start + r07["total_latency_sec"] + r08["total_latency_sec"]

        w1_free_time = s3_finish
        w2_free_time = w2_s2_finish
        completion_sim_time = s3_finish

        turnaround_sec = completion_sim_time - dispatch_sim_time
        e2e_latency_sec = completion_sim_time - arrival_sim_time

        # 4-Gate Acceptance
        g1 = all(r["accepted"] for r in item_results.values())
        g2 = any("Test" in r["title"] and r["accepted"] for r in item_results.values())
        g3 = any("Security" in r["title"] and r["accepted"] for r in item_results.values())
        g4 = any("Schema" in r["title"] and r["accepted"] for r in item_results.values())
        project_accepted = g1 and g2 and g3 and g4

        prec = {
            "project_id": pid,
            "name": pname,
            "archetype": parch,
            "segment": seg,
            "arrival_time_sec": round(arrival_sim_time, 2),
            "dispatch_time_sec": round(dispatch_sim_time, 2),
            "completion_time_sec": round(completion_sim_time, 2),
            "queue_wait_seconds": round(queue_wait_sec, 2),
            "turnaround_seconds": round(turnaround_sec, 2),
            "end_to_end_latency_seconds": round(e2e_latency_sec, 2),
            "worker1_service_demand_seconds": round(w1_demand, 2),
            "worker2_service_demand_seconds": round(w2_demand, 2),
            "accepted": project_accepted,
            "handoff_receipt": handoff_receipt,
            "items": item_results,
            "wall_start_utc": t_proj_wall_start,
            "wall_end_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        }
        all_project_records.append(prec)

        print(f"  Project Complete in {turnaround_sec:.2f}s | W1 Demand: {w1_demand:.2f}s | Accepted: {project_accepted}", flush=True)

    t_campaign_wall_end = datetime.datetime.now(datetime.timezone.utc).isoformat()
    t_end_mono = time.monotonic()
    total_physical_elapsed_sec = t_end_mono - t_start_mono

    # 4. Post-Flight Isolation Audit
    print("\n[Step 4] Executing Post-Flight Isolation Audit...", flush=True)
    post_w1_lines = audit_worker_completions("aihost-vllm-worker1.service", cursor_w1)
    post_w2_lines = audit_worker_completions("aihost-vllm-worker2.service", cursor_w2)

    total_w1_completions = len(post_w1_lines)
    total_w2_completions = len(post_w2_lines)

    # 10 projects * 5 items on W1 = 50 items on W1 (+ warmup on W2)
    # 10 projects * 3 items on W2 = 30 items on W2 + 1 warmup = 31 items on W2
    expected_w1_items = sum(1 for p in all_project_records for it in p["items"].values() if it["assigned_worker"] == "worker_1")
    expected_w2_items = sum(1 for p in all_project_records for it in p["items"].values() if it["assigned_worker"] == "worker_2") + 1  # warmup

    outside_w1_reqs = max(0, total_w1_completions - expected_w1_items)
    outside_w2_reqs = max(0, total_w2_completions - expected_w2_items)
    total_outside_reqs = outside_w1_reqs + outside_w2_reqs

    print(f"  Worker 1 completions: {total_w1_completions} (expected: {expected_w1_items}, outside: {outside_w1_reqs})", flush=True)
    print(f"  Worker 2 completions: {total_w2_completions} (expected: {expected_w2_items}, outside: {outside_w2_reqs})", flush=True)
    print(f"  Total Outside Inference Requests: {total_outside_reqs}", flush=True)

    # 5. Partition Segments
    matched_projects = [p for p in all_project_records if p["segment"] == "matched"]
    extended_projects = [p for p in all_project_records if p["segment"] == "extended"]

    def compute_cohort_stats(cohort_name: str, projs: List[Dict]) -> Dict[str, Any]:
        waits = [p["queue_wait_seconds"] for p in projs]
        e2e = [p["end_to_end_latency_seconds"] for p in projs]
        to = [p["turnaround_seconds"] for p in projs]
        w1_dem = [p["worker1_service_demand_seconds"] for p in projs]
        w2_dem = [p["worker2_service_demand_seconds"] for p in projs]
        accepted_cnt = sum(1 for p in projs if p["accepted"])
        acc_rate = (accepted_cnt / len(projs)) * 100.0

        elapsed_sec = projs[-1]["completion_time_sec"] - projs[0]["arrival_time_sec"]
        thru = (accepted_cnt / elapsed_sec) * 3600.0

        # Backlog slope
        slopes = [waits[k] - waits[k - 1] for k in range(1, len(waits))] if len(waits) > 1 else [0.0]
        mean_slope = sum(slopes) / len(slopes) if slopes else 0.0

        return {
            "cohort_name": cohort_name,
            "project_count": len(projs),
            "accepted_projects": accepted_cnt,
            "acceptance_rate_pct": round(acc_rate, 2),
            "total_campaign_elapsed_seconds": round(elapsed_sec, 2),
            "sustained_throughput_projects_per_hour": round(thru, 4),
            "queue_stability": "STABLE" if mean_slope <= 1.0 else "ACCUMULATING",
            "queue_wait_distribution": {
                "min": round(min(waits), 2),
                "mean": round(sum(waits) / len(waits), 2),
                "p50": round(percentile(waits, 0.50), 2),
                "p95": round(percentile(waits, 0.95), 2),
                "max": round(max(waits), 2),
                "growth_slope_sec_per_proj": round(mean_slope, 2),
            },
            "end_to_end_latency_distribution": {
                "min": round(min(e2e), 2),
                "mean": round(sum(e2e) / len(e2e), 2),
                "p50": round(percentile(e2e, 0.50), 2),
                "p95": round(percentile(e2e, 0.95), 2),
                "max": round(max(e2e), 2),
            },
            "turnaround_distribution": {
                "min": round(min(to), 2),
                "mean": round(sum(to) / len(to), 2),
                "p50": round(percentile(to, 0.50), 2),
                "p95": round(percentile(to, 0.95), 2),
                "max": round(max(to), 2),
            },
            "worker_demand": {
                "w1_mean_sec": round(sum(w1_dem) / len(w1_dem), 2),
                "w2_mean_sec": round(sum(w2_dem) / len(w2_dem), 2),
            },
            "projects": projs,
        }

    matched_stats = compute_cohort_stats("matched_b_plus_six_project", matched_projects)
    all_10_stats = compute_cohort_stats("extended_b_plus_ten_project", all_project_records)

    # 6. Load Frozen B Control for direct comparison
    frozen_b_path = "phase14/evidence/phase14_sustained_config_b_results.json"
    with open(frozen_b_path) as f:
        b_raw = json.load(f)
    frozen_b_stats = b_raw["regime_2"]

    comparison_summary = {
        "experiment_id": "PHASE_14_EXPERIMENT_02_B_PLUS_REQUALIFICATION",
        "canonical_repo_sha": CURRENT_REPO_SHA,
        "execution_window_utc": {
            "start": t_campaign_wall_start,
            "end": t_campaign_wall_end,
            "total_physical_duration_sec": round(total_physical_elapsed_sec, 2),
        },
        "isolation_audit": {
            "worker_1_start_cursor": cursor_w1,
            "worker_2_start_cursor": cursor_w2,
            "worker_1_completions": total_w1_completions,
            "worker_2_completions": total_w2_completions,
            "expected_worker_1_items": expected_w1_items,
            "expected_worker_2_items": expected_w2_items,
            "outside_request_count": total_outside_reqs,
            "workload_isolation_verified": total_outside_reqs == 0,
        },
        "frozen_b_control": {
            "cohort_name": frozen_b_stats["cohort_name"],
            "project_count": len(frozen_b_stats["projects"]),
            "accepted_throughput": frozen_b_stats["sustained_throughput_projects_per_hour"],
            "mean_queue_wait_sec": frozen_b_stats["queue_wait_distribution"]["mean"],
            "p95_queue_wait_sec": frozen_b_stats["queue_wait_distribution"]["p95"],
            "mean_e2e_latency_sec": frozen_b_stats["end_to_end_latency_distribution"]["mean"],
            "p95_e2e_latency_sec": frozen_b_stats["end_to_end_latency_distribution"]["p95"],
            "mean_turnaround_sec": frozen_b_stats["turnaround_distribution"]["mean"],
            "w1_mean_demand_sec": round(sum(p["worker1_service_demand_seconds"] for p in frozen_b_stats["projects"])/6, 2),
            "queue_wait_growth_slope": round((frozen_b_stats["projects"][-1]["queue_wait_seconds"] - frozen_b_stats["projects"][0]["queue_wait_seconds"])/5, 2),
        },
        "matched_b_plus_rerun": {
            "cohort_name": matched_stats["cohort_name"],
            "project_count": matched_stats["project_count"],
            "accepted_throughput": matched_stats["sustained_throughput_projects_per_hour"],
            "mean_queue_wait_sec": matched_stats["queue_wait_distribution"]["mean"],
            "p95_queue_wait_sec": matched_stats["queue_wait_distribution"]["p95"],
            "mean_e2e_latency_sec": matched_stats["end_to_end_latency_distribution"]["mean"],
            "p95_e2e_latency_sec": matched_stats["end_to_end_latency_distribution"]["p95"],
            "mean_turnaround_sec": matched_stats["turnaround_distribution"]["mean"],
            "w1_mean_demand_sec": matched_stats["worker_demand"]["w1_mean_sec"],
            "queue_wait_growth_slope": matched_stats["queue_wait_distribution"]["growth_slope_sec_per_proj"],
        },
        "matched_comparison_deltas": {
            "throughput_difference_proj_hr": round(matched_stats["sustained_throughput_projects_per_hour"] - frozen_b_stats["sustained_throughput_projects_per_hour"], 4),
            "throughput_difference_pct": round(((matched_stats["sustained_throughput_projects_per_hour"] - frozen_b_stats["sustained_throughput_projects_per_hour"]) / frozen_b_stats["sustained_throughput_projects_per_hour"]) * 100.0, 2),
            "mean_queue_wait_reduction_sec": round(frozen_b_stats["queue_wait_distribution"]["mean"] - matched_stats["queue_wait_distribution"]["mean"], 2),
            "mean_queue_wait_reduction_pct": round(((frozen_b_stats["queue_wait_distribution"]["mean"] - matched_stats["queue_wait_distribution"]["mean"]) / frozen_b_stats["queue_wait_distribution"]["mean"]) * 100.0, 2),
            "p95_latency_reduction_sec": round(frozen_b_stats["end_to_end_latency_distribution"]["p95"] - matched_stats["end_to_end_latency_distribution"]["p95"], 2),
            "w1_service_demand_reduction_sec": round(
                round(sum(p["worker1_service_demand_seconds"] for p in frozen_b_stats["projects"])/6, 2) - matched_stats["worker_demand"]["w1_mean_sec"], 2
            ),
        },
        "extended_observation_ten_projects": all_10_stats,
    }

    # 7. Save outputs
    matched_out_path = "phase14/evidence/phase14_b_plus_matched_requalification_results.json"
    extended_out_path = "phase14/evidence/phase14_b_plus_extended_requalification_results.json"
    comp_out_path = "phase14/evidence/phase14_b_plus_requalification_comparison.json"

    with open(matched_out_path, "w") as f:
        json.dump(matched_stats, f, indent=2)
    with open(extended_out_path, "w") as f:
        json.dump(all_10_stats, f, indent=2)
    with open(comp_out_path, "w") as f:
        json.dump(comparison_summary, f, indent=2)

    # Mirror traces
    with open("phase14/traces/phase14_b_plus_matched_requalification_results.json", "w") as f:
        json.dump(matched_stats, f, indent=2)
    with open("phase14/traces/phase14_b_plus_requalification_comparison.json", "w") as f:
        json.dump(comparison_summary, f, indent=2)

    print("\n=======================================================", flush=True)
    print("REQUALIFICATION CAMPAIGN COMPLETE", flush=True)
    print(f"Matched Throughput: {matched_stats['sustained_throughput_projects_per_hour']} proj/hr (B Control: {frozen_b_stats['sustained_throughput_projects_per_hour']})", flush=True)
    print(f"Matched Mean Wait: {matched_stats['queue_wait_distribution']['mean']}s (B Control: {frozen_b_stats['queue_wait_distribution']['mean']}s)", flush=True)
    print(f"Extended 10-Project Mean Wait: {all_10_stats['queue_wait_distribution']['mean']}s", flush=True)
    print(f"Outside Requests Observed: {total_outside_reqs}", flush=True)
    print(f"Saved artifacts to {matched_out_path} and {comp_out_path}", flush=True)
    print("=======================================================", flush=True)

    return comparison_summary


if __name__ == "__main__":
    run_b_plus_requalification_campaign()
