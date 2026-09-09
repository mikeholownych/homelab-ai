from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import uuid
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
ANSIBLE_PLAYBOOK = REPO_ROOT / ".venv" / "bin" / "ansible-playbook"


def has_loopback_prerequisites() -> bool:
    required_bins = ("losetup", "pvs", "vgs", "lvs", "mkfs.xfs", "blkid", "findmnt")
    for b in required_bins:
        if not shutil.which(b):
            return False
    res = subprocess.run(["sudo", "-n", "true"], capture_output=True)
    return res.returncode == 0


def test_storage_lvm_loopback_convergence_and_idempotency() -> None:
    if not has_loopback_prerequisites():
        pytest.skip("Test requires passwordless sudo and LVM/XFS system tools")


    vg_name = f"vg_test_{uuid.uuid4().hex[:8]}"
    lv_name = "test_ai_lv"
    tmp_dir = Path(tempfile.mkdtemp(prefix="storage-loop-"))
    img1 = tmp_dir / "pv1.img"
    img2 = tmp_dir / "pv2.img"
    mnt_dir = tmp_dir / "mnt"
    mnt_dir.mkdir()
    evidence_path = mnt_dir / "evidence" / "storage-layout.json"

    loop1 = None
    loop2 = None
    try:
        with open(img1, "wb") as f:
            f.truncate(400 * 1024 * 1024)
        with open(img2, "wb") as f:
            f.truncate(400 * 1024 * 1024)

        loop1 = subprocess.check_output(["sudo", "losetup", "-f", "--show", str(img1)], text=True).strip()
        loop2 = subprocess.check_output(["sudo", "losetup", "-f", "--show", str(img2)], text=True).strip()

        subprocess.check_call(["sudo", "pvcreate", "-y", loop1, loop2])
        subprocess.check_call(["sudo", "vgcreate", "-y", vg_name, loop1, loop2])

        playbook_content = f"""---
- name: Test LVM storage convergence
  hosts: localhost
  connection: local
  gather_facts: false
  become: true
  vars:
    storage_manage_runtime: true
    storage_allowed_fstypes: [xfs, ext4]
    storage_lvm_evidence_path: "{evidence_path}"
    storage_lvm:
      enabled: true
      vg: "{vg_name}"
      lv: "{lv_name}"
      size: "300m"
      fstype: "xfs"
      mount_path: "{mnt_dir}"
      reserve_gib: 0
      expected_pvs:
        - "{loop1}"
        - "{loop2}"
  tasks:
    - name: Run storage LVM tasks
      ansible.builtin.include_role:
        name: storage
        tasks_from: lvm.yml
"""
        pb_path = tmp_dir / "test_lvm.yml"
        pb_path.write_text(playbook_content, encoding="utf-8")

        env = os.environ.copy()
        env["ANSIBLE_CONFIG"] = str(REPO_ROOT / "ansible.cfg")

        # Pass 1: Convergence
        res1 = subprocess.run(
            [str(ANSIBLE_PLAYBOOK if ANSIBLE_PLAYBOOK.exists() else "ansible-playbook"), str(pb_path)],
            env=env,
            capture_output=True,
            text=True,
        )
        assert res1.returncode == 0, f"Pass 1 failed:\n{res1.stdout}\n{res1.stderr}"

        # Verify evidence document
        evidence_text = subprocess.check_output(["sudo", "cat", str(evidence_path)], text=True)
        evidence = json.loads(evidence_text)
        assert evidence["vg_name"] == vg_name
        assert evidence["lv_name"] == lv_name
        assert evidence["mount_path"] == str(mnt_dir)
        assert evidence["fstype"] == "xfs"
        assert evidence["fs_uuid"], "fs_uuid should be non-empty"
        assert len(evidence["pvs"]) >= 2

        # Pass 2: Idempotency
        res2 = subprocess.run(
            [str(ANSIBLE_PLAYBOOK if ANSIBLE_PLAYBOOK.exists() else "ansible-playbook"), str(pb_path)],
            env=env,
            capture_output=True,
            text=True,
        )
        assert res2.returncode == 0, f"Pass 2 failed:\n{res2.stdout}\n{res2.stderr}"
        assert "changed=0" in res2.stdout, f"Pass 2 was not idempotent:\n{res2.stdout}"

    finally:
        subprocess.run(["sudo", "umount", "-f", str(mnt_dir)], capture_output=True)
        subprocess.run(["sudo", "vgremove", "-y", "-f", vg_name], capture_output=True)
        if loop1:
            subprocess.run(["sudo", "pvremove", "-y", "-f", loop1], capture_output=True)
            subprocess.run(["sudo", "losetup", "-d", loop1], capture_output=True)
        if loop2:
            subprocess.run(["sudo", "pvremove", "-y", "-f", loop2], capture_output=True)
            subprocess.run(["sudo", "losetup", "-d", loop2], capture_output=True)
        shutil.rmtree(tmp_dir, ignore_errors=True)
