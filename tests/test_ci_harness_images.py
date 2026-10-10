"""CI prebuilds the container harness images; their tags and Dockerfiles must be exactly the harness's own."""
import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_harness():
    spec = importlib.util.spec_from_file_location("harness", ROOT / "tests/integration/baseline_container_harness.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_ci_prebuilds_every_harness_image_under_the_harness_tag():
    harness = load_harness()
    steps = yaml.safe_load((ROOT / ".github/workflows/quality.yml").read_text())["jobs"]["quality"]["steps"]
    built = {step["with"]["tags"]: step["with"]["file"] for step in steps
             if str(step.get("uses", "")).startswith("docker/build-push-action@")}
    expected = {cfg["harness_image"]: str(Path(cfg["dockerfile"]).relative_to(ROOT)) for cfg in harness.RELEASE_CONFIGS.values()}
    assert built == expected
    quality = next(step for step in steps if step.get("run") == "make quality")
    assert quality["env"]["AIHOST_HARNESS_PREBUILT"] == "1"
