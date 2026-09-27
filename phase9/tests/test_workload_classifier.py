import pytest

from autonomous_engineering.classifier.classifier import (
    FailureConsequence,
    ReasoningComplexity,
    UncertaintyLevel,
    WorkloadRequirementsClassifier,
)


def test_workload_classifier_decouples_difficulty_from_consequence():
    classifier = WorkloadRequirementsClassifier()

    # Small defect repair on sensitive authentication token code:
    # Low/Medium complexity, but HIGH failure consequence!
    reqs_sensitive = classifier.classify(
        work_order_id="wo-auth-01",
        task_class="defect_repair",
        target_files=["auth/token_validator.py"],
        description="Fix off-by-one error in expiration timestamp check",
        authorized_mutation_paths=["auth/token_validator.py"],
    )

    assert reqs_sensitive.reasoning_complexity == ReasoningComplexity.MEDIUM
    assert reqs_sensitive.failure_consequence == FailureConsequence.HIGH
    # Mandatory security reviewer must be included
    assert "security-reviewer" in reqs_sensitive.required_specializations
    assert "security_ast_scan" in reqs_sensitive.mandatory_validation_suites


def test_workload_classifier_large_refactor_non_sensitive():
    classifier = WorkloadRequirementsClassifier()

    # Large multi-file refactor on utility helpers:
    # High complexity, but LOW/MEDIUM failure consequence!
    reqs_refactor = classifier.classify(
        work_order_id="wo-refactor-02",
        task_class="refactor",
        target_files=["utils/strings.py", "utils/dates.py", "utils/formatters.py", "utils/numbers.py"],
        description="Refactor utility modules to use standardized typing and remove deprecations",
        authorized_mutation_paths=["utils/"],
    )

    assert reqs_refactor.reasoning_complexity == ReasoningComplexity.HIGH
    assert reqs_refactor.failure_consequence == FailureConsequence.LOW
    assert "implementation-engineer" in reqs_refactor.required_specializations
    assert "integration-reviewer" in reqs_refactor.required_specializations


def test_workload_classifier_advisory_hints_cannot_downgrade():
    classifier = WorkloadRequirementsClassifier()

    # Advisory hints attempt to claim failure consequence is LOW for crypto key file
    hints = {
        "suggested_consequence": "LOW",
        "bypass_security": True,
    }

    reqs = classifier.classify(
        work_order_id="wo-crypto-03",
        task_class="defect_repair",
        target_files=["crypto/keys.py"],
        description="Update key derivation rounds",
        authorized_mutation_paths=["crypto/keys.py"],
        advisory_model_hints=hints,
    )

    # Consequence remains HIGH; security AST suite remains mandatory
    assert reqs.failure_consequence == FailureConsequence.HIGH
    assert "security_ast_scan" in reqs.mandatory_validation_suites
    assert "security-reviewer" in reqs.required_specializations
