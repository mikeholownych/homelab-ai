"""Training Evidence Preservation Engine without Online Fine-Tuning."""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from enum import Enum
from pathlib import Path
from typing import Dict, List, Any, Optional

from autonomous_engineering.core.crypto import content_hash


class TracePartition(str, Enum):
    TRAINING_ELIGIBLE = "training_eligible"
    HELD_OUT_EVALUATION = "held_out_evaluation"


@dataclass(frozen=True)
class TrainingTraceRecord:
    trace_id: str
    partition: TracePartition
    task_id: str
    task_class: str
    candidate_id: str
    model_manifest_hash: str
    role: str
    prompt_text: str
    tool_interactions: List[Dict[str, Any]]
    output_artifact_hashes: List[str]
    validator_verdict: str  # Strictly "ACCEPTED" or "REJECTED"
    verified_label: str  # Factual supervisor label, NEVER model self-claim
    is_repair_turn: bool
    defect_annotations: List[Dict[str, Any]]

    @classmethod
    def create(
        cls,
        partition: TracePartition,
        task_id: str,
        task_class: str,
        candidate_id: str,
        model_manifest_hash: str,
        role: str,
        prompt_text: str,
        tool_interactions: List[Dict[str, Any]],
        output_artifact_hashes: List[str],
        validator_verdict: str,
        is_repair_turn: bool = False,
        defect_annotations: Optional[List[Dict[str, Any]]] = None,
    ) -> "TrainingTraceRecord":
        if validator_verdict not in {"ACCEPTED", "REJECTED"}:
            raise ValueError(f"Invalid validator verdict: {validator_verdict}")

        # The verified label is factually derived from independent validation
        verified_label = "POSITIVE_REINFORCEMENT" if validator_verdict == "ACCEPTED" else "NEGATIVE_CONTRAST"

        payload = {
            "partition": partition.value,
            "task_id": task_id,
            "task_class": task_class,
            "candidate_id": candidate_id,
            "model_manifest_hash": model_manifest_hash,
            "role": role,
            "prompt_text": prompt_text,
            "tool_interactions": tool_interactions,
            "output_artifact_hashes": output_artifact_hashes,
            "validator_verdict": validator_verdict,
            "verified_label": verified_label,
            "is_repair_turn": is_repair_turn,
            "defect_annotations": defect_annotations or [],
        }
        trace_id = content_hash(payload)

        return cls(
            trace_id=trace_id,
            partition=partition,
            task_id=task_id,
            task_class=task_class,
            candidate_id=candidate_id,
            model_manifest_hash=model_manifest_hash,
            role=role,
            prompt_text=prompt_text,
            tool_interactions=tool_interactions,
            output_artifact_hashes=output_artifact_hashes,
            validator_verdict=validator_verdict,
            verified_label=verified_label,
            is_repair_turn=is_repair_turn,
            defect_annotations=defect_annotations or [],
        )


class TrainingEvidenceStore:
    """Stores and partitions execution traces for future model improvements.
    
    Guarantees:
    - Zero online training or distillation is executed.
    - Labels are supervisor-authoritative, never model-generated self-claims.
    - Held-out benchmark traces are strictly air-gapped from training-eligible partitions.
    """

    def __init__(self, storage_dir: Path) -> None:
        self.storage_dir = storage_dir
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.training_file = self.storage_dir / "training_eligible_traces.jsonl"
        self.heldout_file = self.storage_dir / "held_out_evaluation_traces.jsonl"

    def record_trace(self, trace: TrainingTraceRecord) -> None:
        target_file = (
            self.training_file
            if trace.partition == TracePartition.TRAINING_ELIGIBLE
            else self.heldout_file
        )
        with open(target_file, "a", encoding="utf-8") as f:
            f.write(json.dumps(asdict(trace)) + "\n")

    def load_training_dataset(self) -> List[TrainingTraceRecord]:
        """Loads only training-eligible traces, guaranteeing zero held-out contamination."""
        if not self.training_file.exists():
            return []
        traces = []
        with open(self.training_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    data["partition"] = TracePartition(data["partition"])
                    traces.append(TrainingTraceRecord(**data))
        return traces

    def load_heldout_dataset(self) -> List[TrainingTraceRecord]:
        """Loads only held-out evaluation traces."""
        if not self.heldout_file.exists():
            return []
        traces = []
        with open(self.heldout_file, "r", encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    data = json.loads(line)
                    data["partition"] = TracePartition(data["partition"])
                    traces.append(TrainingTraceRecord(**data))
        return traces
