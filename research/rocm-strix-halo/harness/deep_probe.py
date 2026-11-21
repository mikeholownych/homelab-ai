#!/usr/bin/env python3
"""Phase 2c probes that engine_sweep_client.py does not cover. Runs on the lab host against
127.0.0.1:<port> (OpenAI-compatible). Emits one JSON line per measurement on stdout.

  deep_probe.py warm    <port> <model>   fixed ~2k-token prefix sent twice (different short tail);
                                         the 2nd request's TTFT is the warm-prefix TTFT
  deep_probe.py quality <port> <model>   tool-call contract probes (name, argument keys + types)

Row ``kind`` values match harness/scorecard.py (warm_ttft, quality).
"""
import json
import sys
import time
import urllib.request

PREFIX = "Synthetic neutral context line for prefix-cache probing. " * 205  # ~2k tokens, fixed text


def post(port, body, timeout=900):
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", json.dumps(body).encode(),
                                 {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def stream_ttft(port, model, prompt, max_tokens=8):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens,
                       "temperature": 0, "stream": True, "stream_options": {"include_usage": True}}).encode()
    t0 = time.monotonic()
    first, usage = None, {}
    req = urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", body, {"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=900) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            c = json.loads(line[5:])
            usage = c.get("usage") or usage
            if first is None and any(((ch.get("delta") or {}).get("content") or (ch.get("delta") or {}).get("reasoning_content")
                                      or (ch.get("delta") or {}).get("reasoning"))
                                     for ch in c.get("choices") or []):
                first = time.monotonic() - t0
    return first, usage


def warm(port, model):
    results = []
    for i, tail in enumerate(("\nReply with one word.", "\nReply with one short word, please.")):
        ttft, usage = stream_ttft(port, model, PREFIX + tail)
        results.append((ttft, usage))
    (t1, u1), (t2, u2) = results
    cached = (u2.get("prompt_tokens_details") or {}).get("cached_tokens")
    print(json.dumps({"kind": "warm_ttft", "prompt_tokens": u2.get("prompt_tokens"), "first_ttft_s": round(t1, 3) if t1 else None,
                      "ttft_s": round(t2, 3) if t2 else None, "cached_tokens": cached,
                      "speedup": round(t1 / t2, 2) if t1 and t2 else None}), flush=True)


def _tool(name, desc, props, required):
    return {"type": "function", "function": {"name": name, "description": desc,
                                              "parameters": {"type": "object", "properties": props, "required": required}}}


ECHO = _tool("echo", "Echo text", {"text": {"type": "string"}}, ["text"])
WEATHER = _tool("get_weather", "Get the weather for a city",
                {"city": {"type": "string"}, "days": {"type": "integer"}, "unit": {"type": "string", "enum": ["celsius", "fahrenheit"]}},
                ["city", "days", "unit"])
READ = _tool("read_file", "Read a file from the workspace", {"path": {"type": "string"}}, ["path"])
GREP = _tool("grep_repo", "Search the repository for a pattern", {"pattern": {"type": "string"}, "max_results": {"type": "integer"}},
             ["pattern"])

# (probe name, user prompt, tools, expected tool name, checker(args) -> bool)
PROBES = [
    ("echo_exact", "Call tool echo with text=ping, then stop.", [ECHO], "echo", lambda a: a.get("text") == "ping"),
    ("typed_args", "What's the weather in Paris for the next 3 days, in celsius? Use the tool.", [WEATHER], "get_weather",
     lambda a: str(a.get("city", "")).lower() == "paris" and a.get("days") == 3 and a.get("unit") == "celsius"),
    ("select_tool", "Open the file src/main.py so I can read it. Use a tool.", [GREP, READ, ECHO], "read_file",
     lambda a: a.get("path") == "src/main.py"),
    ("optional_int", "Search the repo for the pattern TODO and return at most 5 results. Use a tool.", [READ, GREP], "grep_repo",
     lambda a: a.get("pattern") == "TODO" and a.get("max_results") == 5),
]


def quality(port, model):
    for name, prompt, tools, want, check in PROBES:
        row = {"kind": "quality", "probe": name, "pass": False}
        try:
            body = post(port, {"model": model, "messages": [{"role": "user", "content": prompt}], "tools": tools,
                               "tool_choice": "auto", "max_tokens": 2048, "temperature": 0})
            msg = body["choices"][0]["message"]
            calls = msg.get("tool_calls") or []
            row["tool_calls"] = len(calls)
            if calls:
                fn = calls[0]["function"]
                args = json.loads(fn["arguments"]) if isinstance(fn["arguments"], str) else fn["arguments"]
                row.update(tool=fn["name"], arguments=args)
                row["pass"] = fn["name"] == want and bool(check(args))
            else:
                row["content"] = (msg.get("content") or "")[:200]
        except Exception as exc:  # recorded as a failed probe, not hidden
            row["error"] = f"{type(exc).__name__}: {exc}"[:300]
        print(json.dumps(row), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 4 or sys.argv[1] not in ("warm", "quality"):
        sys.exit(__doc__)
    {"warm": warm, "quality": quality}[sys.argv[1]](sys.argv[2], sys.argv[3])
