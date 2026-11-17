#!/usr/bin/env python3
"""Runs on the aihost against a research engine on 127.0.0.1:<port> (NOT the gateway): 3 streamed ~1k-token requests, prints one JSON
line with TTFT, decode gap percentiles and token counts. Works against vLLM and llama-server OpenAI endpoints."""
import json, sys, time, urllib.request
port, model = sys.argv[1], sys.argv[2]
prompt = "Synthetic neutral context. " * 256 + "\nReply with two sentences."
for rep in range(3):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": 128, "temperature": 0,
                       "stream": True, "stream_options": {"include_usage": True}}).encode()
    t0 = time.monotonic(); first = last = None; gaps = []; usage = {}
    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", body,
                                {"content-type": "application/json"}), timeout=600) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            c = json.loads(line[5:]); usage = c.get("usage") or usage
            if any((ch.get("delta") or {}).get("content") for ch in c.get("choices") or []):
                now = time.monotonic()
                if first is None: first = now - t0
                else: gaps.append(now - last)
                last = now
    gaps.sort()
    print(json.dumps({"rep": rep, "ttft_s": round(first, 3) if first else None, "wall_s": round(time.monotonic() - t0, 2),
                      "gap_p50_ms": round(gaps[len(gaps) // 2] * 1000, 1) if gaps else None,
                      "completion_tokens": usage.get("completion_tokens"), "prompt_tokens": usage.get("prompt_tokens")}), flush=True)
