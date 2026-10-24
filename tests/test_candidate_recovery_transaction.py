"""Exercise the durable transaction with real Ansible and isolated role doubles."""
import importlib.util
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import unittest

import test_candidate_failure_execution as fixture_module

ANSIBLE = fixture_module.ANSIBLE
ROOT = fixture_module.ROOT


TOOL = ROOT / "evaluations/engx/candidate_recovery.py"
spec = importlib.util.spec_from_file_location("candidate_recovery", TOOL)
recovery = importlib.util.module_from_spec(spec)
spec.loader.exec_module(recovery)


@unittest.skipUnless(ANSIBLE, "requires Ansible")
class DurableRecovery(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture_module.CandidateFailureExecution()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        # Keep journal and simulated appliance state outside the pinned checkout.
        self.external = self.root.parent / (self.root.name + "-external")
        self.external.mkdir()
        import shutil
        self.addCleanup(shutil.rmtree, self.external)
        self.fixture.state = self.external / "appliance"
        self.fixture.state.mkdir()
        self.fixture.variables["fixture_state"] = str(self.fixture.state)
        self.fixture.command()
        (self.root / "verify.yml").write_text("""---
- hosts: inference
  gather_facts: false
  tasks:
    - name: Verify both original role configurations independently
      ansible.builtin.assert:
        that:
          - lookup('file', fixture_state ~ '/llama_cpp_container.json') | from_json == llama_cpp_container_workers
          - lookup('file', fixture_state ~ '/orchestrator_gateway.json') | from_json == orchestrator_gateway_workers
          - lookup('fileglob', fixture_state ~ '/verification-fail') | length == 0
""")
        (self.root / "experiment.yml").write_text("""---
- hosts: inference
  gather_facts: false
  tasks:
    - ansible.builtin.fail:
        msg: simulated experiment failure
""")
        for arguments in (["init", "-q"], ["add", "."],
                          ["-c", "user.name=Fixture", "-c", "user.email=fixture@localhost",
                           "commit", "-qm", "isolated recovery source"]):
            subprocess.run(["git", "-C", str(self.root), *arguments], check=True, capture_output=True)
        self.journal = self.external / "journal"
        self.lock = self.external / "reconciliation.lock"

    def command(self, action="run", *extra):
        return [sys.executable, str(TOOL), action, "--source", str(self.root),
                "--inventory", "inventory.json", "--state", str(self.journal),
                "--lock", str(self.lock), "--candidate", "fixture",
                "--candidate-playbook", "candidate.yml", "--verify-playbook", "verify.yml", *extra]

    def run_tool(self, action="run", *extra):
        return subprocess.run(self.command(action, *extra), env=self.fixture.environment(),
                              capture_output=True, text=True, timeout=120)

    def record(self):
        return json.loads((self.journal / "active.json").read_text())

    def test_contended_lock_returns_73_without_mutation_or_traceback(self):
        import fcntl
        with self.lock.open("a+") as owner:
            fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = self.run_tool()
        self.assertEqual(result.returncode, 73, result.stdout + result.stderr)
        self.assertIn("lock is busy", result.stderr)
        self.assertNotIn("Traceback", result.stderr)
        self.assertFalse((self.journal / "active.json").exists())
        self.assertEqual(list(self.fixture.state.iterdir()), [])

    def test_failed_experiment_stays_failed_after_verified_restoration(self):
        result = self.run_tool("run", "--experiment-playbook", "experiment.yml")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(self.record()["experiment_outcome"], "failed")
        self.assertEqual(self.record()["phase"], "restored_verified")
        self.fixture.assert_restored()

    def test_partial_and_complete_swap_faults_restore_and_archive_failed_runs(self):
        previous = None
        for point in ("after-workers", "after-swap"):
            with self.subTest(point=point):
                result = self.run_tool("run", "--fault-point", point)
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                record = self.record()
                self.assertEqual(record["experiment_outcome"], "failed")
                self.assertEqual(record["phase"], "restored_verified")
                self.assertNotEqual(record["deploy_returncode"], 0)
                self.fixture.assert_restored()
                if previous:
                    self.assertEqual(json.loads((self.journal / (previous["run_id"] + ".json")).read_text()), previous)
                previous = record

    def test_verification_failure_blocks_new_run_and_can_be_recovered(self):
        marker = self.fixture.state / "verification-fail"
        marker.touch()
        result = self.run_tool()
        self.assertEqual(result.returncode, 3, result.stdout + result.stderr)
        self.assertEqual(self.record()["phase"], "verification_failed")
        refused = self.run_tool()
        self.assertNotEqual(refused.returncode, 0)
        self.assertIn("unresolved run", refused.stderr)
        marker.unlink()
        result = self.run_tool("recover")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.record()["phase"], "restored_verified")

    def test_changed_source_is_refused_before_any_mutation(self):
        (self.root / "verify.yml").write_text("changed source")
        result = self.run_tool()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("clean committed checkout", result.stderr)
        self.assertFalse((self.journal / "active.json").exists())
        self.assertEqual(list(self.fixture.state.iterdir()), [])

    def test_scheduler_preflight_without_record_is_a_noop(self):
        command = self.command()
        command[2] = "recover-if-present"
        result = subprocess.run(command, env=self.fixture.environment(),
                                capture_output=True, text=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertFalse((self.journal / "active.json").exists())
        self.assertEqual(list(self.fixture.state.iterdir()), [])

    def test_rejected_baseline_never_swaps_or_restores_and_survives_snapshot_upgrade(self):
        result = self.run_tool("run", "--baseline-playbook", "experiment.yml")
        self.assertEqual(result.returncode, 4, result.stdout + result.stderr)
        record = self.record()
        self.assertEqual(record["phase"], "baseline_rejected")
        self.assertEqual(record["experiment_outcome"], "not_started")
        self.assertNotIn("deploying", [event["phase"] for event in record["events"]])
        self.assertNotIn("restoring", [event["phase"] for event in record["events"]])
        self.assertEqual(list(self.fixture.state.iterdir()), [])
        (self.root / "new-snapshot.txt").write_text("new snapshot")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-qm", "upgraded snapshot"], check=True)
        result = self.run_tool("recover")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.record(), record)
        self.assertEqual(list(self.fixture.state.iterdir()), [])

    def test_restore_failure_retains_record_and_requires_recovery(self):
        role = self.root / "roles/llama_cpp_container/tasks/main.yml"
        content = role.read_text()
        role.write_text(content.replace("---\n", """---
- name: Simulate failure before restoration changes the worker configuration
  ansible.builtin.fail:
    msg: simulated restoration failure
  when: "'candidate-fixture' not in llama_cpp_container_workers and lookup('fileglob', fixture_state ~ '/restore-fail') | length > 0"
""", 1))
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-qm", "restoration fault fixture"], check=True)
        marker = self.fixture.state / "restore-fail"
        marker.touch()
        result = self.run_tool()
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        record = self.record()
        self.assertEqual(record["phase"], "restore_failed")
        self.assertIn("candidate-fixture", self.fixture.read("llama_cpp_container"))
        refused = self.run_tool()
        self.assertNotEqual(refused.returncode, 0)
        self.assertEqual(self.record()["run_id"], record["run_id"])
        marker.unlink()
        result = self.run_tool("recover")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.fixture.assert_restored()

    def test_recovery_refuses_a_different_committed_source(self):
        # Seed a durable unresolved record without touching the simulated host.
        self.journal.mkdir()
        record = {"schema": 1, "run_id": "fixture", "phase": "deploying",
                  "source": str(self.root), "inventory": "inventory.json", "lock": str(self.lock),
                  "identity": recovery.identity(self.root, self.root / "inventory.json")}
        recovery.atomic_record(self.journal / "active.json", record)
        (self.root / "new-source.txt").write_text("changed committed source")
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-qm", "different source"], check=True)
        result = self.run_tool("recover")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("identity differs", result.stderr)
        self.assertEqual(self.record(), record)
        self.assertEqual(list(self.fixture.state.iterdir()), [])

    def test_wrapper_death_keeps_lock_until_its_ansible_child_finishes(self):
        self.interrupt_wrapper(signal.SIGKILL)

    def test_interactive_interrupt_stops_child_before_restoring(self):
        self.interrupt_wrapper(signal.SIGINT)

    def interrupt_wrapper(self, interruption):
        # Stop the real role at its file-backed candidate state. Only the wrapper
        # dies first: its surviving Ansible child must retain exclusion.
        self.fixture.variables["fixture_pause_role"] = "orchestrator_gateway"
        self.fixture.command()
        subprocess.run(["git", "-C", str(self.root), "add", "."], check=True)
        subprocess.run(["git", "-C", str(self.root), "-c", "user.name=Fixture", "-c",
                        "user.email=fixture@localhost", "commit", "-qm", "pause fixture"], check=True)
        log = self.external / "killed-wrapper.log"
        with log.open("w") as output:
            proc = subprocess.Popen(self.command(), env=self.fixture.environment(),
                                    stdout=output, stderr=subprocess.STDOUT)
            try:
                deadline = time.monotonic() + 40
                while time.monotonic() < deadline:
                    gateway = self.fixture.state / "orchestrator_gateway.json"
                    if gateway.exists() and "candidate-fixture" in gateway.read_text():
                        break
                    if proc.poll() is not None:
                        self.fail(log.read_text())
                    time.sleep(0.1)
                else:
                    self.fail(log.read_text())
                proc.send_signal(interruption)
                if interruption == signal.SIGINT:
                    proc.wait(timeout=90)
                    self.assertNotEqual(proc.returncode, 0)
                    self.assertEqual(self.record()["phase"], "restored_verified", log.read_text())
                    self.assertEqual(self.record()["experiment_outcome"], "not_completed")
                    self.fixture.assert_restored()
                    return
                proc.wait(timeout=5)
                refused = self.run_tool("recover")
                self.assertNotEqual(refused.returncode, 0)
                self.assertIn("lock is busy", refused.stderr)
                self.assertEqual(refused.returncode, 73, refused.stdout + refused.stderr)
                (self.fixture.state / "continue").touch()
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    result = self.run_tool("recover")
                    if "lock is busy" not in result.stderr:
                        break
                    time.sleep(0.1)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(self.record()["experiment_outcome"], "not_completed")
                self.assertEqual(self.record()["phase"], "restored_verified")
                self.fixture.assert_restored()
            finally:
                if proc.poll() is None:
                    proc.kill()
                    proc.wait()
                # Let a surviving Ansible child leave the isolated pause even
                # when an assertion fails; no appliance process is involved.
                (self.fixture.state / "continue").touch()


if __name__ == "__main__":
    unittest.main()
