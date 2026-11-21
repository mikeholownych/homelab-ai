#!/usr/bin/env bash
# Usage: smoke_openai.sh BASE_URL MODEL PROMPT_JSON OUT_JSON
# POST PROMPT_JSON (with "model" merged in) to BASE_URL/v1/chat/completions.
# Writes {http_status, seconds, ok, tools_supported?, body} to OUT_JSON.
# Exit 0 on HTTP 200 with a non-empty choices array. For prompts that carry
# "tools": a missing tool_calls does NOT fail the smoke; it records
# tools_supported=false (the chat path itself passed).
set -euo pipefail

if [[ $# -ne 4 ]]; then
  echo "usage: $0 BASE_URL MODEL PROMPT_JSON OUT_JSON" >&2
  exit 64
fi
BASE_URL="${1%/}" MODEL="$2" PROMPT_JSON="$3" OUT_JSON="$4"
TIMEOUT="${SMOKE_TIMEOUT:-300}"

tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT

python3 - "$PROMPT_JSON" "$MODEL" >"$tmp/req.json" <<'PY'
import json, sys
body = json.load(open(sys.argv[1]))
body["model"] = sys.argv[2]
print(json.dumps(body))
PY

set +e
curl -sS -o "$tmp/resp.body" -w '%{http_code} %{time_total}' --max-time "$TIMEOUT" \
  -H 'Content-Type: application/json' --data-binary @"$tmp/req.json" \
  "$BASE_URL/v1/chat/completions" >"$tmp/meta" 2>"$tmp/curl.err"
curl_rc=$?
set -e
[[ -s "$tmp/meta" ]] || echo "000 0" >"$tmp/meta"
[[ -f "$tmp/resp.body" ]] || : >"$tmp/resp.body"

python3 - "$tmp" "$BASE_URL" "$MODEL" "$PROMPT_JSON" "$OUT_JSON" "$curl_rc" <<'PY'
import json, sys
tmp, base_url, model, prompt_path, out_path, curl_rc = sys.argv[1:7]
status, seconds = open(f"{tmp}/meta").read().split()
raw = open(f"{tmp}/resp.body", errors="replace").read()
try:
    body = json.loads(raw)
except ValueError:
    body = raw
prompt = json.load(open(prompt_path))
choices = body.get("choices") if isinstance(body, dict) else None
chat_ok = status == "200" and isinstance(choices, list) and len(choices) > 0
out = {
    "base_url": base_url,
    "model": model,
    "prompt": prompt_path,
    "http_status": int(status),
    "seconds": float(seconds),
    "curl_exit": int(curl_rc),
    "curl_stderr": open(f"{tmp}/curl.err", errors="replace").read().strip(),
    "ok": chat_ok,
    "body": body,
}
if "tools" in prompt:
    msg = (choices[0].get("message") or {}) if chat_ok else {}
    out["tools_supported"] = bool(chat_ok and msg.get("tool_calls"))
with open(out_path, "w") as fh:
    json.dump(out, fh, indent=2)
    fh.write("\n")
sys.exit(0 if chat_ok else 1)
PY
