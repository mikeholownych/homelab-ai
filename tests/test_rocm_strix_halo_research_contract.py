import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "research" / "rocm-strix-halo"

REQUIRED_SECTIONS = (
    "## Candidates",
    "## Rejected",
    "## Download pins",
    "## Engine coverage",
)


def test_research_tree_scaffold_exists():
    assert (RES / "README.md").is_file()
    assert (RES / "harness" / "README.md").is_file()
    assert (RES / "prompts" / "smoke_chat.json").is_file()
    assert (RES / "prompts" / "smoke_tools.json").is_file()


def test_readme_names_three_engines_and_phases():
    text = (RES / "README.md").read_text()
    for needle in ("llama.cpp", "vLLM", "SGLang", "2a", "2b", "2c", "2d"):
        assert needle in text


def test_model_shortlist_schema():
    path = RES / "model-shortlist.md"
    assert path.is_file()
    text = path.read_text()
    for section in REQUIRED_SECTIONS:
        assert section in text
    # At least 3 candidate bullets under Candidates
    cand = text.split("## Candidates", 1)[1].split("## Rejected", 1)[0]
    assert len(re.findall(r"(?m)^\s*-\s+\*\*", cand)) >= 3
