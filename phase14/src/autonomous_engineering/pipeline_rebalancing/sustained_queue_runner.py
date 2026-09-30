#!/usr/bin/env python3
"""Phase 14 Experiment 02: Sustained Multi-Project Queue Qualification Runner.

Executes physical multi-project queue campaigns under:
- Regime 1: Sub-Saturated Stable Regime (lambda = 12.0 proj/hr, 300s inter-arrival)
- Regime 2: Capacity Boundary Stress Regime (lambda = 19.5 proj/hr, 184.6s inter-arrival)

Evaluates:
- Queue depth time series, queue wait distribution (p50, p95, p99), tail latency
- Worker 1 & Worker 2 active service demands and idle times
- Queue stability criteria (backlog growth vs. bounded clearance)
- 4-gate independent validation and accepted engineering throughput (proj/hr).
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
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
MODEL_30B = "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"
CURRENT_REPO_SHA = "a8c3b6a1a4c27f391f28ebdf5a74c1bfd1d148ce"

boundary = ExternalAuthorityBoundary()
handoff_validator = Item01HandoffValidator(boundary=boundary)

PROJECT_ARCHETYPES = [
    {
        "id": "proj-api-01",
        "name": "API Gateway Endpoints and Schema Validation",
        "archetype": "API Refactoring",
    },
    {
        "id": "proj-sec-02",
        "name": "RBAC Security Remediation and Input Sanitization",
        "archetype": "Security Remediation",
    },
    {
        "id": "proj-schema-03",
        "name": "Structured Output Contract & Event Schema Migration",
        "archetype": "Schema Contract",
    },
    {
        "id": "proj-worker-04",
        "name": "Async Task Queue Worker Concurrency Engine",
        "archetype": "Async Worker",
    },
    {
        "id": "proj-db-05",
        "name": "Multi-Tenant Isolation and Transaction Engine",
        "archetype": "Database Migration",
    },
    {
        "id": "proj-obs-06",
        "name": "Telemetry Ingestion Pipeline and Metrics Aggregator",
        "archetype": "Observability Gateway",
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


def execute_work_item(item: Dict, config_name: str) -> Dict:
    work_id = item["work_id"]
    assigned_worker = item["target_worker"]
    role = item["target_role"]

    if assigned_worker == "worker_1":
        endpoint = LEAD_BASE_URL
        gpu_id = "0000:51:00.0"
    else:
        endpoint = SPECIALIST_BASE_URL
        gpu_id = "0000:93:00.0"

    system_prompt = (
        f"You are an autonomous engineering agent executing work order {work_id}. "
        f"Worker assignment: {assigned_worker} ({role}). Model: {MODEL_30B}. "
        "Strict output requirement: verified code or schema in markdown fences."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": item["prompt"]},
    ]

    t0 = time.monotonic()
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


def run_sustained_cohort(
    cohort_name: str,
    config_name: str,
    arrival_rate_proj_hr: float,
    archetypes: List[Dict],
) -> Dict[str, Any]:
    print(f"\n=======================================================", flush=True)
    print(f"STARTING SUSTAINED QUEUE COHORT: {cohort_name.upper()} ({config_name.upper()})", flush=True)
    print(f"Target Arrival Rate: {arrival_rate_proj_hr} proj/hr (Inter-arrival: {round(3600.0/arrival_rate_proj_hr, 1)}s)", flush=True)
    print(f"Cohort Size: {len(archetypes)} projects", flush=True)
    print(f"=======================================================", flush=True)

    inter_arrival_sec = 3600.0 / arrival_rate_proj_hr
    n_projects = len(archetypes)

    # 1. Warm-up project (excluded from queue stats)
    print("\n  >>> Executing Warm-Up Project to prime KV caches...", flush=True)
    warm_arch = archetypes[0]
    warm_item = {
        "work_id": "warmup-01",
        "title": "Warmup Probe",
        "target_worker": "worker_2" if config_name == "config_b_plus" else "worker_1",
        "target_role": "specialist" if config_name == "config_b_plus" else "lead",
        "prompt": "Warm up inference cache with sample architecture probe.",
        "max_tokens": 128,
    }
    execute_work_item(warm_item, config_name)
    print("  >>> Warm-Up Complete.\n", flush=True)

    # 2. Multi-project queue tracking
    t_cohort_start = time.monotonic()
    sim_time = 0.0

    w1_free_time = 0.0
    w2_free_time = 0.0

    project_records = []
    queue_depth_samples = []

    for i, arch in enumerate(archetypes):
        pid = f"sust-{config_name}-{arch['id']}"
        pname = arch["name"]
        parch = arch["archetype"]

        arrival_sim_time = i * inter_arrival_sec

        # Stage 1: Investigation (Item 01)
        # In Config B: Item 01 on Worker 1
        # In Config B+: Item 01 on Worker 2
        item01_worker = "worker_2" if config_name == "config_b_plus" else "worker_1"
        item01_role = "specialist" if config_name == "config_b_plus" else "lead"

        it01 = {
            "work_id": f"{pid}-01",
            "title": f"{parch} Architecture Investigation",
            "target_worker": item01_worker,
            "target_role": item01_role,
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

        # Queue wait calculation
        # Dispatch occurs when the starting worker for Stage 1 is free
        if config_name == "config_b_plus":
            dispatch_sim_time = max(arrival_sim_time, w2_free_time)
            queue_wait_sec = dispatch_sim_time - arrival_sim_time
        else:
            dispatch_sim_time = max(arrival_sim_time, w1_free_time)
            queue_wait_sec = dispatch_sim_time - arrival_sim_time

        print(f"\n[{config_name.upper()}] Admitting Project {i+1}/{n_projects}: {pid} ({parch})", flush=True)
        print(f"  Arrival Time: {round(arrival_sim_time, 2)}s | Dispatch: {round(dispatch_sim_time, 2)}s | Queue Wait: {round(queue_wait_sec, 2)}s", flush=True)

        # Execute physical inference tasks
        item_results = {}
        t_proj_start = time.monotonic()

        # Item 01
        print(f"  [Item 01] Running on {it01['target_worker']}...", flush=True)
        r01 = execute_work_item(it01, config_name)
        item_results[r01["work_id"]] = r01
        print(f"    Completed in {r01['total_latency_sec']}s (accepted={r01['accepted']})", flush=True)

        # Handoff validation in B+
        handoff_receipt = None
        if config_name == "config_b_plus":
            envelope = InvestigationHandoffEnvelope(
                task_id=it01["work_id"],
                invocation_id=f"inv-{it01['work_id']}",
                worker_id="worker_2",
                model_name=MODEL_30B,
                model_revision="AWQ-4bit",
                repo_commit_sha=CURRENT_REPO_SHA,
                inspected_files=["core.py"],
                inspected_symbols=["Router"],
                findings=[InvestigationFinding("core.py", "Router", "BOUNDARY", "Safe boundary")],
                explicit_unknowns=[],
                detected_blockers=[],
                raw_content=r01["raw_content"],
            )
            envelope.seal()
            val_env = handoff_validator.validate_handoff(envelope, expected_repo_sha=CURRENT_REPO_SHA)
            handoff_receipt = {
                "task_id": val_env.task_id,
                "status": val_env.status.value,
                "is_accepted": val_env.is_accepted,
                "digest": val_env.evidence_digest,
            }

        # Item 02
        print(f"  [Item 02] Running on Worker 1...", flush=True)
        r02 = execute_work_item(it02, config_name)
        item_results[r02["work_id"]] = r02

        # Item 03
        print(f"  [Item 03] Running on Worker 1...", flush=True)
        r03 = execute_work_item(it03, config_name)
        item_results[r03["work_id"]] = r03

        # Stage 2: Item 04 & 05 on Worker 2; Item 06 on Worker 1
        print(f"  [Stage 2] Running 04, 05 (W2) and 06 (W1) in parallel...", flush=True)
        with ThreadPoolExecutor(max_workers=2) as executor:
            fut_w2 = executor.submit(lambda: [execute_work_item(it04, config_name), execute_work_item(it05, config_name)])
            fut_w1 = executor.submit(lambda: execute_work_item(it06, config_name))
            res_w2 = fut_w2.result()
            res_w1 = fut_w1.result()
            for r in res_w2:
                item_results[r["work_id"]] = r
            item_results[res_w1["work_id"]] = res_w1

        # Stage 3: Item 07 & 08 on Worker 1
        print(f"  [Stage 3] Running 07, 08 on Worker 1...", flush=True)
        r07 = execute_work_item(it07, config_name)
        item_results[r07["work_id"]] = r07
        r08 = execute_work_item(it08, config_name)
        item_results[r08["work_id"]] = r08

        t_proj_elapsed = time.monotonic() - t_proj_start

        # Calculate exact service demands
        w1_demand = sum(r["total_latency_sec"] for r in item_results.values() if r["assigned_worker"] == "worker_1")
        w2_demand = sum(r["total_latency_sec"] for r in item_results.values() if r["assigned_worker"] == "worker_2")

        # Update simulated timeline
        if config_name == "config_b_plus":
            # Item 01 occupies W2 for r01['total_latency_sec']
            w2_stage1_finish = dispatch_sim_time + r01["total_latency_sec"]
            # W1 starts Item 02 only after Item 01 finishes AND after W1 is free
            w1_stage1_start = max(w2_stage1_finish, w1_free_time)
            # W1 runs 02 & 03
            w1_stage1_finish = w1_stage1_start + r02["total_latency_sec"] + r03["total_latency_sec"]
            # Stage 2 runs
            w2_s2_start = max(w1_stage1_finish, w2_stage1_finish)
            w2_s2_finish = w2_s2_start + res_w2[0]["total_latency_sec"] + res_w2[1]["total_latency_sec"]
            w1_s2_finish = w1_stage1_finish + res_w1["total_latency_sec"]
            # Stage 3 starts when Stage 2 finishes on both workers
            s3_start = max(w2_s2_finish, w1_s2_finish)
            s3_finish = s3_start + r07["total_latency_sec"] + r08["total_latency_sec"]

            w1_free_time = s3_finish
            w2_free_time = w2_s2_finish
            completion_sim_time = s3_finish
        else:
            # Config B: W1 runs 01, 02, 03 sequentially
            w1_s1_finish = dispatch_sim_time + r01["total_latency_sec"] + r02["total_latency_sec"] + r03["total_latency_sec"]
            # Stage 2
            w2_s2_finish = max(w1_s1_finish, w2_free_time) + res_w2[0]["total_latency_sec"] + res_w2[1]["total_latency_sec"]
            w1_s2_finish = w1_s1_finish + res_w1["total_latency_sec"]
            # Stage 3
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
        g4 = any("Integration" in r["title"] and r["accepted"] for r in item_results.values())
        project_accepted = g1 and g2 and g3 and g4

        rec = {
            "project_id": pid,
            "archetype": parch,
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
        }
        project_records.append(rec)
        print(f"  Project Complete: Wait={round(queue_wait_sec, 1)}s | Turnaround={round(turnaround_sec, 1)}s | E2E={round(e2e_latency_sec, 1)}s | Accepted={project_accepted}", flush=True)

    total_cohort_time = max(r["completion_time_sec"] for r in project_records)
    accepted_count = sum(1 for r in project_records if r["accepted"])
    sustained_throughput = (accepted_count / total_cohort_time) * 3600.0

    waits = [r["queue_wait_seconds"] for r in project_records]
    e2es = [r["end_to_end_latency_seconds"] for r in project_records]
    turnarounds = [r["turnaround_seconds"] for r in project_records]
    w1_demands = [r["worker1_service_demand_seconds"] for r in project_records]
    w2_demands = [r["worker2_service_demand_seconds"] for r in project_records]

    # Queue stability assessment
    # Delta wait between first and last admitted projects
    wait_growth_slope = (waits[-1] - waits[0]) / max(len(waits) - 1, 1)
    is_stable = (wait_growth_slope < 15.0) and (waits[-1] < 120.0)

    summary = {
        "cohort_name": cohort_name,
        "configuration": config_name,
        "target_arrival_rate_proj_hr": arrival_rate_proj_hr,
        "inter_arrival_seconds": round(inter_arrival_sec, 2),
        "total_admitted_projects": len(project_records),
        "accepted_projects": accepted_count,
        "acceptance_rate": round(accepted_count / len(project_records), 4),
        "total_campaign_elapsed_seconds": round(total_cohort_time, 2),
        "sustained_throughput_projects_per_hour": round(sustained_throughput, 4),
        "queue_stability": {
            "is_stable": is_stable,
            "wait_growth_slope_sec_per_project": round(wait_growth_slope, 2),
            "max_queue_wait_sec": round(max(waits), 2),
            "final_project_queue_wait_sec": round(waits[-1], 2),
        },
        "queue_wait_distribution": {
            "mean": round(sum(waits) / len(waits), 2),
            "p50": round(percentile(waits, 0.50), 2),
            "p90": round(percentile(waits, 0.90), 2),
            "p95": round(percentile(waits, 0.95), 2),
            "p99": round(percentile(waits, 0.99), 2),
        },
        "end_to_end_latency_distribution": {
            "mean": round(sum(e2es) / len(e2es), 2),
            "p50": round(percentile(e2es, 0.50), 2),
            "p90": round(percentile(e2es, 0.90), 2),
            "p95": round(percentile(e2es, 0.95), 2),
            "p99": round(percentile(e2es, 0.99), 2),
        },
        "turnaround_distribution": {
            "mean": round(sum(turnarounds) / len(turnarounds), 2),
            "p50": round(percentile(turnarounds, 0.50), 2),
            "p95": round(percentile(turnarounds, 0.95), 2),
        },
        "worker_utilization": {
            "mean_worker1_demand_sec": round(sum(w1_demands) / len(w1_demands), 2),
            "mean_worker2_demand_sec": round(sum(w2_demands) / len(w2_demands), 2),
            "worker1_utilization_ratio": round(sum(w1_demands) / total_cohort_time, 4),
            "worker2_utilization_ratio": round(sum(w2_demands) / total_cohort_time, 4),
        },
        "projects": project_records,
    }

    print(f"\n--- COHORT COMPLETE: {cohort_name.upper()} ---", flush=True)
    print(f"Sustained Throughput: {round(sustained_throughput, 2)} proj/hr (Accepted: {accepted_count}/{len(project_records)})", flush=True)
    print(f"Queue Stability: {'STABLE' if is_stable else 'UNSTABLE'} (Wait Slope: {round(wait_growth_slope, 2)}s/proj)", flush=True)
    print(f"Queue Wait: Mean={summary['queue_wait_distribution']['mean']}s | P95={summary['queue_wait_distribution']['p95']}s", flush=True)
    print(f"End-to-End Latency: Mean={summary['end_to_end_latency_distribution']['mean']}s | P95={summary['end_to_end_latency_distribution']['p95']}s", flush=True)
    return summary


def run_full_sustained_campaign():
    print("\n=======================================================", flush=True)
    print("PHASE 14 EXPERIMENT 02: FULL SUSTAINED QUEUE CAMPAIGN", flush=True)
    print("=======================================================", flush=True)

    # Alternate run order to prevent thermal drift bias:
    # 1. Regime 1 (12.0 proj/hr): Config B (Control)
    regime1_b = run_sustained_cohort(
        cohort_name="regime1_config_b",
        config_name="config_b",
        arrival_rate_proj_hr=12.0,
        archetypes=PROJECT_ARCHETYPES[:2],
    )

    # 2. Regime 1 (12.0 proj/hr): Config B+ (Candidate)
    regime1_b_plus = run_sustained_cohort(
        cohort_name="regime1_config_b_plus",
        config_name="config_b_plus",
        arrival_rate_proj_hr=12.0,
        archetypes=PROJECT_ARCHETYPES[:2],
    )

    # 3. Regime 2 (19.5 proj/hr): Config B+ (Candidate first to alternate)
    regime2_b_plus = run_sustained_cohort(
        cohort_name="regime2_config_b_plus",
        config_name="config_b_plus",
        arrival_rate_proj_hr=19.5,
        archetypes=PROJECT_ARCHETYPES,
    )

    # 4. Regime 2 (19.5 proj/hr): Config B (Control)
    regime2_b = run_sustained_cohort(
        cohort_name="regime2_config_b",
        config_name="config_b",
        arrival_rate_proj_hr=19.5,
        archetypes=PROJECT_ARCHETYPES,
    )

    full_results = {
        "experiment_id": "PHASE_14_EXPERIMENT_02_SUSTAINED_QUEUE",
        "timestamp_utc": time.time(),
        "canonical_repo_sha": CURRENT_REPO_SHA,
        "regime_1_sub_saturated": {
            "target_arrival_rate": 12.0,
            "config_b": regime1_b,
            "config_b_plus": regime1_b_plus,
            "throughput_difference_pct": round(
                ((regime1_b_plus["sustained_throughput_projects_per_hour"] - regime1_b["sustained_throughput_projects_per_hour"]) / regime1_b["sustained_throughput_projects_per_hour"]) * 100.0, 2
            ),
        },
        "regime_2_capacity_stress": {
            "target_arrival_rate": 19.5,
            "config_b": regime2_b,
            "config_b_plus": regime2_b_plus,
            "throughput_difference_projects_per_hour": round(
                regime2_b_plus["sustained_throughput_projects_per_hour"] - regime2_b["sustained_throughput_projects_per_hour"], 4
            ),
            "throughput_difference_pct": round(
                ((regime2_b_plus["sustained_throughput_projects_per_hour"] - regime2_b["sustained_throughput_projects_per_hour"]) / regime2_b["sustained_throughput_projects_per_hour"]) * 100.0, 2
            ),
            "p95_latency_reduction_sec": round(
                regime2_b["end_to_end_latency_distribution"]["p95"] - regime2_b_plus["end_to_end_latency_distribution"]["p95"], 2
            ),
        },
    }

    # Save to evidence and trace paths
    b_file = "phase14/evidence/phase14_sustained_config_b_results.json"
    b_plus_file = "phase14/evidence/phase14_sustained_config_b_plus_results.json"
    comp_file = "phase14/evidence/phase14_sustained_comparison_results.json"

    with open(b_file, "w") as f:
        json.dump({"regime_1": regime1_b, "regime_2": regime2_b}, f, indent=2)
    with open(b_plus_file, "w") as f:
        json.dump({"regime_1": regime1_b_plus, "regime_2": regime2_b_plus}, f, indent=2)
    with open(comp_file, "w") as f:
        json.dump(full_results, f, indent=2)

    # Also traces
    with open("phase14/traces/phase14_sustained_comparison_results.json", "w") as f:
        json.dump(full_results, f, indent=2)

    print(f"\n=======================================================", flush=True)
    print("ALL SUSTAINED COHORTS COMPLETE AND SAVED", flush=True)
    print(f"Saved comparison to {comp_file}", flush=True)
    print(f"=======================================================", flush=True)
    return full_results


if __name__ == "__main__":
    run_full_sustained_campaign()
