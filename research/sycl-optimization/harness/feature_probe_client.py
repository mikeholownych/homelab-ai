#!/usr/bin/env python3
"""Runs on the aihost against a research llama-server on 127.0.0.1:<port> (NOT the gateway). Subcommands (JSON lines):
  slot1 <port>              cold ~18k-token prompt, then POST /slots/0?action=save (file a.bin)
  slot2 <port>              POST /slots/0?action=restore (file a.bin) into a FRESH server, then the same prompt: TTFT and cached tokens
  router <port> <model>...  one tiny chat per listed router model in order, with wall time (load/swap latency shows up in the first request of each switch)
"""
import json, os, sys, time, urllib.error, urllib.request

cmd, port, rest = sys.argv[1], sys.argv[2], sys.argv[3:]
base = f"http://127.0.0.1:{port}"
UNIT = "Synthetic neutral context for fork. "
PROMPT = UNIT * 3000


def post(path, body, timeout=1800):
    req = urllib.request.Request(base + path, json.dumps(body).encode(), {"content-type": "application/json"})
    t0 = time.monotonic()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r), round(time.monotonic() - t0, 2), 200
    except urllib.error.HTTPError as e:
        return {"error": e.read()[:200].decode(errors="replace")}, round(time.monotonic() - t0, 2), e.code


def chat(model=None):
    body = {"messages": [{"role": "user", "content": PROMPT + "\nReply briefly."}], "max_tokens": 16, "temperature": 0, "cache_prompt": True}
    if model:
        body["model"] = model
    return post("/v1/chat/completions", body)


if cmd == "slot1":
    r, secs, st = chat()
    t = r.get("timings", {})
    print(json.dumps({"step": "cold", "status": st, "wall_s": secs, "prompt_n": t.get("prompt_n"), "cache_n": t.get("cache_n")}), flush=True)
    r, secs, st = post("/slots/0?action=save", {"filename": "a.bin"})
    print(json.dumps({"step": "save", "status": st, "wall_s": secs, "resp": {k: r.get(k) for k in ("n_saved", "n_written", "timings")} if st == 200 else r}), flush=True)
elif cmd == "slot2":
    r, secs, st = post("/slots/0?action=restore", {"filename": "a.bin"})
    print(json.dumps({"step": "restore", "status": st, "wall_s": secs, "resp": {k: r.get(k) for k in ("n_restored", "n_read")} if st == 200 else r}), flush=True)
    r, secs, st = chat()
    t = r.get("timings", {})
    print(json.dumps({"step": "after-restore", "status": st, "wall_s": secs, "prompt_n": t.get("prompt_n"), "cache_n": t.get("cache_n"),
                      "prompt_ms": round(t.get("prompt_ms", 0))}), flush=True)
else:
    for model in rest:
        body = {"model": model, "messages": [{"role": "user", "content": "Say OK."}], "max_tokens": 8, "temperature": 0}
        r, secs, st = post("/v1/chat/completions", body)
        print(json.dumps({"model": model, "status": st, "wall_s": secs, "served": r.get("model"), "err": r.get("error") if st != 200 else None}), flush=True)
