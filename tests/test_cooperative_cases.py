from pathlib import Path

import yaml


def test_cooperative_cases_are_network_and_production_isolated():
    cases = yaml.safe_load(
        (Path(__file__).parents[1] / "evaluations/cooperative-cases.yml").read_text()
    )

    assert cases["schema_version"] == "1.0.0"
    assert cases["network_access"] is False
    assert cases["production_credentials"] is False
    assert cases["active_b0_access"] is False
    assert len(cases["cases"]) == 11
    assert len({case["id"] for case in cases["cases"]}) == 11
    assert all(case["expected"] in {"validated", "blocked", "unsupported", "rejected"}
               for case in cases["cases"])
