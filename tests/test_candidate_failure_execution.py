"""Execute the real candidate play against file-backed, localhost-only roles.

These tests prove Ansible control flow, not GPU or deployed gateway recovery.
The SIGKILL case records the boundary: rescue cannot run after its controller dies.
Run with python3 -m unittest discover -s tests -p test_candidate_failure_execution.py -v.
"""
import json
import fcntl
import os
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
ANSIBLE = shutil.which("ansible-playbook")


@unittest.skipUnless(ANSIBLE and shutil.which("flock"), "requires Ansible and flock")
class CandidateFailureExecution(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="candidate-failure-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.state = self.root / "state"
        self.state.mkdir()
        # Copy the production control flow byte-for-byte. Only the invoked roles
        # are doubles; there is no production inventory, SSH or GPU access.
        self.play = self.root / "candidate.yml"
        self.play.write_bytes((ROOT / "playbooks/candidate.yml").read_bytes())
        self.inventory = self.root / "inventory.json"
        self.inventory.write_text(json.dumps({"all": {"children": {"inference": {
            "hosts": {"fixture": {"ansible_connection": "local",
                                  "ansible_python_interpreter": "/usr/bin/python3"}}
        }}}}))
        self.config = self.root / "ansible.cfg"
        self.config.write_text("[defaults]\nretry_files_enabled=False\n"
                               "host_key_checking=True\n")
        self.variables = {
            "ansible_become": False,
            "candidate": "fixture",
            "fixture_state": str(self.state),
            "llama_cpp_container_workers": {"lead": {"state": "started"},
                                             "deep": {"state": "started"}},
            "orchestrator_gateway_workers": [
                {"worker_id": "lead", "state": "started", "pool": "lead"},
                {"worker_id": "deep", "state": "started", "pool": "deep"}],
            "orchestrator_gateway_model_aliases": {"engineering/lead": {"pool": "lead"}},
            "llama_cpp_container_candidate_profiles": {"fixture": {
                "replaces": "lead", "replaces_gateway_worker_id": "lead",
                "worker": {"state": "started"},
                "gateway_worker": {"worker_id": "candidate-fixture", "pool": "candidate"}}},
        }
        for role, expression in (
            ("llama_cpp_container", "llama_cpp_container_workers"),
            ("orchestrator_gateway", "orchestrator_gateway_workers"),
        ):
            directory = self.root / "roles" / role / "tasks"
            directory.mkdir(parents=True)
            (directory / "main.yml").write_text("\n".join([
                "---", "- name: Record the configuration presented to the role",
                "  ansible.builtin.copy:",
                f"    dest: '{{{{ fixture_state }}}}/{role}.json'",
                f"    content: '{{{{ {expression} | to_json }}}}'",
                "    mode: '0600'",
                "- name: Inject a role failure after configuration changed",
                "  ansible.builtin.fail:", "    msg: isolated role failure",
                f"  when: fixture_fail_role | default('') == '{role}' and 'candidate-fixture' in llama_cpp_container_workers",
                "- name: Pause with candidate configuration installed",
                "  ansible.builtin.wait_for:",
                "    path: '{{ fixture_state }}/continue'", "    timeout: 60",
                f"  when: fixture_pause_role | default('') == '{role}' and 'candidate-fixture' in llama_cpp_container_workers",
                "",
            ]))

    def command(self, **extra):
        inventory = json.loads(self.inventory.read_text())
        inventory["all"]["children"]["inference"]["vars"] = self.variables
        self.inventory.write_text(json.dumps(inventory))
        values = self.root / "variables.json"
        # Inventory defaults must remain overridable by the play's set_fact;
        # passing them as extra vars would prevent the candidate swap itself.
        values.write_text(json.dumps(extra))
        return [ANSIBLE, "-i", str(self.inventory), str(self.play), "-e", "@" + str(values)]

    def environment(self):
        return {**os.environ, "ANSIBLE_CONFIG": str(self.config),
                "ANSIBLE_ROLES_PATH": str(self.root / "roles"),
                "ANSIBLE_LOCAL_TEMP": str(self.root / "ansible-temp")}

    def run_play(self, **extra):
        result = subprocess.run(self.command(**extra), env=self.environment(),
                                cwd=self.root, capture_output=True, text=True, timeout=60)
        return result

    def read(self, role):
        return json.loads((self.state / (role + ".json")).read_text())

    def assert_restored(self):
        self.assertEqual(self.read("llama_cpp_container"), self.variables["llama_cpp_container_workers"])
        self.assertEqual(self.read("orchestrator_gateway"), self.variables["orchestrator_gateway_workers"])

    def test_successful_swap_and_explicit_restoration(self):
        result = self.run_play()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        workers = self.read("llama_cpp_container")
        self.assertEqual(workers["lead"]["state"], "stopped")
        self.assertEqual(workers["deep"], self.variables["llama_cpp_container_workers"]["deep"])
        self.assertIn("candidate-fixture", workers)
        result = self.run_play(candidate_state="absent")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assert_restored()

    def test_role_failures_restore_and_preserve_failure_status(self):
        for role in ("llama_cpp_container", "orchestrator_gateway"):
            with self.subTest(role=role):
                result = self.run_play(fixture_fail_role=role)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("isolated role failure", result.stdout)
                self.assert_restored()

    def test_post_swap_failure_restores_and_preserves_failure_status(self):
        result = self.run_play(candidate_drill_fail_after_swap=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("candidate_drill_fail_after_swap is set", result.stdout)
        self.assert_restored()

    def test_killed_controller_requires_explicit_recovery(self):
        self.interrupt_controller(signal.SIGKILL)

    def test_cancelled_controller_requires_explicit_recovery(self):
        self.interrupt_controller(signal.SIGTERM)

    def interrupt_controller(self, interruption):
        log = self.root / "interrupted.log"
        with log.open("w") as output:
            proc = subprocess.Popen(self.command(fixture_pause_role="orchestrator_gateway"),
                                    cwd=self.root, env=self.environment(),
                                    stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
            try:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    gateway = self.state / "orchestrator_gateway.json"
                    if gateway.exists() and "candidate-fixture" in gateway.read_text():
                        break
                    if proc.poll() is not None:
                        self.fail(log.read_text())
                    time.sleep(0.1)
                else:
                    self.fail("candidate state not reached: " + log.read_text())
                os.killpg(proc.pid, interruption)
                proc.wait(timeout=10)
                # This is a characterized gap, not a passing automatic-recovery claim.
                self.assertIn("candidate-fixture", self.read("llama_cpp_container"))
                result = self.run_play(candidate_state="absent")
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assert_restored()
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=10)


@unittest.skipUnless(shutil.which("flock"), "requires flock")
class QualificationLockExecution(unittest.TestCase):
    def test_contender_cannot_release_an_existing_owners_lock(self):
        with tempfile.TemporaryDirectory(prefix="qualification-lock-") as directory:
            lock = Path(directory) / "lock"
            with lock.open("w") as owner:
                fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
                for _ in range(2):
                    contender = subprocess.run(["flock", "--nonblock", str(lock), "true"], timeout=5)
                    self.assertEqual(contender.returncode, 1)
            released = subprocess.run(["flock", "--nonblock", str(lock), "true"], timeout=5)
            self.assertEqual(released.returncode, 0)

    def test_dead_holder_leaves_no_stale_file_lock(self):
        with tempfile.TemporaryDirectory(prefix="qualification-lock-") as directory:
            lock, ready = Path(directory) / "lock", Path(directory) / "ready"
            script = "import pathlib,sys,time; pathlib.Path(sys.argv[1]).touch(); time.sleep(30)"
            proc = subprocess.Popen(["flock", "--nonblock", str(lock), "/usr/bin/python3", "-c", script, str(ready)],
                                    start_new_session=True)
            try:
                deadline = time.monotonic() + 5
                while not ready.exists() and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(ready.exists())
                self.assertEqual(subprocess.run(["flock", "--nonblock", str(lock), "true"], timeout=5).returncode, 1)
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=5)
                self.assertEqual(subprocess.run(["flock", "--nonblock", str(lock), "true"], timeout=5).returncode, 0)
            finally:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                proc.wait(timeout=5)


if __name__ == "__main__":
    unittest.main()
