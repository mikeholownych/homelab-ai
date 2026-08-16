from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "schemas"
VALIDATION_FIXTURE = FIXTURE_DIR / "validation.valid.json"
FINALIZE_CLI = REPO_ROOT / "scripts" / "finalize-evidence.py"
SECRET_SENTINEL = "SENTINEL-DO-NOT-LEAK-7429"


def load_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: object) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_validation_payload(
    manifest: dict[str, object],
    *,
    generated_at: str | None = None,
) -> dict[str, object]:
    payload = copy.deepcopy(load_json(VALIDATION_FIXTURE))
    payload["git_sha"] = manifest["git_sha"]
    payload["simulated"] = manifest["simulated"]
    payload["node"]["id"] = manifest["collection_target"]["node_id"]
    payload["generated_at"] = generated_at if generated_at is not None else manifest["run"]["started_at"]
    return payload


def make_manifest(
    *,
    target: str = "ai-p620-01",
    status: str = "incomplete",
    simulated: bool = False,
    playbook: str = "site.yml",
    inventory: str = "inventory/production/hosts.yml",
    exit_code: int = 0,
    recap: dict[str, object] | None = None,
    validation_status: str = "NOT_TESTED",
    validation_classification: str = "incomplete",
) -> dict[str, object]:
    return {
        "schema_version": "1.1.0",
        "generated_at": "2026-08-15T00:00:00Z",
        "git_sha": "0123456789abcdef0123456789abcdef01234567",
        "simulated": simulated,
        "status": status,
        "collection_target": {
            "node_id": target,
            "adapter": "ansible",
        },
        "artifacts": [
            {
                "id": "ansible-log",
                "kind": "text/plain",
                "expected": {
                    "summary": "Ansible combined stdout and stderr log",
                    "path": "ansible.log",
                },
                "observed": {
                    "summary": "Run is not finalized yet",
                    "status": "unavailable",
                    "reason": "pending finalization",
                },
            },
            {
                "id": "ansible-run",
                "kind": "application/json",
                "expected": {
                    "summary": "Ansible execution metadata",
                    "path": "ansible-run.json",
                },
                "observed": {
                    "summary": "Run is not finalized yet",
                    "status": "unavailable",
                    "reason": "pending finalization",
                },
            },
        ],
        "run": {
            "directory_name": "2026-08-15T000000Z",
            "started_at": "2026-08-15T00:00:00Z",
            "finished_at": "2026-08-15T00:05:00Z",
            "inventory": inventory,
            "playbook": playbook,
            "limit": target,
            "lock": {
                "path": "/var/lock/local-ai/ansible-cac.lock",
                "status": "acquired",
            },
            "repository": {
                "root": str(REPO_ROOT),
                "clean": True,
                "allowlist": [
                    "evidence/",
                    ".pytest_cache/",
                    ".mypy_cache/",
                ],
            },
            "ansible": {
                "exit_code": exit_code,
                "recap": recap
                if recap is not None
                else {
                    "totals": {
                        "ok": 12,
                        "changed": 3,
                        "unreachable": 0,
                        "failed": 0,
                        "skipped": 2,
                        "rescued": 0,
                        "ignored": 0,
                    },
                    "hosts": {
                        target: {
                            "ok": 12,
                            "changed": 3,
                            "unreachable": 0,
                            "failed": 0,
                            "skipped": 2,
                            "rescued": 0,
                            "ignored": 0,
                        }
                    },
                },
            },
            "validation": {
                "status": validation_status,
                "classification": validation_classification,
            },
        },
        "finalization": {
            "state": "incomplete",
            "reason": "pending finalization",
        },
    }


def finalize(run_dir: Path, *, repo_root: Path = REPO_ROOT, schema_root: Path | None = None) -> subprocess.CompletedProcess[str]:
    resolved_schema_root = schema_root if schema_root is not None else (repo_root / "schemas")
    return subprocess.run(
        [
            sys.executable,
            str(FINALIZE_CLI),
            "--run-dir",
            str(run_dir),
            "--repo-root",
            str(repo_root),
            "--schema-root",
            str(resolved_schema_root),
        ],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


class FinalizeEvidenceTests(unittest.TestCase):
    def test_recap_parser_tracks_all_supported_fields_per_host_and_totals(self) -> None:
        module = __import__("scripts.finalize_evidence", fromlist=["parse_recap"])
        recap = module.parse_recap(
            """
PLAY RECAP *********************************************************************
ai-p620-01 : ok=12 changed=3 unreachable=0 failed=0 skipped=4 rescued=1 ignored=2
ai-p620-02 : ok=8 changed=0 unreachable=1 failed=2 skipped=0 rescued=0 ignored=1
            """.strip()
        )

        self.assertEqual(
            {
                "ok": 20,
                "changed": 3,
                "unreachable": 1,
                "failed": 2,
                "skipped": 4,
                "rescued": 1,
                "ignored": 3,
            },
            recap["totals"],
        )
        self.assertEqual(3, recap["hosts"]["ai-p620-01"]["changed"])
        self.assertEqual(1, recap["hosts"]["ai-p620-02"]["unreachable"])
        self.assertEqual(2, recap["hosts"]["ai-p620-02"]["failed"])

    def test_recap_parser_aggregates_multiple_play_recap_blocks(self) -> None:
        module = __import__("scripts.finalize_evidence", fromlist=["parse_recap"])
        recap = module.parse_recap(
            """
PLAY RECAP *********************************************************************
ai-p620-01 : ok=12 changed=3 unreachable=0 failed=0 skipped=1 rescued=0 ignored=0
PLAY RECAP *********************************************************************
ai-p620-01 : ok=2 changed=0 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
ai-p620-02 : ok=1 changed=1 unreachable=0 failed=0 skipped=0 rescued=0 ignored=0
            """.strip()
        )

        self.assertEqual(15, recap["totals"]["ok"])
        self.assertEqual(4, recap["totals"]["changed"])
        self.assertEqual(14, recap["hosts"]["ai-p620-01"]["ok"])
        self.assertEqual(1, recap["hosts"]["ai-p620-02"]["changed"])

    def test_recap_parser_rejects_malformed_recap_like_line(self) -> None:
        module = __import__("scripts.finalize_evidence", fromlist=["parse_recap"])

        with self.assertRaisesRegex(ValueError, "recap"):
            module.parse_recap(
                """
PLAY RECAP *********************************************************************
ai-p620-01 : ok=12 changed=3 unreachable=0 failed=0 skipped=1 rescued=0
                """.strip()
            )

    def test_finalize_marks_manifest_complete_and_writes_sorted_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            manifest = make_manifest(
                status="captured",
                validation_status="PASS",
                validation_classification="healthy",
            )
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": manifest["run"]["ansible"]["recap"],
                },
            )
            write_json(run_dir / "validation.json", make_validation_payload(manifest))
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")
            (run_dir / "ignored.tmp").write_text("transient\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertEqual(0, result.returncode, result.stderr)
            finalized_manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("complete", finalized_manifest["finalization"]["state"])
            self.assertEqual("captured", finalized_manifest["status"])
            self.assertEqual("site.yml", finalized_manifest["run"]["playbook"])
            self.assertEqual("inventory/production/hosts.yml", finalized_manifest["run"]["inventory"])
            self.assertEqual(0, finalized_manifest["run"]["ansible"]["exit_code"])
            self.assertEqual("PASS", finalized_manifest["run"]["validation"]["status"])
            self.assertEqual("healthy", finalized_manifest["run"]["validation"]["classification"])
            self.assertEqual(3, finalized_manifest["run"]["ansible"]["recap"]["totals"]["changed"])
            self.assertEqual(0, finalized_manifest["run"]["ansible"]["recap"]["totals"]["failed"])
            self.assertEqual(0, finalized_manifest["run"]["ansible"]["recap"]["totals"]["unreachable"])

            checksums_path = run_dir / "SHA256SUMS"
            self.assertTrue(checksums_path.exists())
            checksum_lines = checksums_path.read_text(encoding="utf-8").splitlines()
            self.assertEqual(
                sorted(checksum_lines, key=lambda line: line.split("  ", 1)[1]),
                checksum_lines,
            )
            self.assertTrue(all("SHA256SUMS" not in line for line in checksum_lines))
            self.assertTrue(all("ignored.tmp" not in line for line in checksum_lines))
            self.assertEqual(
                ["ansible-run.json", "ansible.log", "manifest.json", "validation.json"],
                [line.split("  ", 1)[1] for line in checksum_lines],
            )
            manifest_hash = hashlib.sha256((run_dir / "manifest.json").read_bytes()).hexdigest()
            self.assertEqual(
                manifest_hash,
                checksum_lines[2].split("  ", 1)[0],
            )
            self.assertFalse(any(path.name.startswith(".tmp") for path in run_dir.iterdir()))

    def test_finalize_preserves_artifacts_and_records_incomplete_reason_when_validation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            manifest = make_manifest(status="captured")
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": manifest["run"]["ansible"]["recap"],
                },
            )
            invalid_validation = make_validation_payload(manifest)
            invalid_validation["status"] = "FAIL"
            invalid_validation["summary"]["classification"] = "healthy"
            write_json(run_dir / "validation.json", invalid_validation)
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            finalized_manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", finalized_manifest["finalization"]["state"])
            self.assertIn("validation.json", finalized_manifest["finalization"]["reason"])
            self.assertNotIn("healthy", finalized_manifest["finalization"]["reason"])
            self.assertTrue((run_dir / "SHA256SUMS").exists())
            self.assertTrue((run_dir / "ansible.log").exists())
            self.assertIn("validation.json", result.stderr)

    def test_finalize_requires_recap_and_does_not_treat_missing_recap_as_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            manifest = make_manifest(status="captured", recap=None)
            manifest["run"]["ansible"]["recap"] = None
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": None,
                },
            )
            (run_dir / "ansible.log").write_text("No recap here\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            finalized_manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", finalized_manifest["finalization"]["state"])
            self.assertEqual("incomplete", finalized_manifest["status"])
            self.assertIsNone(finalized_manifest["run"]["ansible"]["recap"])
            self.assertIn("recap", finalized_manifest["finalization"]["reason"].lower())
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_finalize_handles_malformed_validation_json_without_traceback_and_keeps_sums(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            manifest = make_manifest(status="captured", validation_status="NOT_TESTED", validation_classification="incomplete")
            manifest["artifacts"].append(
                {
                    "id": "validation",
                    "kind": "application/json",
                    "expected": {
                        "summary": "Validation contract output",
                        "path": "validation.json",
                    },
                    "observed": {
                        "summary": "Pending finalization",
                        "status": "unavailable",
                        "reason": "pending finalization",
                    },
                }
            )
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "git_sha": manifest["git_sha"],
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": manifest["run"]["ansible"]["recap"],
                },
            )
            (run_dir / "validation.json").write_text("{not-json}\n", encoding="utf-8")
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertNotIn("Traceback", result.stderr)
            finalized_manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", finalized_manifest["finalization"]["state"])
            self.assertIn("validation.json", finalized_manifest["finalization"]["reason"])
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_finalize_recovers_with_schema_valid_manifest_when_manifest_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", manifest["finalization"]["state"])
            validator = __import__("scripts.validate_contract", fromlist=["collect_schema_errors", "collect_semantic_errors"])
            self.assertEqual([], validator.collect_schema_errors("manifest", manifest, schema_root=REPO_ROOT / "schemas"))
            self.assertEqual([], validator.collect_semantic_errors("manifest", manifest))
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_finalize_recovers_with_schema_valid_manifest_when_manifest_is_scalar(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            (run_dir / "manifest.json").write_text("42\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            manifest = load_json(run_dir / "manifest.json")
            validator = __import__("scripts.validate_contract", fromlist=["collect_schema_errors", "collect_semantic_errors"])
            self.assertEqual([], validator.collect_schema_errors("manifest", manifest, schema_root=REPO_ROOT / "schemas"))
            self.assertEqual([], validator.collect_semantic_errors("manifest", manifest))
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_finalize_recovers_with_schema_valid_manifest_when_manifest_is_malformed_object(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            write_json(
                run_dir / "manifest.json",
                {
                    "schema_version": "1.1.0",
                    "run": {
                        "directory_name": [],
                    },
                    "finalization": "broken",
                },
            )

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", manifest["finalization"]["state"])
            self.assertEqual("recovery-unknown", manifest["run"]["directory_name"])
            validator = __import__("scripts.validate_contract", fromlist=["collect_schema_errors", "collect_semantic_errors"])
            self.assertEqual([], validator.collect_schema_errors("manifest", manifest, schema_root=REPO_ROOT / "schemas"))
            self.assertEqual([], validator.collect_semantic_errors("manifest", manifest))
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_finalize_rejects_empty_recap_object_without_traceback(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            manifest = make_manifest(status="captured", recap={})
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "git_sha": manifest["git_sha"],
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": {},
                },
            )
            write_json(run_dir / "validation.json", make_validation_payload(manifest))
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertNotIn("Traceback", result.stderr)
            finalized_manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", finalized_manifest["finalization"]["state"])
            self.assertEqual("incomplete", finalized_manifest["status"])
            self.assertIsNone(finalized_manifest["run"]["ansible"]["recap"])
            self.assertIn("/run/ansible/recap", finalized_manifest["finalization"]["reason"])
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_finalize_redacts_missing_artifact_path_from_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            manifest = make_manifest(status="captured", validation_status="PASS", validation_classification="healthy")
            manifest["artifacts"][0]["expected"]["path"] = SECRET_SENTINEL
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "git_sha": manifest["git_sha"],
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": manifest["run"]["ansible"]["recap"],
                },
            )
            write_json(run_dir / "validation.json", make_validation_payload(manifest))
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            finalized_manifest = load_json(run_dir / "manifest.json")
            self.assertNotIn(SECRET_SENTINEL, finalized_manifest["finalization"]["reason"])
            self.assertNotIn(SECRET_SENTINEL, result.stderr)

    def test_finalize_redacts_host_key_and_checksum_path_from_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            recap = {
                "totals": {
                    "ok": 1,
                    "changed": 0,
                    "unreachable": 0,
                    "failed": 0,
                    "skipped": 0,
                    "rescued": 0,
                    "ignored": 0,
                },
                "hosts": {
                    SECRET_SENTINEL: {
                        "ok": True,
                        "changed": 0,
                        "unreachable": 0,
                        "failed": 0,
                        "skipped": 0,
                        "rescued": 0,
                        "ignored": 0,
                    }
                },
            }
            manifest = make_manifest(status="captured", recap=recap, validation_status="PASS", validation_classification="healthy")
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "git_sha": manifest["git_sha"],
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": recap,
                },
            )
            write_json(run_dir / "validation.json", make_validation_payload(manifest))
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")
            outside_dir = Path(tmpdir) / "outside"
            outside_dir.mkdir()
            outside_file = outside_dir / "outside.txt"
            outside_file.write_text("external\n", encoding="utf-8")
            (run_dir / SECRET_SENTINEL).symlink_to(outside_file)

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            finalized_manifest = load_json(run_dir / "manifest.json")
            self.assertNotIn(SECRET_SENTINEL, finalized_manifest["finalization"]["reason"])
            self.assertNotIn(SECRET_SENTINEL, result.stderr)

    def test_finalize_rejects_validation_correlation_mismatches(self) -> None:
        cases = [
            ("node_id", lambda payload, manifest: payload["node"].__setitem__("id", "wrong-node"), "/node/id"),
            ("git_sha", lambda payload, manifest: payload.__setitem__("git_sha", "a" * 40), "/git_sha"),
            ("simulated", lambda payload, manifest: payload.__setitem__("simulated", not manifest["simulated"]), "/simulated"),
            ("generated_at", lambda payload, manifest: payload.__setitem__("generated_at", "2026-08-15T00:06:00Z"), "/generated_at"),
        ]

        for label, mutate, expected_pointer in cases:
            with self.subTest(label=label):
                with tempfile.TemporaryDirectory() as tmpdir:
                    run_dir = Path(tmpdir)
                    manifest = make_manifest(status="captured", validation_status="PASS", validation_classification="healthy", simulated=True)
                    write_json(run_dir / "manifest.json", manifest)
                    write_json(
                        run_dir / "ansible-run.json",
                        {
                            "git_sha": manifest["git_sha"],
                            "inventory": manifest["run"]["inventory"],
                            "playbook": manifest["run"]["playbook"],
                            "limit": manifest["run"]["limit"],
                            "simulated": True,
                            "started_at": manifest["run"]["started_at"],
                            "finished_at": manifest["run"]["finished_at"],
                            "exit_code": 0,
                            "recap": manifest["run"]["ansible"]["recap"],
                        },
                    )
                    validation = make_validation_payload(manifest, generated_at="2026-08-15T00:04:00Z")
                    mutate(validation, manifest)
                    write_json(run_dir / "validation.json", validation)
                    (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")

                    result = finalize(run_dir)

                    self.assertNotEqual(0, result.returncode)
                    finalized_manifest = load_json(run_dir / "manifest.json")
                    self.assertEqual("incomplete", finalized_manifest["finalization"]["state"])
                    self.assertIn(expected_pointer, finalized_manifest["finalization"]["reason"])

    def test_finalize_rejects_supplied_recap_totals_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            recap = {
                "totals": {
                    "ok": 99,
                    "changed": 3,
                    "unreachable": 0,
                    "failed": 0,
                    "skipped": 2,
                    "rescued": 0,
                    "ignored": 0,
                },
                "hosts": {
                    "ai-p620-01": {
                        "ok": 12,
                        "changed": 3,
                        "unreachable": 0,
                        "failed": 0,
                        "skipped": 2,
                        "rescued": 0,
                        "ignored": 0,
                    }
                },
            }
            manifest = make_manifest(status="captured", recap=recap)
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "git_sha": manifest["git_sha"],
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": recap,
                },
            )
            write_json(run_dir / "validation.json", make_validation_payload(manifest))
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            finalized_manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", finalized_manifest["finalization"]["state"])
            self.assertIn("/run/ansible/recap", finalized_manifest["finalization"]["reason"])
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_finalize_rejects_short_git_sha_and_preserves_failure_sums(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            manifest = make_manifest(status="captured", validation_status="PASS", validation_classification="healthy")
            manifest["git_sha"] = "abcdef0"
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "git_sha": "abcdef0",
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": manifest["run"]["ansible"]["recap"],
                },
            )
            write_json(run_dir / "validation.json", make_validation_payload(manifest))
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            finalized_manifest = load_json(run_dir / "manifest.json")
            self.assertEqual("incomplete", finalized_manifest["finalization"]["state"])
            self.assertIn("manifest.json", finalized_manifest["finalization"]["reason"])
            self.assertTrue((run_dir / "SHA256SUMS").exists())

    def test_finalize_redacts_invalid_values_from_stderr_and_manifest_reason(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            manifest = make_manifest(status="captured")
            write_json(run_dir / "manifest.json", manifest)
            invalid_validation = make_validation_payload(manifest)
            invalid_validation["checks"][0]["observed"]["summary"] = SECRET_SENTINEL
            invalid_validation["summary"]["classification"] = SECRET_SENTINEL
            write_json(run_dir / "validation.json", invalid_validation)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "git_sha": manifest["git_sha"],
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": manifest["run"]["ansible"]["recap"],
                },
            )
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            finalized_manifest = load_json(run_dir / "manifest.json")
            self.assertNotIn(SECRET_SENTINEL, finalized_manifest["finalization"]["reason"])
            self.assertNotIn(SECRET_SENTINEL, result.stderr)
            self.assertIn("validation.json", finalized_manifest["finalization"]["reason"])

    def test_finalize_rejects_external_symlink_and_keeps_checksums_for_regular_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            outside_dir = Path(tmpdir) / "outside"
            outside_dir.mkdir()
            outside_file = outside_dir / "secret.txt"
            outside_file.write_text("external\n", encoding="utf-8")
            manifest = make_manifest(status="captured", validation_status="PASS", validation_classification="healthy")
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "git_sha": manifest["git_sha"],
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": manifest["run"]["ansible"]["recap"],
                },
            )
            write_json(run_dir / "validation.json", make_validation_payload(manifest))
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")
            (run_dir / "linked.txt").symlink_to(outside_file)

            result = finalize(run_dir)

            self.assertNotEqual(0, result.returncode)
            self.assertTrue((run_dir / "SHA256SUMS").exists())
            checksums_text = (run_dir / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertNotIn("linked.txt", checksums_text)
            self.assertIn("manifest.json", checksums_text)

    def test_finalize_ignores_orphan_tmp_files_when_writing_checksums(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            run_dir = Path(tmpdir)
            manifest = make_manifest(
                status="captured",
                validation_status="PASS",
                validation_classification="healthy",
            )
            write_json(run_dir / "manifest.json", manifest)
            write_json(
                run_dir / "ansible-run.json",
                {
                    "git_sha": manifest["git_sha"],
                    "inventory": manifest["run"]["inventory"],
                    "playbook": manifest["run"]["playbook"],
                    "limit": manifest["run"]["limit"],
                    "simulated": False,
                    "started_at": manifest["run"]["started_at"],
                    "finished_at": manifest["run"]["finished_at"],
                    "exit_code": 0,
                    "recap": manifest["run"]["ansible"]["recap"],
                },
            )
            write_json(run_dir / "validation.json", make_validation_payload(manifest))
            (run_dir / "ansible.log").write_text("PLAY RECAP\n", encoding="utf-8")
            (run_dir / ".tmp-orphan").write_text("ignore me\n", encoding="utf-8")
            (run_dir / "ansible.log.swp").write_text("ignore me too\n", encoding="utf-8")

            result = finalize(run_dir)

            self.assertEqual(0, result.returncode, result.stderr)
            checksums_text = (run_dir / "SHA256SUMS").read_text(encoding="utf-8")
            self.assertNotIn(".tmp-orphan", checksums_text)
            self.assertNotIn("ansible.log.swp", checksums_text)

    def test_atomic_json_writer_replaces_target_without_leaving_temp_files(self) -> None:
        module = __import__("scripts.finalize_evidence", fromlist=["atomic_write_json"])
        with tempfile.TemporaryDirectory() as tmpdir:
            target = Path(tmpdir) / "manifest.json"
            module.atomic_write_json(target, {"state": "one"})
            module.atomic_write_json(target, {"state": "two"})

            self.assertEqual({"state": "two"}, load_json(target))
            self.assertEqual(
                ["manifest.json"],
                sorted(path.name for path in Path(tmpdir).iterdir()),
            )


if __name__ == "__main__":
    unittest.main()
