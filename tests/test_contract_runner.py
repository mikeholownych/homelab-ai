from __future__ import annotations

import json

from evaluations.run_contracts import run_cases


def test_contract_runner_executes_all_cases_without_external_access(tmp_path):
    report_path = tmp_path / "report.json"
    report = run_cases(report_path)

    assert report["network_access"] is False
    assert report["production_credentials"] is False
    assert report["active_b0_access"] is False
    assert len(report["results"]) == 11
    assert all(result["expected"] == result["actual"] for result in report["results"])
    assert json.loads(report_path.read_text())["run_id"] == report["run_id"]
