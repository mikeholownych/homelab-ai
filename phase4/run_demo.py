#!/usr/bin/env python3
"""Phase 4 Standalone Demonstration and Model Qualification Program."""
from __future__ import annotations

import json
import sys
from pathlib import Path

# Add src directories to sys.path
BASE_DIR = Path(__file__).parent
sys.path.insert(0, str(BASE_DIR / "src"))

from autonomous_engineering.eval.candidates import list_candidates
from autonomous_engineering.eval.harness import Phase4EvaluationHarness
from autonomous_engineering.eval.comparison import ComparisonTopology


def main() -> int:
    print("=" * 80)
    print("AUTONOMOUS ENGINEERING SYSTEM: PHASE 4 QUALIFICATION DEMONSTRATION")
    print("Intel Arc Pro B65 Model Qualification, Specialist Routing & Heterogeneous Evaluation")
    print("=" * 80)

    # 1. Resolve Token for live control endpoint
    token_file = Path("/home/mike/.config/opencode/t5820-client-token")
    auth_token = token_file.read_text().strip() if token_file.exists() else None
    endpoint = "http://127.0.0.1:18010/v1"

    print(f"Target Gateway: {endpoint}")
    print(f"Auth Token Present: {auth_token is not None}")

    # 2. Run Comprehensive Qualification
    trace_dir = BASE_DIR / "evidence" / "traces"
    harness = Phase4EvaluationHarness(trace_store_dir=trace_dir)
    print("\nRunning Evaluation Program across Candidates and Held-Out Cohorts...")
    report = harness.run_full_evaluation_program(live_endpoint=endpoint, auth_token=auth_token)

    # 3. Present Candidate Inventory & Deployment Qualification
    print("\n--- 1. B65 Hardware Deployment Qualification ---")
    for cand_id, qual in report.deployment_results.items():
        status = "PASSED" if qual.passed else "FAILED"
        live_str = " (LIVE VERIFIED)" if qual.live_endpoint_verified else " (OFFLINE QUALIFIED)"
        print(f"  [{status}] {cand_id:<30} VRAM: {qual.measured_vram_gb:>4.1f} GB | Tool Fidelity: {qual.tool_call_fidelity*100:>3.0f}%{live_str}")
        if not qual.passed:
            for r in qual.disqualification_reasons:
                print(f"      Reason: {r}")

    # 4. Present Specialist Routing Matrix
    print("\n--- 2. Empirical Specialist Role Qualifications ---")
    for cand_id, roles in report.specialist_routing.items():
        role_str = ", ".join(roles) if roles else "None"
        print(f"  Candidate: {cand_id:<30} -> Qualified Roles: [{role_str}]")

    # 5. Present Matched Comparison
    print("\n--- 3. 3-Way Matched Comparison (12-Task Representative & Held-Out Cohort) ---")
    headers = f"{'Topology':<25} | {'Accepted':<10} | {'Rate':<8} | {'1st Pass':<8} | {'Mean Time':<10} | {'Mean Tokens':<12}"
    print(headers)
    print("-" * len(headers))
    for top_key, summary in report.comparison_results.items():
        print(
            f"{top_key:<25} | {summary.accepted_count:>2}/{summary.total_tasks:<6} | "
            f"{summary.acceptance_rate*100:>5.1f}%  | {summary.first_pass_rate*100:>5.1f}%  | "
            f"{summary.mean_duration_seconds:>6.1f}s   | {summary.mean_tokens_consumed:>10.0f}"
        )

    # 6. Terminal Disposition
    print("\n" + "=" * 80)
    print(f"TERMINAL DISPOSITION: {report.terminal_disposition}")
    print("=" * 80)

    # Persist structured summary
    out_file = BASE_DIR / "evidence" / "qualification_summary.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        # Convert dataclasses to dict
        summary_dict = {
            "timestamp": report.timestamp,
            "candidates_evaluated": report.candidates_evaluated,
            "deployment_results": {k: qual.__dict__ for k, qual in report.deployment_results.items()},
            "specialist_routing": report.specialist_routing,
            "comparison_results": {k: res.__dict__ for k, res in report.comparison_results.items()},
            "held_out_accepted_rate": report.held_out_accepted_rate,
            "terminal_disposition": report.terminal_disposition,
        }
        json.dump(summary_dict, f, indent=2)
    print(f"Summary persisted to {out_file}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
