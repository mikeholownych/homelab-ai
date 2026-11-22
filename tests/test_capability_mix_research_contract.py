from pathlib import Path
import json

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