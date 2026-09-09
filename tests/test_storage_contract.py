from __future__ import annotations

from pathlib import Path
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCTION_ROOT = REPO_ROOT / "inventory" / "production"
STORAGE_ROLE_ROOT = REPO_ROOT / "roles" / "storage"


def load_yaml(path: Path) -> object:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_ai_5820_01_declares_exact_storage_lvm_contract() -> None:
    host_vars = load_yaml(PRODUCTION_ROOT / "host_vars" / "ai-5820-01.yml")
    assert "storage_lvm" in host_vars
    assert host_vars["storage_lvm"] == {
        "enabled": True,
        "vg": "ubuntu-vg",
        "lv": "local-ai-lv",
        "size": "550g",
        "fstype": "xfs",
        "mount_path": "/var/lib/local-ai",
        "reserve_gib": 50,
        "expected_pvs": [
            "/dev/nvme0n1p3",
            "/dev/nvme1n1p1",
        ],
    }


def test_storage_role_includes_lvm_tasks_conditionally() -> None:
    main_tasks = (STORAGE_ROLE_ROOT / "tasks" / "main.yml").read_text(encoding="utf-8")
    assert "lvm.yml" in main_tasks
    assert "storage_lvm" in main_tasks


def test_storage_lvm_preflight_precedes_mutation() -> None:
    lvm_tasks_path = STORAGE_ROLE_ROOT / "tasks" / "lvm.yml"
    assert lvm_tasks_path.exists(), "roles/storage/tasks/lvm.yml must exist"
    lvm_tasks = lvm_tasks_path.read_text(encoding="utf-8")

    assert "pvs --reportformat json" in lvm_tasks
    assert "vgs --reportformat json" in lvm_tasks
    assert "lvs --reportformat json" in lvm_tasks
    assert "findmnt --json" in lvm_tasks
    assert "blkid -p" in lvm_tasks

    lvol_idx = lvm_tasks.index("community.general.lvol")
    assert lvm_tasks.index("pvs --reportformat json") < lvol_idx
    assert lvm_tasks.index("vgs --reportformat json") < lvol_idx
    assert lvm_tasks.index("lvs --reportformat json") < lvol_idx
    assert lvm_tasks.index("findmnt --json") < lvol_idx
    assert lvm_tasks.index("blkid -p") < lvol_idx


def test_storage_lvm_avoids_destructive_commands_and_enforces_safe_defaults() -> None:
    lvm_tasks_path = STORAGE_ROLE_ROOT / "tasks" / "lvm.yml"
    assert lvm_tasks_path.exists()
    lvm_tasks = lvm_tasks_path.read_text(encoding="utf-8")

    # Forbidden destructive commands / flags
    assert "pvcreate" not in lvm_tasks
    assert "vgcreate" not in lvm_tasks
    assert "wipefs" not in lvm_tasks
    assert "force: true" not in lvm_tasks
    assert "force: yes" not in lvm_tasks

    # Mandatory safe flags
    assert "force: false" in lvm_tasks
    assert "resizefs: false" in lvm_tasks
    assert "UUID=" in lvm_tasks
    assert "storage_manage_runtime" in lvm_tasks
