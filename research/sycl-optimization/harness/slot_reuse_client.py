#!/usr/bin/env python3
"""Runs on the aihost against a research llama-server (127.0.0.1:<port>, NOT the gateway): cold / continuation / fork-mid-prompt /
original-again on one ~18k-token prompt. Prints one JSON line per step with prompt_n (computed), cache_n (reused) and wall seconds."""
import json, sys, time, urllib.request
port = sys.argv[1]
unit = "Synthetic neutral context for fork. "
base = unit * 3000
steps = [("cold", base), ("continuation", base + "\nNext question: summarise the above in one line."),
         ("fork-mid-prompt", unit * 1500 + "Different second half. " * 1500), ("original-again", base)]
for name, text in steps:
    body = json.dumps({"messages": [{"role": "user", "content": text + "\nReply briefly."}], "max_tokens": 16, "temperature": 0,
                       "cache_prompt": True}).encode()
    t0 = time.monotonic()
    r = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", body,
                                         {"content-type": "application/json"}), timeout=900))
    t = r.get("timings", {})
    print(json.dumps({"step": name, "wall_s": round(time.monotonic() - t0, 2), "prompt_n": t.get("prompt_n"),
                      "cache_n": t.get("cache_n"), "prompt_ms": round(t.get("prompt_ms", 0))}), flush=True)
