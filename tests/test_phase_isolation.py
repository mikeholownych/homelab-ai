"""Phase tests must not share one import path (see scripts/run-phase-tests.sh and pytest.ini)."""
from __future__ import annotations

import configparser
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
PHASES = sorted(int(p.name[5:]) for p in REPO_ROOT.glob("phase[0-9]*") if p.is_dir())


def test_root_pytest_path_does_not_mix_phase_sources():
    parser = configparser.ConfigParser()
    parser.read(REPO_ROOT / "pytest.ini")
    pythonpath = parser["pytest"]["pythonpath"].split()
    assert not [entry for entry in pythonpath if entry.startswith("phase")], pythonpath
    assert parser["pytest"]["testpaths"].split() == ["tests"]


def test_make_test_runs_the_per_phase_target_that_ci_uses():
    makefile = (REPO_ROOT / "Makefile").read_text(encoding="utf-8")
    assert "test-phases:" in makefile
    assert "scripts/run-phase-tests.sh" in makefile
    test_recipe = makefile.split("\ntest: ", 1)[1].split("\n\n", 1)[0]
    assert "$(MAKE) test-phases" in test_recipe
    assert "make quality" in (REPO_ROOT / ".github/workflows/quality.yml").read_text(encoding="utf-8")


def test_each_phase_resolves_its_own_copy_of_a_module_shared_across_phases():
    # workflow/engine.py exists in several phases; on one shared path phase8's copy would win for every phase.
    shared = "workflow/engine.py"
    owners = [n for n in PHASES if (REPO_ROOT / f"phase{n}/src/autonomous_engineering/{shared}").is_file()]
    assert len(owners) > 1, "fixture assumption: the module exists in more than one phase"
    for n in owners:
        # Same path construction as scripts/run-phase-tests.sh: phaseN/src first, then older phases.
        paths = [str(REPO_ROOT / f"phase{i}/src") for i in range(n, -1, -1) if (REPO_ROOT / f"phase{i}/src").is_dir()]
        code = (
            f"import sys; sys.path[:0] = {paths!r}\n"
            "import autonomous_engineering.workflow.engine as module\n"
            "print(module.__file__)"
        )
        out = subprocess.run([sys.executable, "-I", "-c", code], capture_output=True, text=True, check=True)
        assert Path(out.stdout.strip()) == REPO_ROOT / f"phase{n}/src/autonomous_engineering/{shared}", n


def test_runner_script_covers_every_phase_and_is_executable():
    runner = REPO_ROOT / "scripts/run-phase-tests.sh"
    assert runner.stat().st_mode & 0o111
    text = runner.read_text(encoding="utf-8")
    assert "phaseN/src first" in text or "phase$n/src first" in text
    assert '-o "pythonpath=' in text
    # Child interpreters spawned by phase tests (repo sandboxes) must not inherit the phase path.
    assert not [line for line in text.splitlines() if line.strip().startswith(("PYTHONPATH=", "export PYTHONPATH"))]
