#!/usr/bin/env python3
"""Runs on the aihost against an engine on 127.0.0.1:<port> (NOT the gateway). Append-only agent pattern: ONE growing conversation of 8 steps,
each step re-sends the whole history plus ~330 new tokens (a ~6k-token base first). Shows what each engine's prefix cache does per step.
JSON line per step: prompt tokens, cached tokens when the engine reports them, TTFT, wall."""
import json, random, sys, time, urllib.request
port, model = sys.argv[1], sys.argv[2]
nonce = f"[{random.random()}] "
history = nonce + "Synthetic neutral context line. " * 1450
for step in range(1, 9):
    if step > 1:
        history += f"\nTurn {step}: " + "More synthetic neutral context line. " * 80
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": history + "\nReply with one word."}], "max_tokens": 8,
                       "temperature": 0, "stream": True, "stream_options": {"include_usage": True}}).encode()
    t0 = time.monotonic(); first = None; usage = {}
    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", body, {"content-type": "application/json"}), timeout=900) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            c = json.loads(line[5:]); usage = c.get("usage") or usage
            if first is None and any(((ch.get("delta") or {}).get("content") or (ch.get("delta") or {}).get("reasoning_content")) for ch in c.get("choices") or []):
                first = time.monotonic() - t0
    details = usage.get("prompt_tokens_details") or {}
    print(json.dumps({"step": step, "prompt_tokens": usage.get("prompt_tokens"), "cached_tokens": details.get("cached_tokens"),
                      "ttft_s": round(first, 2) if first else None, "wall_s": round(time.monotonic() - t0, 2)}), flush=True)
