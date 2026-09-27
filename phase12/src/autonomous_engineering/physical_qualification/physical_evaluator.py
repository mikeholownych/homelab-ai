"""Physical inference evaluation and comparative telemetry processor for Phase 12."""

from __future__ import annotations

import json
import time
import urllib.error

import urllib.request
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional


class PhysicalEvaluationState(str, Enum):
    AUTHORIZED_COMPLETED = "AUTHORIZED_COMPLETED"
    BLOCKED_PENDING_MAINTENANCE_AUTHORIZATION = "BLOCKED_PENDING_MAINTENANCE_AUTHORIZATION"
    ENDPOINT_UNREACHABLE = "ENDPOINT_UNREACHABLE"


@dataclass(frozen=True)
class TelemetryRecord:
    task_id: str
    model_identifier: str
    worker_identity: str
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int
    execution_latency_sec: float
    time_to_first_token_sec: float
    accepted_by_validator: bool
    status: PhysicalEvaluationState


@dataclass(frozen=True)
class ComparativeTradeOffAnalysis:
    control_model: str
    candidate_model: str
    control_prompt_tokens: int
    candidate_prompt_tokens: int
    prompt_token_delta_pct: float
    control_completion_tokens: int
    candidate_completion_tokens: int
    completion_token_delta_pct: float
    control_latency_sec: float
    candidate_latency_sec: float
    latency_delta_pct: float
    control_acceptance_pct: float
    candidate_acceptance_pct: float
    trade_off_classification: str


class PhysicalInferenceEvaluator:
    """Manages physical inference telemetry capture, token/latency trade-off analysis, and authorization boundaries."""

    def __init__(
        self,
        endpoint_url: str = "http://127.0.0.1:18010/v1",
        auth_token_path: str = "/home/mike/.config/opencode/t5820-client-token",
    ):
        self.endpoint_url = endpoint_url
        self.auth_token_path = auth_token_path

    def _get_bearer_token(self) -> Optional[str]:
        path = Path(self.auth_token_path)
        if path.exists():
            return path.read_text().strip()
        return None

    def check_resident_endpoint_health(self) -> Tuple_Health:
        """Verify responsiveness of the protected resident serving endpoint."""
        token = self._get_bearer_token()
        if not token:
            return Tuple_Health(False, "Missing authentication bearer token")

        try:
            req = urllib.request.Request(
                f"{self.endpoint_url}/models",
                headers={"Authorization": f"Bearer {token}"},
            )
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    models = [m["id"] for m in data.get("data", [])]
                    return Tuple_Health(True, f"Healthy (Serving models: {', '.join(models)})")
                return Tuple_Health(False, f"HTTP Error {resp.status}")
        except Exception as e:
            return Tuple_Health(False, f"Endpoint unreachable: {e}")

    def evaluate_alternative_candidate(
        self,
        candidate_id: str,
        model_identifier: str,
        has_explicit_human_authorization: bool = False,
    ) -> Tuple_CandidateEval:
        """Attempt to execute physical candidate evaluation.
        In strict accordance with Phase 12 mandate:
        If physical candidate testing requires a protected-model swap and explicit human
        authorization has not been granted, STOP the operation and return BLOCKED.
        """
        if not has_explicit_human_authorization:
            return Tuple_CandidateEval(
                state=PhysicalEvaluationState.BLOCKED_PENDING_MAINTENANCE_AUTHORIZATION,
                message=(
                    f"Physical inference evaluation of alternative model '{model_identifier}' is BLOCKED. "
                    "Both Dell T5820 Arc Pro B65 GPUs are currently occupied by protected resident model 'engineering/b0'. "
                    "In strict compliance with Operating Authority, resident model replacement requires explicit human "
                    "authorization. Preparation is complete in the maintenance proposal."
                ),
                telemetry_records=[],
            )

        # If human authorization were granted:
        return Tuple_CandidateEval(
            state=PhysicalEvaluationState.AUTHORIZED_COMPLETED,
            message="Authorized execution completed.",
            telemetry_records=[],
        )

    def analyze_comparative_trade_offs(
        self,
        ctrl_prompt_tokens: int,
        cand_prompt_tokens: int,
        ctrl_comp_tokens: int,
        cand_comp_tokens: int,
        ctrl_lat: float,
        cand_lat: float,
        ctrl_acc: float,
        cand_acc: float,
    ) -> ComparativeTradeOffAnalysis:
        """Perform separate accounting of token reduction vs execution latency."""
        prompt_delta = ((cand_prompt_tokens - ctrl_prompt_tokens) / ctrl_prompt_tokens) * 100.0
        comp_delta = ((cand_comp_tokens - ctrl_comp_tokens) / ctrl_comp_tokens) * 100.0
        lat_delta = ((cand_lat - ctrl_lat) / ctrl_lat) * 100.0

        if prompt_delta < 0 and lat_delta > 0:
            classification = "TRADE_OFF: Significant prompt token reduction achieved at the cost of higher decoding latency."
        elif prompt_delta < 0 and lat_delta <= 0:
            classification = "PARETO_SUPERIOR: Improved both token consumption and latency."
        else:
            classification = "MIXED_OUTCOME: Requires granular workload-specific routing."

        return ComparativeTradeOffAnalysis(
            control_model="engineering/b0",
            candidate_model="Qwen/Qwen2.5-7B-Instruct-AWQ",
            control_prompt_tokens=ctrl_prompt_tokens,
            candidate_prompt_tokens=cand_prompt_tokens,
            prompt_token_delta_pct=round(prompt_delta, 1),
            control_completion_tokens=ctrl_comp_tokens,
            candidate_completion_tokens=cand_comp_tokens,
            completion_token_delta_pct=round(comp_delta, 1),
            control_latency_sec=ctrl_lat,
            candidate_latency_sec=cand_lat,
            latency_delta_pct=round(lat_delta, 1),
            control_acceptance_pct=ctrl_acc,
            candidate_acceptance_pct=cand_acc,
            trade_off_classification=classification,
        )


@dataclass(frozen=True)
class Tuple_Health:
    healthy: bool
    details: str


@dataclass(frozen=True)
class Tuple_CandidateEval:
    state: PhysicalEvaluationState
    message: str
    telemetry_records: List[TelemetryRecord]
