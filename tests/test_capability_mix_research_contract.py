import importlib.util
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "research" / "capability-mix"


def test_capability_mix_tree_exists():
    assert (RES / "README.md").is_file()
    assert (RES / "orchestration-probe.md").is_file()
    assert (RES / "prompts" / "orch_tools.json").is_file()
    assert (RES / "prompts" / "orch_route.json").is_file()


def test_readme_names_tracks_and_bars():
    text = (RES / "README.md").read_text()
    for needle in ("Track L", "Track R", "coding.routine", "R-text", "R-ocr", "R-img"):
        assert needle in text


def test_orch_prompts_are_objects_with_id():
    for name in ("orch_tools.json", "orch_route.json"):
        data = json.loads((RES / "prompts" / name).read_text())
        assert "id" in data and "messages" in data


def test_orchestration_probe_module_help():
    script = ROOT / "evaluations" / "capability_mix" / "orchestration_probe.py"
    assert script.is_file()
    proc = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "orchestration" in (proc.stdout + proc.stderr).lower() or "--base" in proc.stdout


def _orchestration_probe_module():
    path = ROOT / "evaluations" / "capability_mix" / "orchestration_probe.py"
    spec = importlib.util.spec_from_file_location("orchestration_probe", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_orchestration_probe_rejects_non_https_base():
    probe = _orchestration_probe_module()
    try:
        probe._require_https_base("http://gateway.example")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "TLS" in str(exc)