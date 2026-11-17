#!/usr/bin/env python3
"""Runs on the aihost against a research llama-server (127.0.0.1:<port>, NOT the gateway). Fixed prompt set, temperature 0, thinking off.
One JSON line per prompt: sha256 of the generated text, token count, decode tokens/s from llama-server timings, draft acceptance if reported."""
import hashlib, json, sys, urllib.request
port = sys.argv[1]
PROMPTS = [
    "Write a Python function that merges two sorted lists into one sorted list, with a docstring and three unit tests.",
    "Explain in about 150 words how a B-tree differs from a binary search tree and when to prefer each.",
    "Write a Go function that reads a CSV file and returns the sum of the third column as a float64, handling errors.",
    "Refactor this to be clearer: def f(a):\n  r=[]\n  for i in range(len(a)):\n    if a[i]%2==0:\n      r.append(a[i]*2)\n  return r",
    "List the steps to roll back a bad systemd service deployment on Linux, as a numbered list with one command per step.",
    "Write a SQL query that returns the top 5 customers by total order value in the last 30 days, with the schema you assume.",
]
for i, p in enumerate(PROMPTS):
    body = json.dumps({"messages": [{"role": "user", "content": p}], "max_tokens": 256, "temperature": 0, "seed": 1,
                       "chat_template_kwargs": {"enable_thinking": False}, "cache_prompt": False}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", body,
                                         {"content-type": "application/json"}), timeout=600))
    text = r["choices"][0]["message"].get("content") or ""
    t = r.get("timings", {})
    print(json.dumps({"i": i, "sha": hashlib.sha256(text.encode()).hexdigest()[:16], "n": t.get("predicted_n"),
                      "tps": round(t.get("predicted_per_second", 0), 1), "draft_n": t.get("draft_n"),
                      "draft_accepted": t.get("draft_n_accepted"), "head": text[:60].replace("\n", " ")}), flush=True)
