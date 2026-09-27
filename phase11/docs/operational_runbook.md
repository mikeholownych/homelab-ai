# Phase 11 Operational Runbook: Evidence-Driven Model and Agent Optimization

## 1. System Overview & Architecture

The Phase 11 Evidence-Driven Model and Agent Optimization subsystem extends the Autonomous Engineering System with a reproducible, empirical qualification and optimization harness. It enables systematic evaluation of model revisions, quantization formats, specialized agent profiles, reasoning budgets, and context strategies against realistic engineering workloads.

### Key Principles
1. **Empirical Engineering Outcomes**: Candidates are evaluated on actual end-to-end task completion and sandboxed validation, not isolated token throughput or generic benchmarks.
2. **Authority Non-Expansion**: Derived agent profiles can never exceed the tool permissions, repository scope, or execution authorities of their base profile.
3. **Partition Isolation & Held-Out Quarantine**: Evaluation data is partitioned into `development`, `calibration`, and `held_out`. The held-out set is strictly quarantined against training or prompt inspection.
4. **Physical Serving Protection**: Protected inference workers (e.g. `engineering/b0` on port 18010) and host daemon processes (`hermes_cli`, `opencode --auto`, SSH tunnels) are never interrupted or evicted without explicit human operator authorization.
5. **Fail-Closed Promotion**: Candidates cannot self-promote or be promoted by autonomous agents. Human operator cryptographic signoff and verified rollback plans are strictly enforced.

---

## 2. Directory Layout & Artifacts

```
phase11/
├── docs/
│   ├── phase11_baseline_verification.md
│   ├── phase11_engineering_plan.md
│   └── operational_runbook.md
├── src/autonomous_engineering/optimization/
│   ├── __init__.py
│   ├── corpus.py                 # Evaluation corpus & partition quarantine
│   ├── registry.py               # Candidate configuration registry & digests
│   ├── evaluator.py              # Independent sandboxed engineering evaluator
│   ├── comparative.py           # Paired comparative qualification manager
│   ├── hardware_eval.py          # Intel Arc B65 VRAM constraints & swap proposals
│   ├── profile_optimizer.py      # Versioned agent profile optimization & authority intersection
│   ├── context_reasoning.py      # Context strategy & adaptive reasoning benchmarking
│   ├── experiment_scheduler.py   # Concurrency containment & persistent state machine
│   └── lifecycle.py              # Candidate qualification lifecycle & promotion gates
├── tests/
│   ├── test_evaluation_corpus.py
│   ├── test_candidate_registry.py
│   ├── test_engineering_evaluator.py
│   ├── test_comparative_qualification.py
│   ├── test_hardware_eval.py
│   ├── test_profile_optimizer.py
│   ├── test_context_reasoning.py
│   ├── test_experiment_scheduler.py
│   ├── test_qualification_lifecycle.py
│   ├── test_phase11_adversarial_security.py
│   └── test_phase11_preregistration_gates.py
├── evidence/
│   ├── evaluation_corpus_report.md
│   ├── candidate_registry_report.md
│   ├── independent_evaluation_report.md
│   ├── comparative_qualification_report.md
│   ├── model_quantization_report.md
│   ├── agent_profile_optimization_report.md
│   ├── context_reasoning_optimization_report.md
│   ├── experiment_scheduling_report.md
│   ├── qualification_promotion_report.md
│   ├── adversarial_security_report.md
│   ├── protected_service_audit.md
│   ├── final_report.md
│   └── manifest.sha256
└── run_demo.py
```

---

## 3. Standard Operational Workflows

### 3.1 Registering an Optimization Candidate
To evaluate a new model variant or specialized profile configuration:
```python
from autonomous_engineering.optimization.registry import OptimizationCandidateRegistry, CandidateConfiguration, ExecutionMode

registry = OptimizationCandidateRegistry(storage_path="var/registry.json")
candidate = CandidateConfiguration(
    candidate_id="candidate-qwen3-opt-profile-v1",
    model_identity="Qwen/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
    model_revision="2026-03-r1",
    quantization="awq-4bit",
    inference_parameters={"tensor_parallel": 1, "max_model_len": 32768, "gpu_memory_utilization": 0.90},
    profile_name="implementation-engineer",
    profile_version="1.1.0",
    reasoning_budget={"max_reasoning_tokens": 1024, "effort_level": "medium"},
    context_strategy="targeted_symbols",
    tool_adapter="strict_sandboxed_v2",
    physical_worker="worker-b65-0",
    workload_classes=["bug_investigation", "refactoring"],
    execution_mode=ExecutionMode.PHYSICAL,
)
registered = registry.register_candidate(candidate)
print(f"Registered candidate digest: {registered.canonical_digest}")
```

### 3.2 Running Independent Calibration Evaluation
```python
from autonomous_engineering.optimization.corpus import EngineeringEvaluationCorpusManager, CorpusPartition
from autonomous_engineering.optimization.evaluator import EngineeringCandidateEvaluator

corpus_mgr = EngineeringEvaluationCorpusManager()
corpus_mgr.initialize_standard_corpus()
calibration_tasks = corpus_mgr.get_tasks_for_partition(CorpusPartition.CALIBRATION)

evaluator = EngineeringCandidateEvaluator(traces_dir="var/eval_traces")
summary = evaluator.evaluate_candidate(registered, calibration_tasks)
print(f"Acceptance rate: {summary.acceptance_rate * 100:.1f}%")
```

### 3.3 Running Paired Comparative Qualification
```python
from autonomous_engineering.optimization.comparative import ComparativeQualificationManager

comp_mgr = ComparativeQualificationManager(reports_dir="var/reports")
report = comp_mgr.evaluate_comparison(
    control=control_candidate,
    candidate=registered,
    control_results=control_summary.results,
    candidate_results=summary.results,
)
print(f"Comparative verdict: {report.verdict.value}")
```

### 3.4 Promoting a Qualified Candidate
Promotion strictly requires a human operator signature and verified rollback plan:
```python
from autonomous_engineering.optimization.lifecycle import CandidateQualificationLifecycle

lifecycle = CandidateQualificationLifecycle(db_path="var/lifecycle.db")
rollback_plan = {
    "target_control_id": "control-b0-qwen3-coder-awq-tp1-v1",
    "rollback_procedure": "Revert active specialized profile to implementation-engineer:1.0.0",
    "validation_health_check": "GET http://127.0.0.1:18010/v1/models",
    "operator_signoff": "mike@homelab-ai",
}
promoted = lifecycle.promote(
    candidate_id="candidate-qwen3-opt-profile-v1",
    promoted_by="mike@homelab-ai",
    rollback_plan=rollback_plan,
    notes="Authorized promotion following empirical comparative qualification",
)
```

---

## 4. Emergency Procedures & Rollback

### 4.1 Immediate Rollback Procedure
If a newly promoted profile or inference parameter introduces regressions or instability:
1. Issue an explicit rollback via `CandidateQualificationLifecycle.rollback_candidate(candidate_id, operator, reason)`.
2. The lifecycle immediately transitions the candidate from `PROMOTED` to `REVOKED`.
3. The system restores active configuration to the `target_control_id` defined in the cryptographically logged rollback plan.
4. Verify endpoint health: `curl -H "Authorization: Bearer test-token" http://127.0.0.1:18010/v1/models`.

### 4.2 Handling Incompatible Model Swaps
If a candidate model requires swapping physical weights on the Intel Arc Pro B65 GPUs:
1. `ModelHardwareCompatibilityEvaluator` intercepts the request and generates a `MaintenanceProposal`.
2. Execution of the swap is paused and blocked.
3. Operator reviews memory budget (16.0 GB physical limit per B65 GPU).
4. Operator signs maintenance proposal with an offline operator token.
5. If denied, the proposal is rejected and existing serving remains uninterrupted.
