"""Representative Engineering Reliability Cohort Evaluation across 4 Classes (8 Fixtures)."""
from pathlib import Path
import shutil
import tempfile
import pytest

from autonomous_engineering.artifacts.store import ArtifactStore
from autonomous_engineering.authority.admission import AdmissionEvaluator
from autonomous_engineering.core.types import WorkOrderState
from autonomous_engineering.interface.adapter import HumanInterfaceAdapter
from autonomous_engineering.orchestrator import OrchestratorControlPlane
from autonomous_engineering.planning.planner import ExecutionPlanner
from autonomous_engineering.registry.models import (
    EmpiricalSkillRecord,
    EvidenceSource,
    HardwareTarget,
    RuntimeConfig,
    WorkerCapabilityProfile,
)
from autonomous_engineering.registry.registry import WorkerCapabilityRegistry
from autonomous_engineering.repair.controller import BoundedRepairController
from autonomous_engineering.router.router import CapabilityRouter
from autonomous_engineering.validator.independent import IndependentValidator
from autonomous_engineering.workers.simulated import (
    FastCoderWorker,
    MultiFileWorker,
    RefactorWorker,
    ReviewerWorker,
    TestDevWorker,
)
from autonomous_engineering.workflow.engine import WorkflowEngine
from autonomous_engineering.work_order.compiler import WorkOrderCompiler
from autonomous_engineering.work_order.models import AcceptanceCriterion


@pytest.fixture
def b65_registry():
    registry = WorkerCapabilityRegistry()
    hw_0 = HardwareTarget("intel_arc_pro_b65", "0000:51:00.0", 32 * 1024**3, "xe-24.1")
    hw_1 = HardwareTarget("intel_arc_pro_b65", "0000:93:00.0", 32 * 1024**3, "xe-24.1")
    runtime = RuntimeConfig("vllm_xpu", "engineering/b0", "v1.7", "int4", 16384, "qwen2", "hermes")

    prof_author = WorkerCapabilityProfile(
        profile_id="prof-b65-0",
        worker_id="worker-b65-0",
        hardware=hw_0,
        runtime=runtime,
        empirical_skills={
            "defect_patch": EmpiricalSkillRecord(
                "defect_patch", True, 0.94, 50, "2026-09-27", EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT
            ),
            "implementation": EmpiricalSkillRecord(
                "implementation", True, 0.91, 45, "2026-09-27", EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT
            ),
            "test_development": EmpiricalSkillRecord(
                "test_development", True, 0.92, 40, "2026-09-27", EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT
            ),
            "refactoring": EmpiricalSkillRecord(
                "refactoring", True, 0.95, 42, "2026-09-27", EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT
            ),
            "maintainability_refactor": EmpiricalSkillRecord(
                "maintainability_refactor", True, 0.95, 42, "2026-09-27", EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT
            ),
        },
    )

    prof_reviewer = WorkerCapabilityProfile(
        profile_id="prof-b65-1",
        worker_id="worker-b65-1",
        hardware=hw_1,
        runtime=runtime,
        empirical_skills={
            "independent_review": EmpiricalSkillRecord(
                "independent_review", True, 0.96, 60, "2026-09-27", EvidenceSource.EMPIRICAL_DEPLOYED_MEASUREMENT
            )
        },
    )

    registry.register(prof_author)
    registry.register(prof_reviewer)
    return registry


# --- Cohort 1: Defect Repair ---

def test_cohort_1a_defect_repair_stats(b65_registry):
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "disposable_repo"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"
        shutil.copytree(fixture_dir, repo_dir)

        engine = WorkflowEngine(tmp_path / "engine.sqlite")
        store = ArtifactStore(tmp_path / "artifacts")
        adapter = HumanInterfaceAdapter(engine, store)

        patch = (
            "diff --git a/src/stats_utils.py b/src/stats_utils.py\n"
            "--- a/src/stats_utils.py\n"
            "+++ b/src/stats_utils.py\n"
            "@@ -9,4 +9,4 @@\n"
            "-    if window_size == 0:\n"
            "+    if window_size <= 0:\n"
            "         raise ValueError(\"window_size must be positive\")\n"
            "-\n"
            "+    if window_size > len(data):\n"
            "+        return []\n"
        )
        workers = {
            "worker-b65-0": FastCoderWorker("worker-b65-0", "prof-b65-0", store, patch_content=patch),
            "worker-b65-1": ReviewerWorker("worker-b65-1", "prof-b65-1", store),
        }

        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text="Fix moving average window boundary checks",
            source_channel="cli",
            source_reference="cohort-1a",
            repository_id="disposable_repo",
            baseline_commit="8b25d26",
            proposed_mutation_paths=["src/stats_utils.py"],
            acceptance_criteria=[
                AcceptanceCriterion("c1", "Run pytest", "pytest", "tests/test_stats_utils.py")
            ],
        )
        adapter.submit_work_order(wo)

        orch = OrchestratorControlPlane(
            admission_evaluator=AdmissionEvaluator(),
            planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="defect_patch"),
            router=CapabilityRouter(b65_registry),
            engine=engine,
            artifact_store=store,
            validator=IndependentValidator(store),
            repair_controller=BoundedRepairController(),
            workers=workers,
            baseline_repo_dir=repo_dir,
            enable_review_repair=True,
        )
        state = orch.execute_work_order(wo)
        assert state == WorkOrderState.ACCEPTED

        delivery = adapter.deliver_accepted_artifact(wo.work_order_id, wo.version)
        assert delivery["terminal_disposition"] == "ACCEPTED"
        assert "src/stats_utils.py" in delivery["deliverable"]["changed_files"]


def test_cohort_1b_defect_repair_series(b65_registry):
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "cohort" / "defect_repair_series_repo"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"
        shutil.copytree(fixture_dir, repo_dir)

        engine = WorkflowEngine(tmp_path / "engine.sqlite")
        store = ArtifactStore(tmp_path / "artifacts")
        adapter = HumanInterfaceAdapter(engine, store)

        patch = (
            "--- a/src/math_series.py\n"
            "+++ b/src/math_series.py\n"
            "@@ -6,11 +6,12 @@\n"
            "     - If r == 0: raise ValueError(\"ratio r cannot be zero\")\n"
            "     - Returns list of float terms: [a * (r ** i) for i in range(n)]\n"
            "     \"\"\"\n"
            "-    # Defect: Only checks n == 0, misses negative n\n"
            "-    if n == 0:\n"
            "+    if n <= 0:\n"
            "         raise ValueError(\"n must be positive\")\n"
            " \n"
            "-    # Defect: Missing check for r == 0\n"
            "+    if r == 0:\n"
            "+        raise ValueError(\"ratio r cannot be zero\")\n"
            "+\n"
            "     terms = []\n"
            "     current = float(a)\n"
            "     for _ in range(n):\n"
        )
        workers = {
            "worker-b65-0": FastCoderWorker("worker-b65-0", "prof-b65-0", store, patch_content=patch),
            "worker-b65-1": ReviewerWorker("worker-b65-1", "prof-b65-1", store),
        }

        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text="Fix geometric series validation for negative n and zero ratio",
            source_channel="cli",
            source_reference="cohort-1b",
            repository_id="defect_repair_series_repo",
            baseline_commit="c-1b",
            proposed_mutation_paths=["src/math_series.py"],
            acceptance_criteria=[
                AcceptanceCriterion("c1", "Run pytest", "pytest", "tests/test_math_series.py")
            ],
        )
        adapter.submit_work_order(wo)

        orch = OrchestratorControlPlane(
            admission_evaluator=AdmissionEvaluator(),
            planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="defect_patch"),
            router=CapabilityRouter(b65_registry),
            engine=engine,
            artifact_store=store,
            validator=IndependentValidator(store),
            repair_controller=BoundedRepairController(),
            workers=workers,
            baseline_repo_dir=repo_dir,
            enable_review_repair=True,
        )
        state = orch.execute_work_order(wo)
        assert state == WorkOrderState.ACCEPTED

        delivery = adapter.deliver_accepted_artifact(wo.work_order_id, wo.version)
        assert delivery["terminal_disposition"] == "ACCEPTED"


# --- Cohort 2: Multi-File Implementation ---

def test_cohort_2a_multi_file_discounts(b65_registry):
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "cohort" / "multi_file_repo"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"
        shutil.copytree(fixture_dir, repo_dir)

        engine = WorkflowEngine(tmp_path / "engine.sqlite")
        store = ArtifactStore(tmp_path / "artifacts")
        adapter = HumanInterfaceAdapter(engine, store)

        patch = (
            "diff --git a/src/processor.py b/src/processor.py\n"
            "--- a/src/processor.py\n"
            "+++ b/src/processor.py\n"
            "@@ -12,2 +12,2 @@\n"
            "-    discounted_subtotal = subtotal + discount\n"
            "+    discounted_subtotal = subtotal - discount\n"
        )
        workers = {
            "worker-b65-0": MultiFileWorker("worker-b65-0", "prof-b65-0", store, patch_content=patch),
            "worker-b65-1": ReviewerWorker("worker-b65-1", "prof-b65-1", store),
        }

        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text="Implement tier discounts across processor and discounts modules",
            source_channel="cli",
            source_reference="cohort-2a",
            repository_id="multi_file_repo",
            baseline_commit="c-2a",
            proposed_mutation_paths=["src/processor.py", "src/discounts.py"],
            acceptance_criteria=[
                AcceptanceCriterion("c1", "Run pytest", "pytest", "tests/test_processor.py")
            ],
        )
        adapter.submit_work_order(wo)

        orch = OrchestratorControlPlane(
            admission_evaluator=AdmissionEvaluator(),
            planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="implementation"),
            router=CapabilityRouter(b65_registry),
            engine=engine,
            artifact_store=store,
            validator=IndependentValidator(store),
            repair_controller=BoundedRepairController(),
            workers=workers,
            baseline_repo_dir=repo_dir,
            enable_review_repair=True,
        )
        state = orch.execute_work_order(wo)
        assert state == WorkOrderState.ACCEPTED


def test_cohort_2b_multi_file_tax(b65_registry):
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "cohort" / "multi_file_tax_repo"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"
        shutil.copytree(fixture_dir, repo_dir)

        engine = WorkflowEngine(tmp_path / "engine.sqlite")
        store = ArtifactStore(tmp_path / "artifacts")
        adapter = HumanInterfaceAdapter(engine, store)

        patch = (
            "--- a/src/tax_calculator.py\n"
            "+++ b/src/tax_calculator.py\n"
            "@@ -14,7 +14,12 @@\n"
            "     - If amount < 0: raise ValueError(\"amount must be non-negative\")\n"
            "     - Return tax rounded to 2 decimal places.\n"
            "     \"\"\"\n"
            "-    # Skeleton placeholder - unhandled rates and missing negative validation\n"
            "     if amount < 0:\n"
            "         raise ValueError(\"amount must be non-negative\")\n"
            "-    return round(amount * 0.05, 2)\n"
            "+    rates = {\n"
            "+        \"CA\": 0.0825,\n"
            "+        \"NY\": 0.08,\n"
            "+        \"TX\": 0.0625,\n"
            "+    }\n"
            "+    rate = rates.get(state.upper(), 0.05)\n"
            "+    return round(amount * rate, 2)\n"
        )
        workers = {
            "worker-b65-0": MultiFileWorker("worker-b65-0", "prof-b65-0", store, patch_content=patch),
            "worker-b65-1": ReviewerWorker("worker-b65-1", "prof-b65-1", store),
        }

        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text="Implement state sales tax rates in tax_calculator",
            source_channel="cli",
            source_reference="cohort-2b",
            repository_id="multi_file_tax_repo",
            baseline_commit="c-2b",
            proposed_mutation_paths=["src/tax_calculator.py"],
            acceptance_criteria=[
                AcceptanceCriterion("c1", "Run pytest", "pytest", "tests/test_order_service.py")
            ],
        )
        adapter.submit_work_order(wo)

        orch = OrchestratorControlPlane(
            admission_evaluator=AdmissionEvaluator(),
            planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="implementation"),
            router=CapabilityRouter(b65_registry),
            engine=engine,
            artifact_store=store,
            validator=IndependentValidator(store),
            repair_controller=BoundedRepairController(),
            workers=workers,
            baseline_repo_dir=repo_dir,
            enable_review_repair=True,
        )
        state = orch.execute_work_order(wo)
        assert state == WorkOrderState.ACCEPTED


# --- Cohort 3: Meaningful Test Development ---

def test_cohort_3a_test_dev_token(b65_registry):
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "cohort" / "test_dev_repo"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"
        shutil.copytree(fixture_dir, repo_dir)

        engine = WorkflowEngine(tmp_path / "engine.sqlite")
        store = ArtifactStore(tmp_path / "artifacts")
        adapter = HumanInterfaceAdapter(engine, store)

        test_patch = (
            "--- /dev/null\n"
            "+++ b/tests/test_token_utils.py\n"
            "@@ -0,0 +1,22 @@\n"
            "+from src.token_utils import validate_bearer_token\n"
            "+\n"
            "+\n"
            "+def test_valid_token():\n"
            "+    assert validate_bearer_token('Bearer abc123xyz') == 'abc123xyz'\n"
            "+\n"
            "+\n"
            "+def test_invalid_prefix():\n"
            "+    assert validate_bearer_token('Basic abc123xyz') is None\n"
            "+    assert validate_bearer_token('bearer abc123xyz') is None\n"
            "+\n"
            "+\n"
            "+def test_empty_or_whitespace():\n"
            "+    assert validate_bearer_token(None) is None\n"
            "+    assert validate_bearer_token('') is None\n"
            "+    assert validate_bearer_token('Bearer ') is None\n"
            "+    assert validate_bearer_token('Bearer    ') is None\n"
            "+\n"
            "+\n"
            "+def test_internal_whitespace():\n"
            "+    assert validate_bearer_token('Bearer abc 123') is None\n"
            "+    assert validate_bearer_token('Bearer abc\\n123') is None\n"
        )
        workers = {
            "worker-b65-0": TestDevWorker("worker-b65-0", "prof-b65-0", store, patch_content=test_patch),
            "worker-b65-1": ReviewerWorker("worker-b65-1", "prof-b65-1", store),
        }

        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text="Author meaningful unit tests for token_utils",
            source_channel="cli",
            source_reference="cohort-3a",
            repository_id="test_dev_repo",
            baseline_commit="c-3a",
            proposed_mutation_paths=["tests/test_token_utils.py"],
            acceptance_criteria=[
                AcceptanceCriterion("c1", "Run pytest", "pytest", "tests/test_token_utils.py")
            ],
        )
        adapter.submit_work_order(wo)

        orch = OrchestratorControlPlane(
            admission_evaluator=AdmissionEvaluator(),
            planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="test_development"),
            router=CapabilityRouter(b65_registry),
            engine=engine,
            artifact_store=store,
            validator=IndependentValidator(store),
            repair_controller=BoundedRepairController(),
            workers=workers,
            baseline_repo_dir=repo_dir,
            enable_review_repair=True,
        )
        state = orch.execute_work_order(wo)
        assert state == WorkOrderState.ACCEPTED


def test_cohort_3b_test_dev_auth_jwt(b65_registry):
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "cohort" / "test_dev_auth_repo"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"
        shutil.copytree(fixture_dir, repo_dir)

        engine = WorkflowEngine(tmp_path / "engine.sqlite")
        store = ArtifactStore(tmp_path / "artifacts")
        adapter = HumanInterfaceAdapter(engine, store)

        test_patch = (
            "--- /dev/null\n"
            "+++ b/tests/test_auth_jwt.py\n"
            "@@ -0,0 +1,27 @@\n"
            "+import pytest\n"
            "+import time\n"
            "+from src.auth_jwt import generate_token, verify_token\n"
            "+\n"
            "+def test_token_generation_and_verification():\n"
            "+    secret = \"super-secret-key\"\n"
            "+    claims = {\"sub\": \"user_123\", \"role\": \"admin\"}\n"
            "+    token = generate_token(claims, secret, ttl_seconds=3600)\n"
            "+    decoded = verify_token(token, secret)\n"
            "+    assert decoded[\"sub\"] == \"user_123\"\n"
            "+    assert decoded[\"role\"] == \"admin\"\n"
            "+    assert \"iat\" in decoded\n"
            "+    assert \"exp\" in decoded\n"
            "+\n"
            "+def test_tampered_token_rejected():\n"
            "+    secret = \"super-secret-key\"\n"
            "+    token = generate_token({\"sub\": \"user_1\"}, secret)\n"
            "+    parts = token.split(\".\")\n"
            "+    tampered = f\"{parts[0]}.eyJhZG1pbiI6dHJ1ZX0.{parts[2]}\"\n"
            "+    with pytest.raises(ValueError, match=\"Signature verification failed\"):\n"
            "+        verify_token(tampered, secret)\n"
            "+\n"
            "+def test_expired_token_rejected():\n"
            "+    secret = \"super-secret-key\"\n"
            "+    token = generate_token({\"sub\": \"user_1\"}, secret, ttl_seconds=-10)\n"
            "+    with pytest.raises(ValueError, match=\"Token expired\"):\n"
            "+        verify_token(token, secret)\n"
        )
        workers = {
            "worker-b65-0": TestDevWorker("worker-b65-0", "prof-b65-0", store, patch_content=test_patch),
            "worker-b65-1": ReviewerWorker("worker-b65-1", "prof-b65-1", store),
        }

        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text="Author meaningful unit tests for HMAC JWT verification",
            source_channel="cli",
            source_reference="cohort-3b",
            repository_id="test_dev_auth_repo",
            baseline_commit="c-3b",
            proposed_mutation_paths=["tests/test_auth_jwt.py"],
            acceptance_criteria=[
                AcceptanceCriterion("c1", "Run pytest", "pytest", "tests/test_auth_jwt.py")
            ],
        )
        adapter.submit_work_order(wo)

        orch = OrchestratorControlPlane(
            admission_evaluator=AdmissionEvaluator(),
            planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="test_development"),
            router=CapabilityRouter(b65_registry),
            engine=engine,
            artifact_store=store,
            validator=IndependentValidator(store),
            repair_controller=BoundedRepairController(),
            workers=workers,
            baseline_repo_dir=repo_dir,
            enable_review_repair=True,
        )
        state = orch.execute_work_order(wo)
        assert state == WorkOrderState.ACCEPTED


# --- Cohort 4: Maintainability & Deduplication ---

def test_cohort_4a_maintainability_currency(b65_registry):
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "cohort" / "maintainability_repo"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"
        shutil.copytree(fixture_dir, repo_dir)

        engine = WorkflowEngine(tmp_path / "engine.sqlite")
        store = ArtifactStore(tmp_path / "artifacts")
        adapter = HumanInterfaceAdapter(engine, store)

        workers = {
            "worker-b65-0": RefactorWorker("worker-b65-0", "prof-b65-0", store),
            "worker-b65-1": ReviewerWorker("worker-b65-1", "prof-b65-1", store),
        }

        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text="Deduplicate currency formatters without behavior regression",
            source_channel="cli",
            source_reference="cohort-4a",
            repository_id="maintainability_repo",
            baseline_commit="c-4a",
            proposed_mutation_paths=["src/currency_formatters.py"],
            acceptance_criteria=[
                AcceptanceCriterion("c1", "Run pytest", "pytest", "tests/test_currency_formatters.py")
            ],
        )
        adapter.submit_work_order(wo)

        orch = OrchestratorControlPlane(
            admission_evaluator=AdmissionEvaluator(),
            planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="maintainability_refactor"),
            router=CapabilityRouter(b65_registry),
            engine=engine,
            artifact_store=store,
            validator=IndependentValidator(store),
            repair_controller=BoundedRepairController(),
            workers=workers,
            baseline_repo_dir=repo_dir,
            enable_review_repair=True,
        )
        state = orch.execute_work_order(wo)
        assert state == WorkOrderState.ACCEPTED


def test_cohort_4b_maintainability_config(b65_registry):
    fixture_dir = Path(__file__).parent.parent / "fixtures" / "cohort" / "maintainability_config_repo"
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        repo_dir = tmp_path / "repo"
        shutil.copytree(fixture_dir, repo_dir)

        engine = WorkflowEngine(tmp_path / "engine.sqlite")
        store = ArtifactStore(tmp_path / "artifacts")
        adapter = HumanInterfaceAdapter(engine, store)

        patch = (
            "--- a/src/config_loader.py\n"
            "+++ b/src/config_loader.py\n"
            "@@ -3,85 +3,54 @@\n"
            " from typing import Any\n"
            " \n"
            " \n"
            "+def _parse_env_field(source: dict[str, str], prefix: str, field: str, default: Any, val_type: type) -> Any:\n"
            "+    env_key = f\"{prefix}_{field.upper()}\"\n"
            "+    raw = source.get(env_key)\n"
            "+    if raw is None:\n"
            "+        return default\n"
            "+    if val_type is bool:\n"
            "+        return raw.lower() in (\"true\", \"1\", \"yes\")\n"
            "+    elif val_type is int:\n"
            "+        try:\n"
            "+            return int(raw)\n"
            "+        except ValueError:\n"
            "+            raise ValueError(f\"Invalid integer value for {env_key}: {raw}\")\n"
            "+    elif val_type is float:\n"
            "+        try:\n"
            "+            return float(raw)\n"
            "+        except ValueError:\n"
            "+            raise ValueError(f\"Invalid float value for {env_key}: {raw}\")\n"
            "+    return raw\n"
            "+\n"
            "+\n"
            " def load_database_config(env: dict[str, str] | None = None) -> dict[str, Any]:\n"
            "     \"\"\"Loads database settings from environment with type conversions and defaults.\"\"\"\n"
            "     source = env if env is not None else os.environ\n"
            "-\n"
            "-    host = source.get(\"DB_HOST\", \"localhost\")\n"
            "-    raw_port = source.get(\"DB_PORT\", \"5432\")\n"
            "-    try:\n"
            "-        port = int(raw_port)\n"
            "-    except ValueError:\n"
            "-        raise ValueError(f\"Invalid integer value for DB_PORT: {raw_port}\")\n"
            "-\n"
            "-    raw_timeout = source.get(\"DB_TIMEOUT\", \"30.0\")\n"
            "-    try:\n"
            "-        timeout = float(raw_timeout)\n"
            "-    except ValueError:\n"
            "-        raise ValueError(f\"Invalid float value for DB_TIMEOUT: {raw_timeout}\")\n"
            "-\n"
            "-    raw_ssl = source.get(\"DB_SSL\", \"false\").lower()\n"
            "-    ssl = raw_ssl in (\"true\", \"1\", \"yes\")\n"
            "-\n"
            "     return {\n"
            "-        \"host\": host,\n"
            "-        \"port\": port,\n"
            "-        \"timeout\": timeout,\n"
            "-        \"ssl\": ssl,\n"
            "+        \"host\": _parse_env_field(source, \"DB\", \"host\", \"localhost\", str),\n"
            "+        \"port\": _parse_env_field(source, \"DB\", \"port\", 5432, int),\n"
            "+        \"timeout\": _parse_env_field(source, \"DB\", \"timeout\", 30.0, float),\n"
            "+        \"ssl\": _parse_env_field(source, \"DB\", \"ssl\", False, bool),\n"
            "     }\n"
            " \n"
            " \n"
            " def load_cache_config(env: dict[str, str] | None = None) -> dict[str, Any]:\n"
            "     \"\"\"Loads cache settings from environment with duplicate type conversions and defaults.\"\"\"\n"
            "     source = env if env is not None else os.environ\n"
            "-\n"
            "-    host = source.get(\"CACHE_HOST\", \"localhost\")\n"
            "-    raw_port = source.get(\"CACHE_PORT\", \"6379\")\n"
            "-    try:\n"
            "-        port = int(raw_port)\n"
            "-    except ValueError:\n"
            "-        raise ValueError(f\"Invalid integer value for CACHE_PORT: {raw_port}\")\n"
            "-\n"
            "-    raw_timeout = source.get(\"CACHE_TIMEOUT\", \"5.0\")\n"
            "-    try:\n"
            "-        timeout = float(raw_timeout)\n"
            "-    except ValueError:\n"
            "-        raise ValueError(f\"Invalid float value for CACHE_TIMEOUT: {raw_timeout}\")\n"
            "-\n"
            "-    raw_ssl = source.get(\"CACHE_SSL\", \"false\").lower()\n"
            "-    ssl = raw_ssl in (\"true\", \"1\", \"yes\")\n"
            "-\n"
            "     return {\n"
            "-        \"host\": host,\n"
            "-        \"port\": port,\n"
            "-        \"timeout\": timeout,\n"
            "-        \"ssl\": ssl,\n"
            "+        \"host\": _parse_env_field(source, \"CACHE\", \"host\", \"localhost\", str),\n"
            "+        \"port\": _parse_env_field(source, \"CACHE\", \"port\", 6379, int),\n"
            "+        \"timeout\": _parse_env_field(source, \"CACHE\", \"timeout\", 5.0, float),\n"
            "+        \"ssl\": _parse_env_field(source, \"CACHE\", \"ssl\", False, bool),\n"
            "     }\n"
            " \n"
            " \n"
            " def load_auth_config(env: dict[str, str] | None = None) -> dict[str, Any]:\n"
            "     \"\"\"Loads authentication settings from environment with duplicate type conversions.\"\"\"\n"
            "     source = env if env is not None else os.environ\n"
            "-\n"
            "-    host = source.get(\"AUTH_HOST\", \"auth.local\")\n"
            "-    raw_port = source.get(\"AUTH_PORT\", \"8080\")\n"
            "-    try:\n"
            "-        port = int(raw_port)\n"
            "-    except ValueError:\n"
            "-        raise ValueError(f\"Invalid integer value for AUTH_PORT: {raw_port}\")\n"
            "-\n"
            "-    raw_timeout = source.get(\"AUTH_TIMEOUT\", \"10.0\")\n"
            "-    try:\n"
            "-        timeout = float(raw_timeout)\n"
            "-    except ValueError:\n"
            "-        raise ValueError(f\"Invalid float value for AUTH_TIMEOUT: {raw_timeout}\")\n"
            "-\n"
            "-    raw_ssl = source.get(\"AUTH_SSL\", \"true\").lower()\n"
            "-    ssl = raw_ssl in (\"true\", \"1\", \"yes\")\n"
            "-\n"
            "     return {\n"
            "-        \"host\": host,\n"
            "-        \"port\": port,\n"
            "-        \"timeout\": timeout,\n"
            "-        \"ssl\": ssl,\n"
            "+        \"host\": _parse_env_field(source, \"AUTH\", \"host\", \"auth.local\", str),\n"
            "+        \"port\": _parse_env_field(source, \"AUTH\", \"port\", 8080, int),\n"
            "+        \"timeout\": _parse_env_field(source, \"AUTH\", \"timeout\", 10.0, float),\n"
            "+        \"ssl\": _parse_env_field(source, \"AUTH\", \"ssl\", True, bool),\n"
            "     }\n"
        )
        workers = {
            "worker-b65-0": RefactorWorker("worker-b65-0", "prof-b65-0", store, patch_content=patch),
            "worker-b65-1": ReviewerWorker("worker-b65-1", "prof-b65-1", store),
        }

        compiler = WorkOrderCompiler()
        wo = compiler.compile(
            raw_text="Deduplicate environment variable config parsing without regressions",
            source_channel="cli",
            source_reference="cohort-4b",
            repository_id="maintainability_config_repo",
            baseline_commit="c-4b",
            proposed_mutation_paths=["src/config_loader.py"],
            acceptance_criteria=[
                AcceptanceCriterion("c1", "Run pytest", "pytest", "tests/test_config_loader.py")
            ],
        )
        adapter.submit_work_order(wo)

        orch = OrchestratorControlPlane(
            admission_evaluator=AdmissionEvaluator(),
            planner=ExecutionPlanner(include_investigation=False, include_review=True, primary_role="maintainability_refactor"),
            router=CapabilityRouter(b65_registry),
            engine=engine,
            artifact_store=store,
            validator=IndependentValidator(store),
            repair_controller=BoundedRepairController(),
            workers=workers,
            baseline_repo_dir=repo_dir,
            enable_review_repair=True,
        )
        state = orch.execute_work_order(wo)
        assert state == WorkOrderState.ACCEPTED

