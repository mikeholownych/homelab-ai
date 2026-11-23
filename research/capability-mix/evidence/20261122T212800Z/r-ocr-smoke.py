#!/usr/bin/env python3
"""R-ocr smoke: send fixture to llama-server (GLM-OCR) and check for the invoice total.
Run on ai-ms-s1-max-01 against the temp loopback port."""
import base64, json, sys, time, urllib.request

URL = "http://127.0.0.1:8191/v1/chat/completions"
IMG = sys.argv[1] if len(sys.argv) > 1 else "/tmp/invoice_sample.png"
PROMPT = "Text Recognition:"
b64 = base64.b64encode(open(IMG, "rb").read()).decode()
body = {
    "messages": [{"role": "user", "content": [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + b64}},
        {"type": "text", "text": PROMPT}]}],
    "temperature": 0, "max_tokens": 256,
}
t0 = time.time()
req = urllib.request.Request(URL, json.dumps(body).encode(), {"Content-Type": "application/json"})
r = json.load(urllib.request.urlopen(req, timeout=300))
dt = time.time() - t0
text = r["choices"][0]["message"]["content"]
out = {"prompt": PROMPT, "text": text, "elapsed_s": round(dt, 2),
       "usage": r.get("usage"), "timings": r.get("timings"),
       "pass": "42.00" in text}
print(json.dumps(out, indent=2))
sys.exit(0 if out["pass"] else 1)
