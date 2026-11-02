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
