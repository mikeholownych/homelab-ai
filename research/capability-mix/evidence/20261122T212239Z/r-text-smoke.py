import json, sys, time, urllib.request

BASE = sys.argv[1]
MODEL = sys.argv[2]
tools_spec = json.load(open(sys.argv[3]))
out = {"base": BASE, "model": MODEL}


def post(body, timeout=900):
    req = urllib.request.Request(BASE + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t = time.time()
    r = json.load(urllib.request.urlopen(req, timeout=timeout))
    return r, time.time() - t


def stream_ttft(body):
    body = dict(body, stream=True)
    req = urllib.request.Request(BASE + "/v1/chat/completions", json.dumps(body).encode(),
                                 {"Content-Type": "application/json"})
    t = time.time()
    ttft = None
    n = 0
    with urllib.request.urlopen(req, timeout=900) as resp:
        for line in resp:
            line = line.strip()
            if not line.startswith(b"data:") or line.endswith(b"[DONE]"):
                continue
            d = json.loads(line[5:])
            ch = d["choices"][0]["delta"] if d.get("choices") else {}
            if ch.get("content") or ch.get("reasoning_content"):
                if ttft is None:
                    ttft = time.time() - t
                n += 1
    return ttft, n, time.time() - t


# 1. chat
r, dt = post({"model": MODEL, "messages": [{"role": "user", "content": "Reply with exactly: pong"}],
              "max_tokens": 256, "temperature": 0})
m = r["choices"][0]["message"]
out["chat"] = {"ok": bool((m.get("content") or "").strip()), "content": m.get("content"),
               "reasoning_len": len(m.get("reasoning_content") or ""), "seconds": round(dt, 2),
               "timings": r.get("timings")}

# 2. tools round trip
msgs = list(tools_spec["messages"])
body = {"model": MODEL, "messages": msgs, "tools": tools_spec["tools"], "max_tokens": 2048, "temperature": 0}
r, dt1 = post(body)
am = r["choices"][0]["message"]
tcs = am.get("tool_calls") or []
out["tools"] = {"first_finish": r["choices"][0]["finish_reason"], "tool_calls": tcs, "seconds_1": round(dt1, 2)}
if tcs:
    tc = tcs[0]
    msgs.append({"role": "assistant", "content": am.get("content") or "", "tool_calls": tcs})
    msgs.append({"role": "tool", "tool_call_id": tc["id"], "content": json.dumps(tools_spec["tool_result"])})
    r2, dt2 = post({"model": MODEL, "messages": msgs, "tools": tools_spec["tools"], "max_tokens": 2048,
                    "temperature": 0})
    final = r2["choices"][0]["message"].get("content") or ""
    out["tools"].update({"final": final, "seconds_2": round(dt2, 2),
                         "schema_valid": tc["function"]["name"] == "calculator"
                         and "expression" in json.loads(tc["function"]["arguments"]),
                         "pass": tools_spec["expect_final_contains"] in final})
else:
    out["tools"]["pass"] = False

# 3. long prompt (~33k tokens) -> TTFT + OOM check
filler = ("The quick brown fox jumps over the lazy dog near the river bank number %d. ")
text = "".join(filler % i for i in range(2300))
body = {"model": MODEL, "messages": [{"role": "user", "content": text + "\nIn one word, what animal jumps?"}],
        "max_tokens": 64, "temperature": 0}
try:
    ttft, n, total = stream_ttft(body)
    out["long_ctx"] = {"approx_prompt_chars": len(text), "ttft_s": round(ttft, 2) if ttft else None,
                       "chunks": n, "total_s": round(total, 2)}
except Exception as e:
    out["long_ctx"] = {"error": repr(e)}

# 4. short TTFT / decode speed
body = {"model": MODEL, "messages": [{"role": "user", "content": "Write 150 words about GPUs."}],
        "max_tokens": 300, "temperature": 0}
ttft, n, total = stream_ttft(body)
out["short_stream"] = {"ttft_s": round(ttft, 2) if ttft else None, "chunks": n, "total_s": round(total, 2)}
r, dt = post(body)
out["short_timings"] = r.get("timings")
out["usage"] = r.get("usage")
print(json.dumps(out, indent=2))
