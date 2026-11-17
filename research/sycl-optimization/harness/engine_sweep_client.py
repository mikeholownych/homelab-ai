#!/usr/bin/env python3
"""Runs on the aihost against a research engine on 127.0.0.1:<port> (NOT the gateway), OpenAI-compatible streaming.
  engine_sweep_client.py batch   <port> <model> <level> [<level> ...]   aggregate decode throughput at N concurrent streams (1k-token prompts, 128 tokens out)
  engine_sweep_client.py longctx <port> <model> <tokens> [<tokens> ...] cold prefill: TTFT for one prompt of about that many tokens (unique prefix, 16 tokens out)
One JSON line per level / size."""
import concurrent.futures, json, random, sys, time, urllib.request

mode, port, model, args = sys.argv[1], sys.argv[2], sys.argv[3], [int(a) for a in sys.argv[4:]]


def stream(prompt, max_tokens):
    body = json.dumps({"model": model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens, "temperature": 0,
                       "stream": True, "stream_options": {"include_usage": True}}).encode()
    t0 = time.monotonic(); first = None; usage = {}
    with urllib.request.urlopen(urllib.request.Request(f"http://127.0.0.1:{port}/v1/chat/completions", body,
                                {"content-type": "application/json"}), timeout=1800) as r:
        for line in r:
            line = line.decode().strip()
            if not line.startswith("data:") or line == "data: [DONE]":
                continue
            c = json.loads(line[5:]); usage = c.get("usage") or usage
            if first is None and any(((ch.get("delta") or {}).get("content") or (ch.get("delta") or {}).get("reasoning_content"))
                                     for ch in c.get("choices") or []):   # thinking models stream reasoning tokens first
                first = time.monotonic() - t0
    return {"ttft": first, "wall": time.monotonic() - t0, "completion": usage.get("completion_tokens") or 0, "prompt": usage.get("prompt_tokens")}


def pct(v, q):
    v = sorted(x for x in v if x is not None)
    return round(v[min(len(v) - 1, int(q * len(v)))], 3) if v else None


if mode == "batch":
    stream("warm up " * 50, 8)
    for level in args:
        nonce = lambda: f"[{random.random()}] "
        t0 = time.monotonic()
        with concurrent.futures.ThreadPoolExecutor(max_workers=level) as pool:
            rows = list(pool.map(lambda i: stream(nonce() + "Synthetic neutral context. " * 250 + "\nWrite a short paragraph about databases.", 128), range(level * 2)))
        wall = time.monotonic() - t0
        total = sum(r["completion"] for r in rows)
        print(json.dumps({"mode": "batch", "level": level, "requests": len(rows), "completion_tokens": total, "wall_s": round(wall, 2),
                          "aggregate_tok_s": round(total / wall, 1), "ttft_p50": pct([r["ttft"] for r in rows], .5),
                          "ttft_p95": pct([r["ttft"] for r in rows], .95)}), flush=True)
else:
    for size in args:
        text = f"[{random.random()}] " + "Synthetic neutral context. " * int(size / 4.1)
        r = stream(text + "\nReply with one word.", 16)
        print(json.dumps({"mode": "longctx", "target_tokens": size, "prompt_tokens": r["prompt"], "ttft_s": round(r["ttft"], 2) if r["ttft"] else None,
                          "prefill_tok_s": round(r["prompt"] / r["ttft"], 0) if r["prompt"] and r["ttft"] else None}), flush=True)
