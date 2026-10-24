"""Durable candidate transaction; all appliance actions are Ansible playbooks.

An independent actor must call ``recover`` after controller loss. This tool is
not itself a scheduler and must not be described as automatic crash recovery.
"""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time
import uuid


TERMINAL = {"restored_verified", "baseline_rejected"}


def atomic_record(path: Path, record: dict) -> None:
    """Publish a complete private record and flush both data and directory."""
    fd, temporary = tempfile.mkstemp(prefix=".record-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as output:
            json.dump(record, output, indent=2, sort_keys=True)
            output.write("\n")
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def identity(root: Path, inventory: Path) -> dict:
    def git(*arguments):
        return subprocess.check_output(["git", "-C", str(root), *arguments])

    if git("status", "--porcelain").strip():
        raise RuntimeError("source must be a clean committed checkout")
    paths = [root / os.fsdecode(p) for p in git("ls-files", "-z").split(b"\0") if p]
    paths += sorted(inventory.rglob("*")) if inventory.is_dir() else [inventory]
    digest = hashlib.sha256()
    for path in paths:
        if path.is_dir():
            continue
        # Bind names and contents; do not retain credential contents in the record.
        digest.update(os.fsencode(str(path.relative_to(root))) + b"\0")
        digest.update(hashlib.sha256(path.read_bytes()).digest())
    return {"head": git("rev-parse", "HEAD").decode().strip(), "sha256": digest.hexdigest()}


def source_path(root: Path, name: str) -> Path:
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.exists():
        raise RuntimeError("input must exist inside the pinned source checkout")
    return path


def execute(args) -> int:
    root = Path(args.source).resolve()
    inventory = source_path(root, args.inventory)
    state = Path(args.state).resolve()
    lock_path = Path(args.lock).resolve()
    if state.is_relative_to(root):
        raise RuntimeError("run records must be outside the source checkout")
    state.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(state, 0o700)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    record_path = state / "active.json"
    # Use the reconciliation lock inode. Never unlink it or infer ownership from
    # somebody else's inability to acquire it.
    with lock_path.open("a+") as ownership:
        try:
            fcntl.flock(ownership, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("reconciliation/candidate lock is busy") from error
        current = identity(root, inventory)
        old = json.loads(record_path.read_text()) if record_path.exists() else None
        if args.action == "recover-if-present" and old is None:
            return 0
        # Completed transactions do not need to be replayed under a newer
        # snapshot. Unresolved transactions below still require exact identity.
        if args.action != "run" and old and old.get("phase") in TERMINAL:
            return 0
        if args.action == "run":
            if old and old["phase"] not in TERMINAL:
                raise RuntimeError("unresolved run exists; recover it before starting a candidate")
            if not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", args.candidate or ""):
                raise RuntimeError("a declared candidate profile name is required")
            for name in (args.candidate_playbook, args.verify_playbook):
                if not name:
                    raise RuntimeError("candidate and independent verification playbooks are required")
                source_path(root, name)
            if args.experiment_playbook:
                source_path(root, args.experiment_playbook)
            if args.baseline_playbook:
                source_path(root, args.baseline_playbook)
            executable = Path(shutil.which(args.ansible) or args.ansible).resolve()
            if not executable.is_file() or not os.access(executable, os.X_OK):
                raise RuntimeError("Ansible executable is unavailable")
            if old:
                atomic_record(state / (old["run_id"] + ".json"), old)
            record = {
                "schema": 1, "run_id": uuid.uuid4().hex, "phase": "prepared",
                "identity": current, "source": str(root), "inventory": args.inventory,
                "lock": str(lock_path), "candidate": args.candidate,
                "candidate_playbook": args.candidate_playbook,
                "verify_playbook": args.verify_playbook,
                "experiment_playbook": args.experiment_playbook,
                "baseline_playbook": args.baseline_playbook,
                "fault_point": args.fault_point,
                "allow_restore_fault": args.allow_restore_fault,
                "ansible": str(executable), "timeout": args.timeout,
                "ansible_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                "experiment_outcome": "not_completed", "events": [],
            }
        else:
            if not old:
                raise RuntimeError("no recovery record exists")
            record = old
            if (record["source"] != str(root) or record["inventory"] != args.inventory
                    or record["lock"] != str(lock_path) or record["identity"] != current):
                raise RuntimeError("source/inventory/lock identity differs from the recorded run")
            if record["phase"] in TERMINAL:
                return 0

        def transition(phase):
            record["phase"] = phase
            record["events"].append({"phase": phase, "at": time.time()})
            atomic_record(record_path, record)

        def play(name, variables):
            # Recheck before each operation; a changed checkout blocks recovery
            # instead of converging whatever happens to be present now.
            if identity(root, inventory) != record["identity"]:
                raise RuntimeError("source changed during the run")
            if hashlib.sha256(Path(record["ansible"]).read_bytes()).hexdigest() != record["ansible_sha256"]:
                raise RuntimeError("Ansible executable changed since preparation")
            path = source_path(root, name)
            evidence = state / record["run_id"]
            evidence.mkdir(mode=0o700, exist_ok=True)
            variables = {"candidate": record["candidate"], **variables, "candidate_run_id": record["run_id"],
                         "candidate_evidence_root": str(evidence)}
            if variables.get("candidate_state") == "absent":
                variables["candidate_drill_fail_restore"] = (
                    record.get("allow_restore_fault", False) and (state / "restore-fault").exists())
            command = [record["ansible"], "-i", str(inventory), str(path), "-e", json.dumps(variables)]
            # Ansible inherits ownership. Killing this wrapper alone cannot
            # release the lock while its Ansible child continues mutating state.
            # Give every command its own process group for bounded timeout cleanup.
            child = subprocess.Popen(command, cwd=root, pass_fds=(ownership.fileno(),),
                                     start_new_session=True,
                                     env={**os.environ, "ANSIBLE_CONFIG": str(root / "ansible.cfg"),
                                          "ANSIBLE_LOCAL_TEMP": str(state / "ansible-temp")})
            try:
                return child.wait(timeout=record["timeout"])
            except subprocess.TimeoutExpired:
                import signal
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                return 124
            except BaseException:
                # An interactive interrupt must not start restoration while
                # the original Ansible child is still changing the same host.
                import signal
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()
                raise

        transition("prepared" if args.action == "run" else "recovering")
        if args.action == "run" and record["baseline_playbook"]:
            transition("baseline")
            baseline_rc = play(record["baseline_playbook"], {"verification_stage": "baseline"})
            record["baseline_returncode"] = baseline_rc
            if baseline_rc:
                # No candidate swap has begun. Preserve rejection without
                # mutating production or requiring an absent baseline artifact.
                record["experiment_outcome"] = "not_started"
                transition("baseline_rejected")
                return 4
        experiment_rc = 1
        try:
            if args.action == "run":
                transition("deploying")
                experiment_rc = play(record["candidate_playbook"],
                                     {"candidate": record["candidate"], "candidate_state": "present",
                                      "candidate_drill_fail_after_workers": record["fault_point"] == "after-workers",
                                      "candidate_drill_fail_after_swap": record["fault_point"] == "after-swap"})
                record["deploy_returncode"] = experiment_rc
                if experiment_rc == 0 and record["experiment_playbook"]:
                    transition("experiment")
                    experiment_rc = play(record["experiment_playbook"], {"candidate": record["candidate"]})
                    record["experiment_returncode"] = experiment_rc
                record["experiment_outcome"] = (
                    "not_requested" if experiment_rc == 0 and not record["experiment_playbook"]
                    else ("passed" if experiment_rc == 0 else "failed")
                )
        finally:
            transition("restoring")
            restored = play(record["candidate_playbook"],
                            {"candidate": record["candidate"], "candidate_state": "absent"})
            record["restore_returncode"] = restored
            if restored:
                transition("restore_failed")
                return 2
            transition("verifying")
            verified = play(record["verify_playbook"], {"candidate": record["candidate"]})
            record["verify_returncode"] = verified
            if verified:
                transition("verification_failed")
                return 3
            transition("restored_verified")
        return 0 if args.action != "run" else (0 if experiment_rc == 0 else 1)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("action", choices=["run", "recover", "recover-if-present"])
    result.add_argument("--source", required=True)
    result.add_argument("--inventory", required=True)
    result.add_argument("--state", required=True)
    result.add_argument("--lock", required=True)
    result.add_argument("--candidate")
    result.add_argument("--candidate-playbook", default="playbooks/candidate.yml")
    result.add_argument("--verify-playbook")
    result.add_argument("--experiment-playbook")
    result.add_argument("--baseline-playbook")
    result.add_argument("--fault-point", choices=["none", "after-workers", "after-swap"], default="none")
    result.add_argument("--allow-restore-fault", action="store_true")
    result.add_argument("--ansible", default="ansible-playbook")
    result.add_argument("--timeout", type=int, default=1800)
    return result


if __name__ == "__main__":
    arguments = parser().parse_args()
    if arguments.timeout <= 0 or arguments.timeout > 7200:
        raise SystemExit("timeout must be between 1 and 7200 seconds")
    try:
        raise SystemExit(execute(arguments))
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as error:
        if "lock is busy" in str(error):
            print(str(error), file=sys.stderr)
            raise SystemExit(73)
        raise SystemExit(str(error))
