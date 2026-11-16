"""Pure-function checks for the long-context probe: deterministic filler, unique-first nonce, growing size."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "evaluations" / "engx"))
import long_context_probe as probe  # noqa: E402


def test_prompt_is_deterministic_apart_from_the_nonce_and_grows_with_target():
    a, b = probe.build_prompt(2000, "n1"), probe.build_prompt(2000, "n2")
    assert a != b and a.split("\n", 1)[1] == b.split("\n", 1)[1]
    assert a.startswith("Request id n1.")
    assert len(probe.build_prompt(8000, "n1")) > 3 * len(a)


def test_run_one_retries_throttling_and_derives_rates(monkeypatch):
    calls = []

    class Fake:
        def chat(self, messages, *, stream, **controls):
            calls.append(1)
            if len(calls) == 1:
                return {"passed": False, "http_status": 429, "seconds": 0.0}, {}
            return {"passed": True, "http_status": 200, "ttft_seconds": 2.0, "seconds": 3.0,
                    "usage": {"prompt_tokens": 2000, "completion_tokens": 11}}, {}

    monkeypatch.setattr(probe.time, "sleep", lambda s: None)
    row = probe.run_one(Fake(), 2000, "n")
    assert row["throttled_retries"] == 1 and row["prefill_tokens_per_second"] == 1000.0
    assert row["decode_tokens_per_second"] == 10.0
