"""Rollback-drill smoke: /v1/models view and three requests through the TLS gateway. Token on stdin; metadata only."""
import json, sys, time, urllib.error, urllib.request

key = sys.stdin.read().strip()
base = "https://10.0.8.5:8443"
H = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
models = json.load(urllib.request.urlopen(urllib.request.Request(base + "/v1/models", headers=H), timeout=30))["data"]
view = {m["id"]: {"serving": [(s["model_id"], s["artifact_digest"]) for s in m["serving"]], "reasoning": m["reasoning"],
                  "reasoning_capability": m["capabilities"]["reasoning"]} for m in models}
out = {"label": sys.argv[1], "at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), "models": view, "requests": []}
for alias, profile in (("engineering/deep", None), ("engineering/deep", "off"), ("engineering/b0", None)):
    headers = dict(H, **({"X-AIHost-Reasoning": profile} if profile else {}))
    body = {"model": alias, "messages": [{"role": "user", "content": "Reply with the single word READY."}], "max_tokens": 6000}
    rec = {"alias": alias, "reasoning_profile": profile or "default"}
    try:
        req = urllib.request.Request(base + "/v1/chat/completions", json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=600) as r:
            d, hd = json.load(r), r.headers
        m = d["choices"][0]["message"]
        rec.update(status=200, finish=d["choices"][0]["finish_reason"], content=(m.get("content") or "").strip()[:20],
                   reasoning_present=bool(m.get("reasoning_content")), served_model=hd.get("X-AIHost-Served-Model"),
                   route=hd.get("X-AIHost-Route"))
    except urllib.error.HTTPError as e:
        rec.update(status=e.code, error=json.loads(e.read() or b"{}"))
    out["requests"].append(rec)
print(json.dumps(out, indent=1))
