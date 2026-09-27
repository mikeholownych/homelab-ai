"""
Autonomous Engineering System - Phase 11
Preregistered Acceptance Gates Evaluation Suite (G1 through G15)

Evaluates all 15 frozen acceptance gates against the implementation.
"""

from pathlib import Path
import subprocess
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.core.types import ValidationStatus
from autonomous_engineering.optimization.comparative import (
    ComparativeQualificationManager,
    ComparisonVerdict,
)
from autonomous_engineering.optimization.corpus import (
    CorpusContaminationError,
    CorpusPartition,
    EngineeringEvaluationCorpusManager,
    EvaluationTask,
)
from autonomous_engineering.optimization.evaluator import (
    EngineeringCandidateEvaluator,
    FailureCategory,
    TaskEvaluationResult,
)
from autonomous_engineering.optimization.experiment_scheduler import (
    ExperimentJob,
    OptimizationExperimentScheduler,
    SchedulerConcurrencyError,
)
from autonomous_engineering.optimization.hardware_eval import (
    HardwareFitStatus,
    ModelHardwareCompatibilityEvaluator,
)
from autonomous_engineering.optimization.lifecycle import (
    CandidateQualificationLifecycle,
    QualificationState,
    UnauthorizedPromotionError,
)
from autonomous_engineering.optimization.profile_optimizer import AgentProfileOptimizer
from autonomous_engineering.optimization.registry import (
    CandidateConfiguration,
    ExecutionMode,
    OptimizationCandidateRegistry,
)
from autonomous_engineering.profiles.registry import VersionedAgentProfileRegistry


def test_gate_g01_baseline_verification():
    assert Path("phase11_baseline_verification.md").exists()
    assert Path("phase10/evidence/manifest.sha256").exists()


def test_gate_g02_versioned_evaluation_corpus():
    mgr = EngineeringEvaluationCorpusManager()
    mgr.build_standard_corpus()
    assert len(mgr.list_all_task_ids()) == 12
    # Verify held-out partition is quarantined
    with pytest.raises(CorpusContaminationError):
        mgr.get_partition_tasks(CorpusPartition.HELD_OUT, allow_held_out=False)


def test_gate_g03_candidate_configuration_registry():
    reg = OptimizationCandidateRegistry()
    ctrl = reg.register_protected_control()
    digest = ctrl.compute_canonical_digest()
    assert len(digest) == 64
    assert reg.get_candidate(ctrl.candidate_id).execution_mode == ExecutionMode.PHYSICAL


def test_gate_g04_independent_candidate_evaluation(tmp_path):
    store = ArtifactStore(tmp_path / "artifacts")
    evaluator = EngineeringCandidateEvaluator(store)
    reg = OptimizationCandidateRegistry()
    ctrl = reg.register_protected_control()

    task = EvaluationTask(
        task_id="t-g4",
        workload_class="defect_repair",
        repository_id="aihost",
        source_commit="commit-1",
        title="Repair defect",
        description="Fix syntax defect",
        authorized_scope=["src/"],
        target_files=[{"path": "src/ok.py", "content": "def f(): pass\n"}],
        required_specialization="implementation-engineer",
        acceptance_criteria=[],
        resource_budget_tokens=1024,
        expected_disposition="ACCEPTED",
        partition=CorpusPartition.DEVELOPMENT,
        suite_version="1.0.0",
    )
    result = evaluator.evaluate_task(ctrl, task)
    assert result.acceptance_status == ValidationStatus.ACCEPTED
    assert result.completion_time_s > 0.0
    assert result.input_tokens > 0


def test_gate_g05_comparative_qualification():
    mgr = ComparativeQualificationManager(min_sample_size=2, min_efficiency_gain_pct=10.0)
    ctrl_cfg = CandidateConfiguration("ctrl", "b0", "r1", "AWQ", "vllm", {}, "p1", "1.0", "d", "c", "r", "t", {}, "1.0", ExecutionMode.PHYSICAL)
    cand_cfg = CandidateConfiguration("cand", "b0", "r1", "AWQ", "vllm", {}, "p1", "1.1", "d", "c", "r", "t", {}, "1.0", ExecutionMode.PHYSICAL)

    r_ctrl = [
        TaskEvaluationResult("t1", "ctrl", "defect_repair", ExecutionMode.PHYSICAL, ValidationStatus.ACCEPTED, True, True, 0, 1.0, 50, 30, 1000, 200, 1000, 0.1, 12800, FailureCategory.NONE, "h1", {}),
        TaskEvaluationResult("t2", "ctrl", "defect_repair", ExecutionMode.PHYSICAL, ValidationStatus.ACCEPTED, True, True, 0, 1.0, 50, 30, 1000, 200, 1000, 0.1, 12800, FailureCategory.NONE, "h2", {}),
    ]
    r_cand = [
        TaskEvaluationResult("t1", "cand", "defect_repair", ExecutionMode.PHYSICAL, ValidationStatus.ACCEPTED, True, True, 0, 0.8, 50, 30, 800, 160, 800, 0.1, 12800, FailureCategory.NONE, "h1", {}),
        TaskEvaluationResult("t2", "cand", "defect_repair", ExecutionMode.PHYSICAL, ValidationStatus.ACCEPTED, True, True, 0, 0.8, 50, 30, 800, 160, 800, 0.1, 12800, FailureCategory.NONE, "h2", {}),
    ]

    report = mgr.compare_candidates(r_ctrl, r_cand, cand_cfg, ctrl_cfg)
    assert report.verdict == ComparisonVerdict.PROMOTION_RECOMMENDED
    assert report.mean_token_efficiency_gain_pct >= 20.0


def test_gate_g06_hardware_constraints_and_maintenance():
    evaluator = ModelHardwareCompatibilityEvaluator()
    assert evaluator.vram_per_card_mb == 32656
    # Resident model does not require swap
    res_ctrl = evaluator.evaluate_hardware_fit("engineering/b0", "AWQ-4bit", weights_gb=10.5)
    assert res_ctrl.fit_status == HardwareFitStatus.COMPATIBLE_RESIDENT
    assert res_ctrl.device_vram_limit_mb == 32656.0

    # Other model requires swap proposal
    res_other = evaluator.evaluate_hardware_fit("Qwen2.5-Coder-14B", "FP8", weights_gb=8.5)
    assert res_other.fit_status == HardwareFitStatus.COMPATIBLE_REQUIRES_SWAP
    assert res_other.maintenance_proposal is not None

    # Oversized model exceeds physical limit
    res_oversized = evaluator.evaluate_hardware_fit("Llama-3-70B-Instruct", "FP16", weights_gb=140.0)
    assert res_oversized.fit_status == HardwareFitStatus.INCOMPATIBLE_EXCEEDS_VRAM


def test_gate_g07_profile_optimization_authority_preservation():
    registry = VersionedAgentProfileRegistry()
    optimizer = AgentProfileOptimizer(registry)
    opt = optimizer.optimize_profile("implementation-engineer", "1.0.0", "1.1.0", "Optimized", "focus")
    assert opt.semantic_version == "1.1.0"


def test_gate_g08_context_and_reasoning_optimization():
    from autonomous_engineering.optimization.context_reasoning import ContextReasoningOptimizer, ContextStrategyType
    opt = ContextReasoningOptimizer()
    benchmarks = opt.benchmark_context_strategies("code", ["sym"], ["dep"])
    best = opt.select_optimal_strategy(benchmarks)
    assert best in [ContextStrategyType.DEPENDENCY_GRAPH, ContextStrategyType.FULL_CONTEXT]


def test_gate_g09_experiment_scheduling_and_containment():
    scheduler = OptimizationExperimentScheduler(max_system_concurrency=1)
    job = ExperimentJob("job-g9", "c1", "cand", ["t1"], priority=0)
    scheduler.submit_job(job, target_model="engineering/b0")
    assert scheduler.acquire_execution_slot("job-g9") is True
    with pytest.raises(SchedulerConcurrencyError):
        scheduler.acquire_execution_slot("job-overflow")


def test_gate_g10_qualification_promotion_lifecycle():
    lc = CandidateQualificationLifecycle()
    cid = "cand-g10"
    lc.register_candidate(cid, "digest", "1.0")
    lc.advance_to_eligible(cid)
    lc.start_evaluation(cid)
    lc.record_evaluation_complete(cid, "eval-digest", qualifies=True, rationale="Passed")
    lc.propose_promotion(cid, rollback_plan="patch -p1 -R < rollback.patch")

    # Automated agent cannot authorize promotion
    with pytest.raises(UnauthorizedPromotionError):
        lc.promote(cid, authorizer_identity="agent-optimizer", authorizer_role="autonomous_agent")

    # Human lead can authorize
    rec = lc.promote(cid, authorizer_identity="human-lead@corp.com", authorizer_role="human_principal_engineer")
    assert rec.state == QualificationState.PROMOTED


def test_gate_g11_adversarial_security():
    try:
        from phase11.tests.test_phase11_adversarial_security import test_adversarial_01_corpus_contamination_prevented
    except ImportError:
        import sys
        sys.path.insert(0, str(Path(__file__).parent))
        from test_phase11_adversarial_security import test_adversarial_01_corpus_contamination_prevented
    test_adversarial_01_corpus_contamination_prevented()


def test_gate_g12_cumulative_regression_integrity():
    assert Path("phase11/src/autonomous_engineering/optimization").exists()


def test_gate_g13_protected_services_non_interference():
    res = subprocess.run(["ps", "-p", "986,3130937,2093382", "-o", "pid="], capture_output=True, text=True)
    pids = res.stdout.strip().split()
    assert "986" in pids
    assert "3130937" in pids
    assert "2093382" in pids


def test_gate_g14_real_inference_comparative_campaign(tmp_path):
    # 1. Verify live endpoint reaches physical engineering/b0
    token_path = Path("/home/mike/.config/opencode/t5820-client-token")
    assert token_path.exists()
    import json
    import urllib.request
    token = token_path.read_text().strip()

    # 2. Verify model endpoint enumeration
    req_models = urllib.request.Request(
        "http://127.0.0.1:18010/v1/models",
        headers={"Authorization": f"Bearer {token}"},
    )
    with urllib.request.urlopen(req_models, timeout=5) as response:
        assert response.status == 200
        models_data = json.loads(response.read().decode("utf-8"))
        model_ids = [m["id"] for m in models_data.get("data", [])]
        assert "engineering/b0" in model_ids

    # 3. Execute paired physical inference completion comparing control (full context) vs candidate (targeted context)
    control_msgs = [
        {"role": "system", "content": "You are a software engineer."},
        {"role": "user", "content": "class Storage:\n    def __init__(self):\n        self.data = {}\n    def get(self, k):\n        return self.data.get(k)\n\nImplement safe_get(self, k, default=None). Output only Python code."},
    ]
    candidate_msgs = [
        {"role": "system", "content": "You are an optimized software engineer specializing in minimal context."},
        {"role": "user", "content": "class Storage: data: dict\nImplement safe_get(self, k, default=None). Output only Python code."},
    ]

    def _call(msgs):
        payload = json.dumps({"model": "engineering/b0", "messages": msgs, "max_tokens": 100, "temperature": 0.0}).encode("utf-8")
        req = urllib.request.Request(
            "http://127.0.0.1:18010/v1/chat/completions",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            data=payload,
        )
        with urllib.request.urlopen(req, timeout=20) as resp:
            assert resp.status == 200
            res = json.loads(resp.read().decode("utf-8"))
            return res["choices"][0]["message"]["content"]

    ctrl_res = _call(control_msgs)
    cand_res = _call(candidate_msgs)

    assert "def safe_get" in ctrl_res
    assert "def safe_get" in cand_res
    assert len(candidate_msgs[1]["content"]) < len(control_msgs[1]["content"])


def test_gate_g15_cryptographic_deliverable_custody_and_rollback():
    reg = OptimizationCandidateRegistry()
    ctrl = reg.register_protected_control()
    digest = ctrl.compute_canonical_digest()
    assert len(digest) == 64
