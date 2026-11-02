#!/usr/bin/env python3
"""Verify live cache controls through the normal TLS gateway; credential on stdin."""
import hashlib
import json
import ssl
import sys
import urllib.request
import uuid
from datetime import datetime, timezone


def main():
    credentials = json.load(sys.stdin)
    context = ssl.create_default_context(cafile="/home/mike/.config/nexus/t5820-gateway-ca.crt")
    headers = {"Content-Type": "application/json", "Authorization": "Bearer " + credentials["qualification"],
               "X-AIHost-Reasoning": "off"}
    nonce = uuid.uuid4().hex
    rows = []

    def check(body, expected_cache, expected_answer, extra=None):
        request = urllib.request.Request("https://10.0.8.5:8443/v1/chat/completions",
                                         json.dumps(body).encode(), {**headers, **(extra or {})})
        with urllib.request.urlopen(request, context=context, timeout=600) as response:
            data = json.load(response)
            choice = data["choices"][0]
            answer = (choice["message"].get("content") or "").strip()
            row = {"expected_cache": expected_cache, "observed_cache": response.headers.get("X-AIHost-Cache"),
                   "correct_answer": answer == expected_answer, "finish": choice.get("finish_reason"),
                   "request_sha256": hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()}
            row["passed"] = row["observed_cache"] == expected_cache and row["correct_answer"] and row["finish"] == "stop"
            rows.append(row)

    body = {"model": "engineering/lead", "messages": [
        {"role": "system", "content": "Reply with exactly READY."},
        {"role": "user", "content": "Qualification nonce " + nonce + ". Reply with exactly READY."}],
        "temperature": 0, "max_tokens": 128}
    check(body, "MISS", "READY")
    check(body, "HIT", "READY")
    check(body, "BYPASS", "READY", {"cache-control": "no-store"})
    check(body, "BYPASS", "READY", {"x-aihost-cache": "bypass"})
    check({**body, "max_tokens": 64}, "MISS", "READY")
    for operator, answer in [("==", "EQ"), ("!=", "NEQ")]:
        check({**body, "messages": [
            {"role": "system", "content": "Reply EQ if the expression uses ==. Reply NEQ if it uses !=. No other text."},
            {"role": "user", "content": "Nonce " + nonce + "\nExpression: x " + operator + " y"}]}, "MISS", answer)
    print(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "checks": rows,
                      "passed": all(r["passed"] for r in rows)}, indent=2))
    if not all(r["passed"] for r in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
