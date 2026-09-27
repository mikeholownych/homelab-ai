"""Tests for Training Evidence Preservation and Anti-Contamination Invariants."""
import tempfile
from pathlib import Path
import pytest
from autonomous_engineering.eval.training_data import (
    TracePartition,
    TrainingTraceRecord,
    TrainingEvidenceStore,
)


def test_training_evidence_partitioning():
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = TrainingEvidenceStore(Path(tmp_dir))

        # 1. Training eligible trace
        train_trace = TrainingTraceRecord.create(
            partition=TracePartition.TRAINING_ELIGIBLE,
            task_id="train-task-01",
            task_class="defect_repair",
            candidate_id="control-qwen3-coder-30b-awq",
            model_manifest_hash="hash123",
            role="author",
            prompt_text="Fix defect in test",
            tool_interactions=[{"tool": "read_file", "path": "test.py"}],
            output_artifact_hashes=["art_hash_1"],
            validator_verdict="ACCEPTED",
        )
        store.record_trace(train_trace)

        # 2. Held-out benchmark trace
        heldout_trace = TrainingTraceRecord.create(
            partition=TracePartition.HELD_OUT_EVALUATION,
            task_id="heldout-benchmark-01",
            task_class="defect_repair",
            candidate_id="control-qwen3-coder-30b-awq",
            model_manifest_hash="hash123",
            role="author",
            prompt_text="Evaluate held out task",
            tool_interactions=[{"tool": "read_file", "path": "benchmark.py"}],
            output_artifact_hashes=["art_hash_2"],
            validator_verdict="ACCEPTED",
        )
        store.record_trace(heldout_trace)

        # Invariant: Training dataset MUST NEVER contain held-out traces
        train_dataset = store.load_training_dataset()
        assert len(train_dataset) == 1
        assert train_dataset[0].task_id == "train-task-01"
        assert train_dataset[0].partition == TracePartition.TRAINING_ELIGIBLE
        assert train_dataset[0].verified_label == "POSITIVE_REINFORCEMENT"

        heldout_dataset = store.load_heldout_dataset()
        assert len(heldout_dataset) == 1
        assert heldout_dataset[0].task_id == "heldout-benchmark-01"
        assert heldout_dataset[0].partition == TracePartition.HELD_OUT_EVALUATION


def test_supervisor_verdict_authoritative():
    # If validator rejects, label is NEGATIVE_CONTRAST regardless of model self claims
    trace = TrainingTraceRecord.create(
        partition=TracePartition.TRAINING_ELIGIBLE,
        task_id="failed-task",
        task_class="defect_repair",
        candidate_id="control-qwen3-coder-30b-awq",
        model_manifest_hash="hash123",
        role="author",
        prompt_text="Fix bug",
        tool_interactions=[],
        output_artifact_hashes=[],
        validator_verdict="REJECTED",
    )
    assert trace.verified_label == "NEGATIVE_CONTRAST"

    with pytest.raises(ValueError):
        TrainingTraceRecord.create(
            partition=TracePartition.TRAINING_ELIGIBLE,
            task_id="invalid-verdict-task",
            task_class="defect_repair",
            candidate_id="control-qwen3-coder-30b-awq",
            model_manifest_hash="hash123",
            role="author",
            prompt_text="Fix bug",
            tool_interactions=[],
            output_artifact_hashes=[],
            validator_verdict="MODEL_CLAIMS_SUCCESS",  # Invalid! Must be supervisor verdict
        )
