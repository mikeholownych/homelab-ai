from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "research" / "rocm-strix-halo"


def test_research_tree_scaffold_exists():
    assert (RES / "README.md").is_file()
    assert (RES / "harness" / "README.md").is_file()
    assert (RES / "prompts" / "smoke_chat.json").is_file()
    assert (RES / "prompts" / "smoke_tools.json").is_file()


def test_readme_names_three_engines_and_phases():
    text = (RES / "README.md").read_text()
    for needle in ("llama.cpp", "vLLM", "SGLang", "2a", "2b", "2c", "2d"):
        assert needle in text