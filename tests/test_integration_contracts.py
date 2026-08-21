from __future__ import annotations

import json
from pathlib import Path
import pytest
import jsonschema
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
CMDB_SCHEMA_PATH = REPO_ROOT / "schemas/cmdb.schema.json"
ITSM_SCHEMA_PATH = REPO_ROOT / "schemas/itsm.schema.json"


def load_yaml(relpath: str) -> object:
    return yaml.safe_load((REPO_ROOT / relpath).read_text(encoding="utf-8"))


def test_cmdb_schema_valid_export():
    schema = json.loads(CMDB_SCHEMA_PATH.read_text(encoding="utf-8"))
    export_data = {
        "schema_version": "1.0.0",
        "generated_at": "2026-08-21T12:00:00Z",
        "git_sha": "0123456789abcdef0123456789abcdef01234567",
        "simulated": True,
        "status": "VALIDATED",
        "node": {
            "node_id": "ai-p620-01",
            "hostname": "ai-p620-01",
            "environment": "production",
        },
        "configuration_item": {
            "expected": {
                "ci_id": "ci-p620-01",
                "ci_type": "NODE",
                "hardware_profile": "p620_dual_b65",
                "capabilities": {
                    "gpu": True,
                    "inference": True,
                    "benchmarking": True,
                    "monitoring": True,
                    "cluster_eligible": True,
                },
                "cluster_membership": {
                    "name": None,
                    "membership_state": "standalone",
                    "node_role": "primary",
                    "roles": {"worker": False, "api": False, "scheduler": False, "storage": False},
                },
                "runtime_versions": {
                    "intel_runtime": "26.27.39122.11",
                    "level_zero": "1.17.6",
                    "pytorch": "2.12.1+xpu",
                    "vllm": "0.7.3",
                    "llama_commit": "b374829a435fa848d7c1775efd2dfbfb87fcf1e2",
                },
            },
            "observed": {
                "ci_id": "ci-p620-01",
                "ci_type": "NODE",
                "hardware_profile": "p620_dual_b65",
                "capabilities": {
                    "gpu": True,
                    "inference": True,
                    "benchmarking": True,
                    "monitoring": True,
                    "cluster_eligible": True,
                },
                "cluster_membership": {
                    "name": None,
                    "membership_state": "standalone",
                    "node_role": "primary",
                    "roles": {"worker": False, "api": False, "scheduler": False, "storage": False},
                },
                "runtime_versions": {
                    "intel_runtime": "26.27.39122.11",
                    "level_zero": "1.17.6",
                    "pytorch": "2.12.1+xpu",
                    "vllm": "0.7.3",
                    "llama_commit": "b374829a435fa848d7c1775efd2dfbfb87fcf1e2",
                },
            },
        },
        "relationships": [],
        "last_convergence_at": "2026-08-21T12:00:00Z",
        "last_validation_at": "2026-08-21T12:00:00Z",
    }
    jsonschema.validate(instance=export_data, schema=schema)


def test_itsm_schema_valid_envelope():
    schema = json.loads(ITSM_SCHEMA_PATH.read_text(encoding="utf-8"))
    envelope = {
        "schema_version": "1.0.0",
        "generated_at": "2026-08-21T12:00:00Z",
        "git_sha": "0123456789abcdef0123456789abcdef01234567",
        "simulated": True,
        "status": "IMPLEMENTED",
        "adapter": "servicenow_generic",
        "change_id": "CHG0012345",
        "request_id": "REQ0054321",
        "affected_ci_ids": ["ci-p620-01"],
        "risk": "MEDIUM",
        "approval_state": "APPROVED",
        "maintenance_window": {
            "start": "2026-08-21T00:00:00Z",
            "end": "2026-08-21T23:59:59Z",
        },
        "permitted_actions": ["RECONCILE", "VALIDATE"],
        "selected_action": "RECONCILE",
        "executed_action": "RECONCILE",
        "rollback_reference": "commit:previous_sha",
        "execution_result": {
            "expected": {"status": "PASS", "summary": "Reconciliation successful"},
            "observed": {"status": "PASS", "summary": "Reconciliation successful"},
        },
        "validation_result": {
            "expected": {"status": "PASS", "summary": "Validation passed"},
            "observed": {"status": "PASS", "summary": "Validation passed"},
        },
    }
    jsonschema.validate(instance=envelope, schema=schema)


def test_facts_export_playbook_structure():
    content = (REPO_ROOT / "playbooks/facts-export.yml").read_text()
    assert "facts-export" in content or "cmdb_export" in content
