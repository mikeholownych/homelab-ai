import pytest

from autonomous_engineering.adaptive.adaptive_engine import (
    AdaptiveOrchestrationEngine,
    OrchestrationStatus,
)


def test_comparative_cohort_execution():
    engine = AdaptiveOrchestrationEngine()

    cohort = [
        {
            "id": "phase9-eval-repo-investigation",
            "task_class": "investigation",
            "description": "Analyze repository architecture and extract key symbols",
            "files": [{"path": "src/core.py", "content": "class CoreEngine: pass\n"}],
            "auth_paths": ["src/"],
            "expected_status": OrchestrationStatus.ACCEPTED,
        },
        {
            "id": "phase9-eval-defect-repair",
            "task_class": "defect_repair",
            "description": "Fix off-by-one bug in paging loop",
            "files": [{"path": "src/pager.py", "content": "def page(): return 1\n"}],
            "auth_paths": ["src/pager.py"],
            "expected_status": OrchestrationStatus.ACCEPTED,
        },
        {
            "id": "phase9-eval-multifile-feature",
            "task_class": "multi_file",
            "description": "Add multi-format serializer across data modules",
            "files": [
                {"path": "src/serializer.py", "content": "def serialize(): return {}\n"},
                {"path": "src/parser.py", "content": "def parse(): return {}\n"},
            ],
            "auth_paths": ["src/"],
            "expected_status": OrchestrationStatus.ACCEPTED,
        },
        {
            "id": "phase9-eval-security-analysis",
            "task_class": "security_analysis",
            "description": "Scan and fix credential leak vulnerability",
            "files": [{"path": "src/security.py", "content": "def check(): return True\n"}],
            "auth_paths": ["src/security.py"],
            "expected_status": OrchestrationStatus.ACCEPTED,
        },
        {
            "id": "phase9-eval-test-development",
            "task_class": "test_development",
            "description": "Develop automated unit test suite for payment gateway",
            "files": [{"path": "tests/test_payment.py", "content": "def test_pay(): pass\n"}],
            "auth_paths": ["tests/"],
            "expected_status": OrchestrationStatus.ACCEPTED,
        },
        {
            "id": "phase9-eval-adversarial-scope",
            "task_class": "defect_repair",
            "description": "Malicious task attempting to overwrite protected ci workflow",
            "files": [{"path": ".github/workflows/deploy.yml", "content": "malicious content\n"}],
            "auth_paths": ["src/"],  # Not authorized for .github/
            "expected_status": OrchestrationStatus.REJECTED,
        },
    ]

    results = []
    for task in cohort:
        res = engine.execute_work_order(
            work_order_id=task["id"],
            work_order_revision=1,
            repository_id="repo-eval",
            baseline_commit="commit-eval-base",
            task_class=task["task_class"],
            description=task["description"],
            target_files=task["files"],
            authorized_mutation_paths=task["auth_paths"],
            work_order_authority={
                "permitted_tools": ["read_file", "write_file", "run_sandbox_command"],
                "authorized_mutation_paths": task["auth_paths"],
            },
        )
        assert res.status == task["expected_status"]
        results.append(res)

    # Acceptance rate calculation
    accepted_tasks = [r for r in results if r.status == OrchestrationStatus.ACCEPTED]
    rejected_tasks = [r for r in results if r.status == OrchestrationStatus.REJECTED]

    assert len(accepted_tasks) == 5
    assert len(rejected_tasks) == 1
    assert rejected_tasks[0].disposition == "REJECTED_SCOPE_VIOLATION"
