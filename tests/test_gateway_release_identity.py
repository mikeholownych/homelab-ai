"""The deployed gateway release id must name the code it ships.

2026-10-10/11: gateway code changed in 6a3a52e while inventory still pinned t5820-gateway-b41eaa1, so a deploy put
newer code into the directory named for older code. The release id must name a commit whose gateway code is identical
to the working tree's (git history is required; CI checks out full history for this)."""
import re
import subprocess
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
GATEWAY_CODE = ["orchestrator_gateway", "orchestrator_runtime", "orchestrator_contract"]


def git(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", "-C", str(ROOT), *args], capture_output=True, text=True)


def test_release_id_names_a_commit_with_the_deployed_gateway_code():
    if git("rev-parse", "--is-inside-work-tree").returncode != 0:
        pytest.skip("not a git checkout")
    host_vars = yaml.safe_load((ROOT / "inventory/production/host_vars/ai-5820-01.yml").read_text())
    release_id = host_vars["orchestrator_gateway_release_id"]
    match = re.fullmatch(r"t5820-gateway-([0-9a-f]{7,40})", release_id)
    assert match, f"release id {release_id!r} does not name a commit"
    assert host_vars["orchestrator_gateway_release_dir"].endswith("/" + release_id)
    sha = match.group(1)
    assert git("cat-file", "-e", sha + "^{commit}").returncode == 0, f"{sha} is not in this checkout's history"
    diff = git("diff", "--quiet", sha, "--", *GATEWAY_CODE)
    assert diff.returncode == 0, (
        f"gateway code differs from {release_id}; bump orchestrator_gateway_release_id to the commit that ships it "
        f"(git log -1 --format=%h -- {' '.join(GATEWAY_CODE)})")
