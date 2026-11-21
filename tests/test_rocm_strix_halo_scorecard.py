import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCORECARD = ROOT / "research" / "rocm-strix-halo" / "harness" / "scorecard.py"


def _load():
    spec = importlib.util.spec_from_file_location("rocm_scorecard", SCORECARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


sc = _load()
score = sc.score


def test_scorecard_weights_sum_and_prefer_quality_ttft():
    weights = {"quality": 0.30, "ttft": 0.30, "tok_s": 0.20, "ops": 0.20}
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    a = score({"quality": 0.9, "ttft": 0.9, "tok_s": 0.2, "ops": 0.5}, weights)
    b = score({"quality": 0.2, "ttft": 0.2, "tok_s": 0.9, "ops": 0.5}, weights)
    assert a > b


def test_default_weights_match_readme_and_sum_to_one():
    assert sc.DEFAULT_WEIGHTS == {"quality": 0.30, "ttft": 0.30, "tok_s": 0.20, "ops": 0.20}
    assert abs(sum(sc.DEFAULT_WEIGHTS.values()) - 1.0) < 1e-9


def test_score_clamps_axes_and_requires_all_weighted_axes():
    w = sc.DEFAULT_WEIGHTS
    assert score({"quality": 2, "ttft": 2, "tok_s": 2, "ops": 2}, w) == 1.0
    assert score({"quality": -1, "ttft": -1, "tok_s": -1, "ops": -1}, w) == 0.0
    try:
        score({"quality": 1.0}, w)
    except KeyError:
        pass
    else:
        raise AssertionError("missing axis must raise, not be scored as zero")


def test_normalization_helpers_are_ratio_to_best_in_unit_range():
    assert sc.norm_lower_better(2.0, 1.0) == 0.5
    assert sc.norm_lower_better(1.0, 1.0) == 1.0
    assert sc.norm_higher_better(50.0, 100.0) == 0.5
    assert sc.norm_higher_better(100.0, 100.0) == 1.0


def _rows(cold2k, cold8k, warm, tok, passed=True, ops=(4, 5)):
    return [
        {"kind": "cold_ttft", "target_tokens": 2048, "ttft_s": cold2k},
        {"kind": "cold_ttft", "target_tokens": 8192, "ttft_s": cold8k},
        {"kind": "batch", "level": 1, "aggregate_tok_s": tok},
        {"kind": "batch", "level": 4, "aggregate_tok_s": tok * 2},
        {"kind": "warm_ttft", "ttft_s": warm},
        {"kind": "quality", "pass": passed},
        {"kind": "ops", "items_pass": ops[0], "items_total": ops[1]},
    ]


def test_summarize_metrics_extracts_raw_axes():
    raw = sc.summarize_metrics(_rows(1.0, 4.0, 0.25, 30.0))
    assert abs(raw["ttft"] - 1.0) < 1e-9  # geometric mean of 1, 4, 0.25
    assert raw["tok_s"] == 45.0  # mean of c=1 (30) and c=4 (60)
    assert raw["quality"] == 1.0
    assert raw["ops"] == 0.8


def test_summarize_metrics_leaves_missing_axes_none_not_zero():
    raw = sc.summarize_metrics([{"kind": "quality", "pass": False}])
    assert raw["quality"] == 0.0
    assert raw["ttft"] is None and raw["tok_s"] is None and raw["ops"] is None


def test_build_scorecard_ranks_within_model_and_skips_incomplete(tmp_path):
    def write(engine, model, rows):
        d = tmp_path / "deep" / engine / model
        d.mkdir(parents=True)
        (d / "metrics.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))

    write("llamacpp", "m1", _rows(2.0, 8.0, 0.5, 50.0))
    write("vllm", "m1", _rows(1.0, 4.0, 0.25, 25.0))
    write("vllm", "m2", [{"kind": "quality", "pass": True}])

    runs = sc.collect_runs(tmp_path / "deep")
    assert {(r["engine"], r["model"]) for r in runs} == {("llamacpp", "m1"), ("vllm", "m1"), ("vllm", "m2")}
    table = sc.build_scorecard(runs)
    by = {(r["engine"], r["model"]): r for r in table}
    # vllm: best ttft (1.0) + same quality/ops, half the tok/s of llamacpp.
    assert by[("vllm", "m1")]["score"] > by[("llamacpp", "m1")]["score"]
    assert by[("vllm", "m2")]["score"] is None  # incomplete: not invented
    md = sc.render_markdown(table, sc.DEFAULT_WEIGHTS)
    assert "| vllm | m1 |" in md and "incomplete" in md
