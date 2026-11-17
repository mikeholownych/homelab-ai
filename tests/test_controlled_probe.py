import importlib.util
from pathlib import Path


def module(name):
    path = Path(__file__).parents[1] / "evaluations/engx" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_drm_sampler_deduplicates_handles_without_claiming_device_free_memory(tmp_path):
    probe = module("sample_drm_memory")
    pid = tmp_path / "123"
    info = pid / "fdinfo"
    info.mkdir(parents=True)
    text = "drm-pdev: 0000:51:00.0\ndrm-client-id: 42\ndrm-resident-vram0: 123 KiB\n"
    (info / "3").write_text(text)
    (info / "4").write_text(text)
    result = probe.clients(pid)
    assert len(result) == 1
    assert result[0]["resident_bytes"]["drm-resident-vram0"] == 123 * 1024
    assert "free_bytes" not in result[0]


def test_summary_does_not_turn_rejections_into_a_speedup():
    probe = module("controlled_probe")
    result = probe.summarize([{"passed": True, "seconds": 10, "ttft_seconds": 2},
                              {"passed": False, "seconds": 0, "failure_class": "pool_unavailable"}])
    assert result["median_seconds"] == 10
    assert result["passed"] == 1 and result["requests"] == 2
    assert result["failure_classes"] == {"pool_unavailable": 1}
    assert probe.cached_tokens({"prompt_tokens": 100}) is None
    assert probe.cached_tokens({"prompt_tokens_details": {"cached_tokens": 50}}) == 50


def test_multiturn_probe_stops_on_extra_or_malformed_tool_calls():
    probe = module("controlled_probe")

    class WrongGateway:
        calls = 0

        def chat(self, *args, **kwargs):
            self.calls += 1
            return {"passed": True, "seconds": 1}, {"choices": [{"finish_reason": "tool_calls", "message": {
                "tool_calls": [{"id": "1", "function": {"name": "read_stock", "arguments": "{}"}},
                               {"id": "2", "function": {"name": "reserve_stock", "arguments": "{}"}}]}}]}

    gateway = WrongGateway()
    result = probe.stateful_tool_case(gateway, 2)
    assert not result["passed"] and gateway.calls == 1
    assert result["turns"][0]["failure_class"] == "tool_contract"


def test_multiturn_probe_grades_tool_results_and_final_state():
    probe = module("controlled_probe")

    class GoodGateway:
        def chat(self, messages, **kwargs):
            count = len(messages)
            if count == 2:
                message = {"tool_calls": [{"id": "read", "function": {"name": "read_stock", "arguments": "{}"}}]}
            elif count == 4:
                assert '"available": 10' in messages[-1]["content"]
                message = {"tool_calls": [{"id": "reserve", "function": {"name": "reserve_stock", "arguments": '{"quantity":2}'}}]}
            else:
                assert '"receipt": "RESERVED-2"' in messages[-1]["content"]
                message = {"content": "RESERVED-2"}
            return {"passed": True, "seconds": 1}, {"choices": [{"message": message,
                    "finish_reason": "tool_calls" if "tool_calls" in message else "stop"}]}

    assert probe.stateful_tool_case(GoodGateway(), 2)["passed"]


def test_chat_rows_record_finish_reason_truncation_and_output_rate(monkeypatch):
    import io
    import json as _json
    probe = module("controlled_probe")

    class Resp(io.BytesIO):
        status = 200
        headers = {"X-AIHost-Cache": "BYPASS"}
        def __enter__(self): return self
        def __exit__(self, *a): return False

    body = {"choices": [{"message": {"content": "x"}, "finish_reason": "length"}],
            "usage": {"completion_tokens": 128, "prompt_tokens": 10}}
    monkeypatch.setattr(probe.urllib.request, "urlopen", lambda *a, **k: Resp(_json.dumps(body).encode()))
    gateway = probe.Gateway("https://gw.invalid", "m", "k", None)
    row, _ = gateway.chat([{"role": "user", "content": "hi"}])
    assert row["finish_reason"] == "length" and row["truncated"] is True
    assert row["output_tokens_per_second"] > 0


def test_gateway_load_summaries_and_bounds():
    load = module("gateway_load")
    assert sum(c * load.PER_LEVEL for c in load.LEVELS) + 3 <= load.MAX_REQUESTS
    rows = [{"status": 200, "ttft_seconds": 0.1 * i, "chunk_gaps_seconds": [0.01, 0.02], "finish_reason": "stop",
             "seconds": 1.0, "tpot_seconds": 0.02} for i in range(1, 5)]
    rows.append({"status": 429, "ttft_seconds": None, "chunk_gaps_seconds": [], "finish_reason": None, "seconds": 0.01})
    s = load.summarize(rows)
    assert s["statuses"] == {"200": 4, "429": 1} and s["ttft_max"] == 0.4 and s["gap_p99"] == 0.02
    assert "chunk_gaps_seconds" not in load.strip(rows[0]) and load.strip(rows[0])["chunk_gap_count"] == 2


def test_gateway_load_alternate_runs_two_rounds_over_three_distinct_prefixes(tmp_path, monkeypatch):
    load = module("gateway_load")
    seen = []
    def fake(gateway, text, max_tokens=128):
        seen.append(text[:16])
        return {"status": 200, "chunk_gaps_seconds": [], "cached_prompt_tokens": 0}
    monkeypatch.setattr(load, "stream_request", fake)
    result = load.alternate(object(), {}, tmp_path / "o.json")
    assert len(seen) == 6 and len(set(seen)) == 3 and seen[:3] == seen[3:]
    assert [r["round"] for r in result["alternate"]] == [1, 1, 1, 2, 2, 2]


def test_gateway_load_fork_steps(tmp_path, monkeypatch):
    load = module("gateway_load")
    monkeypatch.setattr(load, "stream_request", lambda g, t, max_tokens=128: {"status": 200, "chunk_gaps_seconds": [], "len": len(t)})
    result = load.fork(object(), {}, tmp_path / "o.json")
    assert [r["step"] for r in result["fork"]] == ["cold", "continuation", "fork-mid-prompt", "original-again"]


def test_gateway_load_replay_plan_picks_successive_tool_call_cuts():
    load = module("gateway_load")
    msgs = [{"role": "user", "content": "go"}]
    for n in range(5):
        msgs.append({"role": "assistant", "content": "", "tool_calls": [
            {"function": {"name": "read_file", "arguments": "{}"}}]})
        msgs.append({"role": "tool", "content": "ok"})
    digest, plan = load.replay_plan([("s.json", msgs)], steps=3)
    assert len(digest) == 12 and 1 <= len(plan) <= 3
    assert [p[0] for p in plan] == sorted(p[0] for p in plan) and plan[0][2][0]["function"]["name"] == "read_file"
