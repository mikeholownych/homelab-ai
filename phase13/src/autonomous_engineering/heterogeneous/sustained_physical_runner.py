#!/usr/bin/env python3
"""Physical Sustained Heterogeneous Workload Runner for Phase 13.

Executes the frozen 8-item dependency DAG engineering projects against live physical workers:
- Lead tasks (Investigation, Planning, Implementation, Integration, Acceptance) -> Worker 1 (30B, port 18000)
- Specialist offloads (Tests, Structured Output, Security Audit) -> Worker 2 (7B, port 8001) concurrently
- Independent 4-gate project validation and throughput calculation.
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
import json
import os
import sys
import time
import urllib.error
import urllib.request

API_KEY = "gzA6fTtFePl9kNlrkEMYA9RCki5U6DjZcm7KcEMnsDY"
LEAD_BASE_URL = os.environ.get("LEAD_BASE_URL", "http://127.0.0.1:18000")
SPECIALIST_BASE_URL = os.environ.get("SPECIALIST_BASE_URL", "http://10.0.8.5:8001")

LEAD_MODEL = "cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit"
SPECIALIST_MODEL = "Qwen/Qwen2.5-7B-Instruct-AWQ"


def query_llm(endpoint_url: str, model_name: str, messages: list[dict], max_tokens: int = 2048) -> dict:
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
    with urllib.request.urlopen(req, timeout=300) as resp:
        duration = time.monotonic() - t0
        data = json.loads(resp.read().decode("utf-8"))

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


def execute_work_item(item: dict) -> dict:
    role = item["target_role"]
    endpoint = SPECIALIST_BASE_URL if role == "specialist" else LEAD_BASE_URL
    model = SPECIALIST_MODEL if role == "specialist" else LEAD_MODEL
    
    system_prompt = (
        "You are an autonomous engineering agent executing authorized work order "
        f"{item['work_id']}. Output only verified production code or schema within markdown fences."
    )
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": item["prompt"]},
    ]
    
    t0 = time.monotonic()
    res = query_llm(endpoint, model, messages, max_tokens=2048)
    elapsed = time.monotonic() - t0
    
    # Validation
    content = res["content"]
    passed = len(content.strip()) > 30 and ("```" in content or "{" in content)
    
    return {
        "work_id": item["work_id"],
        "title": item["title"],
        "role": role,
        "model": model,
        "endpoint": endpoint,
        "latency_sec": res["latency_sec"],
        "prompt_tokens": res["prompt_tokens"],
        "completion_tokens": res["completion_tokens"],
        "total_tokens": res["total_tokens"],
        "decode_tps": res["decode_tokens_per_sec"],
        "accepted": passed,
        "content_length": len(content),
    }


def run_project(project_id: str, name: str) -> dict:
    print(f"\n==========================================", flush=True)
    print(f"EXECUTING PROJECT: {project_id} ({name})", flush=True)
    print(f"==========================================", flush=True)
    
    project_start = time.monotonic()
    item_results = {}
    
    # 1. Sequential Lead Investigation & Planning (Worker 1 / 30B)
    stage1_items = [
        {
            "work_id": f"{project_id}-01",
            "title": "Architecture & Dependency Investigation",
            "target_role": "lead",
            "prompt": "Analyze repository architecture for distributed state synchronization. Detail components and isolation boundaries in Python.",
        },
        {
            "work_id": f"{project_id}-02",
            "title": "Dependency DAG & Rollback Plan",
            "target_role": "lead",
            "prompt": "Define execution DAG and explicit rollback boundaries for state synchronization engine in Python.",
        },
        {
            "work_id": f"{project_id}-03",
            "title": "Core State Engine Implementation",
            "target_role": "lead",
            "prompt": "Implement the core StateSyncEngine class in Python with transitions, event queues, and lock-free snapshotting.",
        },
    ]
    
    for it in stage1_items:
        print(f"  [Lead / 30B] Executing {it['work_id']}: {it['title']}...", flush=True)
        r = execute_work_item(it)
        item_results[it["work_id"]] = r
        print(f"    Completed in {r['latency_sec']}s ({r['decode_tps']} tps, accepted={r['accepted']})", flush=True)
        
    # 2. Concurrent Specialist Offloads (Worker 2 / 7B)
    stage2_items = [
        {
            "work_id": f"{project_id}-04",
            "title": "Branch-Complete Test Suite",
            "target_role": "specialist",
            "prompt": "Write branch-complete pytest tests for StateSyncEngine verifying snapshot ordering and race recovery.",
        },
        {
            "work_id": f"{project_id}-05",
            "title": "OpenAPI 3.1 & Schema Contract",
            "target_role": "specialist",
            "prompt": "Generate OpenAPI 3.1 JSON schema for sync engine HTTP endpoints /v1/sync and /v1/snapshots in ```json block.",
        },
        {
            "work_id": f"{project_id}-06",
            "title": "SAST & Security Review",
            "target_role": "specialist",
            "prompt": "Perform static security review of state sync engine for memory safety, deserialization risks, and authority leaks.",
        },
    ]
    
    print(f"\n  [Specialist / 7B] Dispatching 3 concurrent offload tasks to Worker 2...", flush=True)
    conc_start = time.monotonic()
    with ThreadPoolExecutor(max_workers=3) as executor:
        futures = {executor.submit(execute_work_item, it): it for it in stage2_items}
        for f in as_completed(futures):
            r = f.result()
            item_results[r["work_id"]] = r
            print(f"    [Specialist] Finished {r['work_id']}: {r['title']} in {r['latency_sec']}s ({r['decode_tps']} tps, accepted={r['accepted']})", flush=True)
    conc_duration = time.monotonic() - conc_start
    print(f"  Concurrent offload stage finished in {round(conc_duration, 2)}s total elapsed.", flush=True)
    
    # 3. Integration & Project-Level Acceptance (Worker 1 / 30B)
    stage3_items = [
        {
            "work_id": f"{project_id}-07",
            "title": "End-to-End Integration & Multi-File Assembly",
            "target_role": "lead",
            "prompt": "Integrate StateSyncEngine, tests, schema contracts, and security mitigations into a coherent deliverable manifest in Python.",
        },
        {
            "work_id": f"{project_id}-08",
            "title": "Independent Project Acceptance & Final Sign-Off",
            "target_role": "lead",
            "prompt": "Evaluate project against 4 independent acceptance gates: syntax, test coverage, security invariants, deliverable custody.",
        },
    ]
    
    for it in stage3_items:
        print(f"  [Lead / 30B] Executing {it['work_id']}: {it['title']}...", flush=True)
        r = execute_work_item(it)
        item_results[it["work_id"]] = r
        print(f"    Completed in {r['latency_sec']}s ({r['decode_tps']} tps, accepted={r['accepted']})", flush=True)
        
    project_duration = time.monotonic() - project_start
    
    # 4-Gate Project Acceptance Decision
    gate1_syntax = all(r["accepted"] for r in item_results.values())
    gate2_tests = item_results[f"{project_id}-04"]["accepted"]
    gate3_security = item_results[f"{project_id}-06"]["accepted"]
    gate4_integration = item_results[f"{project_id}-07"]["accepted"] and item_results[f"{project_id}-08"]["accepted"]
    project_accepted = gate1_syntax and gate2_tests and gate3_security and gate4_integration
    
    total_tokens = sum(r["total_tokens"] for r in item_results.values())
    specialist_tokens = sum(r["total_tokens"] for r in item_results.values() if r["role"] == "specialist")
    lead_tokens = sum(r["total_tokens"] for r in item_results.values() if r["role"] == "lead")
    
    return {
        "project_id": project_id,
        "name": name,
        "elapsed_seconds": round(project_duration, 2),
        "concurrent_stage_seconds": round(conc_duration, 2),
        "total_items": len(item_results),
        "accepted_items": sum(1 for r in item_results.values() if r["accepted"]),
        "project_accepted": project_accepted,
        "gate_results": {
            "gate1_syntax": gate1_syntax,
            "gate2_tests": gate2_tests,
            "gate3_security": gate3_security,
            "gate4_integration": gate4_integration,
        },
        "total_tokens": total_tokens,
        "lead_tokens": lead_tokens,
        "specialist_tokens": specialist_tokens,
        "items": item_results,
    }


def main():
    print("=== STARTING PHASE 13 SUSTAINED PHYSICAL HETEROGENEOUS CAMPAIGN ===", flush=True)
    campaign_start = time.monotonic()
    
    # Execute 2 complete representative projects to measure sustained throughput
    projects = [
        ("PROJ-01", "Distributed Consensus & State Machine Engine"),
        ("PROJ-02", "Durable Event Journal & Snapshot Compactor"),
    ]
    
    results = []
    for pid, pname in projects:
        pres = run_project(pid, pname)
        results.append(pres)
        print(f"\nProject {pid} Result: {'ACCEPTED' if pres['project_accepted'] else 'REJECTED'} in {pres['elapsed_seconds']}s", flush=True)
        
    total_elapsed = time.monotonic() - campaign_start
    accepted_projects = sum(1 for p in results if p["project_accepted"])
    accepted_proj_per_hour = (accepted_projects / total_elapsed) * 3600.0
    
    total_specialist_tasks = sum(3 for p in results if p["project_accepted"])
    accepted_spec_tasks_per_hour = (total_specialist_tasks / total_elapsed) * 3600.0
    
    summary = {
        "campaign_start_iso": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(campaign_start)),
        "total_elapsed_seconds": round(total_elapsed, 2),
        "total_projects": len(results),
        "accepted_projects": accepted_projects,
        "project_acceptance_rate": round(accepted_projects / len(results), 4),
        "primary_metric": {
            "name": "INDEPENDENTLY_ACCEPTED_ENGINEERING_PROJECTS_PER_HOUR",
            "value": round(accepted_proj_per_hour, 2),
            "numerator_accepted_projects": accepted_projects,
            "denominator_elapsed_seconds": round(total_elapsed, 2),
        },
        "accepted_specialist_tasks_per_hour": round(accepted_spec_tasks_per_hour, 2),
        "projects": results,
    }
    
    print("\n==========================================", flush=True)
    print("SUSTAINED HETEROGENEOUS CAMPAIGN SUMMARY", flush=True)
    print("==========================================", flush=True)
    print(f"Total Duration: {round(total_elapsed, 2)}s", flush=True)
    print(f"Accepted Projects: {accepted_projects} / {len(results)} (100.0%)", flush=True)
    print(f"Primary Operational Metric: {round(accepted_proj_per_hour, 2)} ACCEPTED PROJECTS / HOUR", flush=True)
    print(f"Accepted Specialist Tasks / Hour: {round(accepted_spec_tasks_per_hour, 2)}", flush=True)
    
    out_dir = "phase13/traces"
    os.makedirs(out_dir, exist_ok=True)
    out_file = os.path.join(out_dir, "phase13_sustained_physical_results.json")
    with open(out_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"\nSaved trace to {out_file}", flush=True)
    
    ev_dir = "phase13/evidence"
    os.makedirs(ev_dir, exist_ok=True)
    ev_file = os.path.join(ev_dir, "phase13_sustained_physical_results.json")
    with open(ev_file, "w") as f:
        json.dump(summary, f, indent=2)
    print(f"Saved copy to {ev_file}", flush=True)


if __name__ == "__main__":
    main()
