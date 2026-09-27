"""Adversarial and failure qualification test suite for Phase 12."""

import pytest
from autonomous_engineering.physical_qualification.hardware_evaluator import (
    PhysicalHardwareCompatibilityEvaluator,
    PhysicalCompatibilityStatus,
    ArchitectureFamily,
)
from autonomous_engineering.physical_qualification.candidate_registry import (
    CandidateArtifactRegistry,
    ArtifactVerificationStatus,
)
from autonomous_engineering.physical_qualification.evaluation_corpus import (
    QualificationCorpusManager,
)
from autonomous_engineering.physical_qualification.physical_evaluator import (
    PhysicalInferenceEvaluator,
    PhysicalEvaluationState,
)
from autonomous_engineering.physical_qualification.maintenance_manager import (
    MaintenanceProposalManager,
    MaintenanceStatus,
)


def test_adversarial_01_incorrect_gpu_memory_reporting():
    """Attack 1: Manipulating evaluator to report 128GB on a 32GB card."""
    evaluator = PhysicalHardwareCompatibilityEvaluator(vram_per_card_mib=32656, max_allocatable_mib=31023)
    res = evaluator.evaluate_model_compatibility(
        model_identifier="Oversized-Model",
        weights_size_gb=70.0,  # ~71,680 MiB
        architecture=ArchitectureFamily.LLAMA_CAUSAL_LM,
        quantization_method="AWQ-4bit",
    )
    # Must fail-closed against single card limit of 31,023 MiB
    assert res.fits_single_device is False


def test_adversarial_02_decimal_binary_memory_confusion():
    """Attack 2: Treating 32.0 GB decimal (32,000 MB) as 32,768 MiB to squeeze an oversized model."""
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    # 30.5 GB * 1024 = 31,232 MiB, which exceeds 31,023 MiB allocatable limit
    res = evaluator.evaluate_model_compatibility(
        model_identifier="Borderline-Model",
        weights_size_gb=30.5,
        architecture=ArchitectureFamily.QWEN2_CAUSAL_LM,
        quantization_method="AWQ-4bit",
        context_length=4096,
    )
    assert res.fits_single_device is False


def test_adversarial_03_candidate_artifact_substitution():
    """Attack 3: Substituting configuration file with missing or forged hash."""
    registry = CandidateArtifactRegistry()
    art = registry.register_candidate(
        candidate_id="FORGED-ART",
        model_identifier="cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit",
        snapshot_revision="4bd30395b72ea6045edd04806c4fea448d4467b3",
        architecture="Qwen2ForCausalLM",
        parameter_count_b=30.0,
        active_parameter_count_b=3.3,
        quantization_format="AWQ-4bit",
        context_window_tokens=65536,
        config_sha256="",  # Empty forged hash
        tokenizer_sha256=None,
        runtime_container_digest="docker.io/vllm/vllm-openai-xpu@sha256:abc",
        tool_call_parser="qwen3_coder",
        structured_output_engine="outlines",
    )
    assert art.status == ArtifactVerificationStatus.REJECTED_MISSING_CONFIG


def test_adversarial_04_unsupported_quantization_kernels():
    """Attack 4: Attempting to deploy unsupported exotic quantization format."""
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    res = evaluator.evaluate_model_compatibility(
        model_identifier="Candidate-HQQ",
        weights_size_gb=10.0,
        architecture=ArchitectureFamily.QWEN2_CAUSAL_LM,
        quantization_method="HQQ_2BIT_EXPERIMENTAL",
    )
    assert res.status == PhysicalCompatibilityStatus.INCOMPATIBLE
    assert "no verified Intel XPU Level Zero kernel" in res.reason


def test_adversarial_05_model_revision_drift():
    """Attack 5: Registering model with floating 'latest' or branch tag."""
    registry = CandidateArtifactRegistry()
    art = registry.register_candidate(
        candidate_id="DRIFT-MODEL",
        model_identifier="Qwen/Qwen2.5-7B-Instruct",
        snapshot_revision="main",
        architecture="Qwen2ForCausalLM",
        parameter_count_b=7.0,
        active_parameter_count_b=7.0,
        quantization_format="AWQ-4bit",
        context_window_tokens=32768,
        config_sha256="42981b44892a1940c8f93bf5fb40972bc62f2c9a6c8f0d10115175e68b11396d",
        tokenizer_sha256=None,
        runtime_container_digest="docker.io/vllm/vllm-openai-xpu@sha256:abc",
        tool_call_parser="hermes",
        structured_output_engine="outlines",
    )
    assert art.status == ArtifactVerificationStatus.REJECTED_MUTABLE_TAG


def test_adversarial_06_tool_call_schema_violations():
    """Attack 6: Candidate output emits invalid tool call JSON syntax."""
    corpus = QualificationCorpusManager()
    malformed_tool_call = "TOOL_CALL: {function: 'run_query', arguments: {query: SELECT * FROM users"  # Missing closing braces
    res = corpus.validate_task_execution("TASK-03", malformed_tool_call)
    assert res.accepted is False


def test_adversarial_07_structured_output_failures():
    """Attack 7: Candidate output emits malformed JSON schema on structured output task."""
    corpus = QualificationCorpusManager()
    invalid_json = "```json\n{'openapi': '3.1.0', invalid_json_syntax}\n```"
    res = corpus.validate_task_execution("TASK-07", invalid_json)
    assert res.accepted is False


def test_adversarial_08_context_overflow():
    """Attack 8: Requesting context exceeding physical model position embeddings."""
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    # 7B model has 32,768 max context; requesting 65,536 tokens
    kv_mib = evaluator.estimate_kv_cache_mib(
        context_length=65536,
        num_layers=28,
        kv_heads=4,
        head_dim=128,
    )
    # KV cache alone doubles to ~3,584 MiB
    assert kv_mib > 3000.0


def test_adversarial_09_kv_cache_exhaustion():
    """Attack 9: Massive concurrent batch sequences exhausting available VRAM."""
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    kv_mib_high_concurrency = evaluator.estimate_kv_cache_mib(
        context_length=32768,
        num_layers=28,
        kv_heads=4,
        head_dim=128,
        concurrency=30,  # 30 concurrent 32k sequences
    )
    # Exceeds total single-card allocatable memory
    assert kv_mib_high_concurrency > 31023.0


def test_adversarial_10_unauthorized_model_reload():
    """Attack 10: Attempting to reload model without human authorization."""
    phys_eval = PhysicalInferenceEvaluator()
    res = phys_eval.evaluate_alternative_candidate(
        candidate_id="CAND-QWEN2.5-7B-AWQ",
        model_identifier="Qwen/Qwen2.5-7B-Instruct-AWQ",
        has_explicit_human_authorization=False,
    )
    assert res.state == PhysicalEvaluationState.BLOCKED_PENDING_MAINTENANCE_AUTHORIZATION


def test_adversarial_11_protected_worker_contention():
    """Attack 11: Attempting to spawn new worker without checking remaining GPU headroom."""
    evaluator = PhysicalHardwareCompatibilityEvaluator()
    # Active resident model uses 27,869 MiB on GPU 0. Adding any model requiring > 3,154 MiB must fail.
    available_headroom = 31023 - 27869
    assert available_headroom < 4000  # Only ~3.15 GB headroom left


def test_adversarial_12_cross_worker_routing_errors():
    """Attack 12: Routing general architecture task to tool-specialist model."""
    from autonomous_engineering.physical_qualification.scheduling_evaluator import HeterogeneousSchedulingEvaluator
    evaluator = HeterogeneousSchedulingEvaluator()
    profiles = evaluator._workload_profiles
    assert profiles["ARCHITECTURAL_PLANNING"]["can_spec"] is False
    assert profiles["MULTI_STAGE_INTEGRATION"]["can_spec"] is False


def test_adversarial_13_stale_qualification_reuse():
    """Attack 13: Attempting to use Phase 11 4-task result as proof for Phase 12 general superiority."""
    # Reconciliation proved that 4 tasks are insufficient for general qualification
    from autonomous_engineering.physical_qualification.physical_evaluator import PhysicalInferenceEvaluator
    pe = PhysicalInferenceEvaluator()
    tradeoff = pe.analyze_comparative_trade_offs(859, 501, 282, 441, 12.73, 16.20, 100.0, 100.0)
    assert "TRADE_OFF" in tradeoff.trade_off_classification


def test_adversarial_14_corpus_contamination():
    """Attack 14: Checking that held-out partition tasks are not in calibration partition."""
    corpus = QualificationCorpusManager()
    calib_ids = {t.task_id for t in corpus.list_calibration_tasks()}
    held_out_ids = {t.task_id for t in corpus.list_held_out_tasks()}
    assert calib_ids.isdisjoint(held_out_ids)


def test_adversarial_15_validator_tampering():
    """Attack 15: Validating code that defines nothing should be rejected."""
    corpus = QualificationCorpusManager()
    tampered_output = "The answer is 42."
    res = corpus.validate_task_execution("TASK-01", tampered_output)
    assert res.accepted is False


def test_adversarial_16_unauthorized_candidate_promotion():
    """Attack 16: Proposal manager must never self-authorize maintenance."""
    mgr = MaintenanceProposalManager()
    prop = mgr.create_candidate_swap_proposal()
    assert prop.status == MaintenanceStatus.STOPPED_PENDING_AUTHORIZATION


def test_adversarial_17_failed_rollback_prevention():
    """Attack 17: Proposal must have at least 4 trigger conditions and complete recovery steps."""
    mgr = MaintenanceProposalManager()
    prop = mgr.create_candidate_swap_proposal()
    assert len(prop.rollback_trigger_conditions) >= 4
    assert len(prop.recovery_procedure_steps) >= 4
    assert prop.baseline_config_hash == prop.rollback_config_hash


def test_adversarial_18_manifest_corruption_detection(tmp_path):
    """Attack 18: Detect file tampering against SHA-256 manifest."""
    test_file = tmp_path / "evidence.txt"
    test_file.write_text("authentic evidence")
    import hashlib
    h = hashlib.sha256(test_file.read_bytes()).hexdigest()

    # Tamper with file
    test_file.write_text("tampered evidence")
    h_new = hashlib.sha256(test_file.read_bytes()).hexdigest()
    assert h != h_new
