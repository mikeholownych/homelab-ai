#!/usr/bin/env python3
"""Small gateway-only benchmark: response-cache bypass, SSE latency and tool state.

Credentials arrive on stdin. Results retain hashes and verdicts, never generated
reasoning or conversation text. Prefix reuse is reported only when measured.
This synthetic smoke corpus is not BFCL or full engineering qualification.
"""
import argparse
import concurrent.futures
import hashlib
import json
import ssl
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True).encode()).hexdigest()


def cached_tokens(usage):
    details = usage.get("prompt_tokens_details") or {}
    return details.get("cached_tokens")  # Absence is unknown, not zero.


def summarize(rows):
    passed = [r for r in rows if r.get("passed")]
    return {"requests": len(rows), "passed": len(passed),
            "median_seconds": statistics.median(r["seconds"] for r in passed) if passed else None,
            "median_ttft_seconds": statistics.median(r["ttft_seconds"] for r in passed
                                                    if r.get("ttft_seconds") is not None)
            if any(r.get("ttft_seconds") is not None for r in passed) else None,
            "failure_classes": {k: sum(r.get("failure_class") == k for r in rows)
                                for k in sorted({r["failure_class"] for r in rows if r.get("failure_class")})}}


class Gateway:
    def __init__(self, base, model, key, ca, timeout=600):
        if not base.startswith("https://"):
            raise ValueError("An authenticated TLS gateway is required")
        self.base, self.model, self.timeout = base.rstrip("/"), model, timeout
        self.context = ssl.create_default_context(cafile=ca)
        self.headers = {"Content-Type": "application/json", "Authorization": "Bearer " + key,
                        "Cache-Control": "no-store", "X-AIHost-Cache": "bypass", "X-AIHost-Reasoning": "off"}

    def models(self):
        req = urllib.request.Request(self.base + "/v1/models", headers=self.headers)
        with urllib.request.urlopen(req, context=self.context, timeout=30) as response:
            return next(m for m in json.load(response)["data"] if m["id"] == self.model)

    def chat(self, messages, *, stream=False, **controls):
        body = {"model": self.model, "messages": messages, "temperature": 0, "max_tokens": 128,
                "cache": False, "stream": stream, **controls}
        if stream:
            body["stream_options"] = {"include_usage": True}
        req = urllib.request.Request(self.base + "/v1/chat/completions", json.dumps(body).encode(), self.headers)
        start = time.monotonic()
        row = {"request_sha256": digest(body), "stream": stream, "ttft_seconds": None,
               "prefix_cache_state": "uncontrolled", "passed": False}
        try:
            with urllib.request.urlopen(req, context=self.context, timeout=self.timeout) as response:
                row.update(http_status=response.status, response_cache=response.headers.get("X-AIHost-Cache"))
                if row["response_cache"] != "BYPASS":
                    row.update(failure_class="response_cache_not_bypassed", seconds=time.monotonic() - start)
                    return row, {}
                if not stream:
                    data = json.load(response)
                else:
                    text, finish, usage = [], None, {}
                    for line in response:
                        line = line.decode().strip()
                        if not line.startswith("data:") or line == "data: [DONE]":
                            continue
                        chunk = json.loads(line[5:])
                        usage = chunk.get("usage") or usage
                        for choice in chunk.get("choices") or []:
                            delta = choice.get("delta") or {}
                            if delta.get("content"):
                                if row["ttft_seconds"] is None:
                                    row["ttft_seconds"] = time.monotonic() - start
                                text.append(delta["content"])
                            finish = choice.get("finish_reason") or finish
                    data = {"choices": [{"message": {"content": "".join(text)}, "finish_reason": finish}],
                            "usage": usage}
                row.update(seconds=time.monotonic() - start, usage=data.get("usage") or {})
                row["cached_prompt_tokens"] = cached_tokens(row["usage"])
                row["passed"] = True
                return row, data
        except urllib.error.HTTPError as error:
            raw = error.read()
            try:
                failure = (json.loads(raw).get("error") or {}).get("type")
            except ValueError:
                failure = None
            row.update(http_status=error.code, failure_class=failure or "http_error")
        except (OSError, ValueError) as error:
            row.update(failure_class=type(error).__name__)
        row["seconds"] = time.monotonic() - start
        return row, {}


def latency_request(gateway, label, stream, prefix):
    messages = [{"role": "system", "content": "Reply with exactly READY."},
                {"role": "user", "content": prefix + "\nReply with exactly READY."}]
    row, data = gateway.chat(messages, stream=stream)
    if row["passed"]:
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        row["passed"] = (message.get("content") or "").strip() == "READY" and choice.get("finish_reason") == "stop"
        if not row["passed"]:
            row["failure_class"] = "output_contract"
    row["label"] = label
    return row


def stateful_tool_case(gateway, quantity):
    """Two forced calls with a synthetic tool-result transition and a graded final answer."""
    functions = [
        {"type": "function", "function": {"name": "read_stock", "description": "Read available stock.",
         "parameters": {"type": "object", "properties": {}, "additionalProperties": False}}},
        {"type": "function", "function": {"name": "reserve_stock", "description": "Reserve the requested quantity.",
         "parameters": {"type": "object", "properties": {"quantity": {"type": "integer"}},
                        "required": ["quantity"], "additionalProperties": False}}},
    ]
    messages = [{"role": "system", "content": "Use the tools as instructed. Do not invent tool results."},
                {"role": "user", "content": f"Read stock, then reserve {quantity} units. After the reservation, reply with only its receipt."}]
    turns = []
    for index, (name, arguments, result) in enumerate([
        ("read_stock", {}, {"available": 10}),
        ("reserve_stock", {"quantity": quantity}, {"receipt": f"RESERVED-{quantity}"}),
    ]):
        row, data = gateway.chat(messages, tools=functions,
                                 tool_choice={"type": "function", "function": {"name": name}},
                                 parallel_tool_calls=False)
        choice = (data.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        calls = message.get("tool_calls") or []
        try:
            valid = (len(calls) == 1 and calls[0]["function"]["name"] == name
                     and json.loads(calls[0]["function"]["arguments"]) == arguments
                     and bool(calls[0].get("id")) and choice.get("finish_reason") == "tool_calls")
        except (KeyError, TypeError, ValueError):
            valid = False
        row["passed"] = row["passed"] and valid
        row["turn"] = index
        if not row["passed"]:
            row.setdefault("failure_class", "tool_contract")
        turns.append(row)
        if not row["passed"]:
            return {"quantity": quantity, "passed": False, "turns": turns}
        messages.extend([message, {"role": "tool", "tool_call_id": calls[0]["id"], "content": json.dumps(result)}])
    row, data = gateway.chat(messages, tools=functions, tool_choice="none")
    choice = (data.get("choices") or [{}])[0]
    message = choice.get("message") or {}
    row["passed"] = (row["passed"] and not message.get("tool_calls")
                     and (message.get("content") or "").strip() == f"RESERVED-{quantity}"
                     and choice.get("finish_reason") == "stop")
    if not row["passed"]:
        row.setdefault("failure_class", "final_state_contract")
    row["turn"] = 2
    turns.append(row)
    return {"quantity": quantity, "passed": row["passed"], "turns": turns}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ca", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--concurrency", type=int, choices=[1, 2], default=1)
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=3)
    args = parser.parse_args()
    credentials = json.load(sys.stdin)
    gateway = Gateway(args.base, args.model, credentials["qualification"], args.ca)
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "model": gateway.models(),
              "concurrency": args.concurrency, "repeats": args.repeats, "reasoning": "off",
              "corpus": "synthetic-state-and-latency-v1", "latency": [], "tool_cases": [],
              "limitations": ["Not BFCL", "Not full engineering qualification",
                              "Prefix cache is uncontrolled; no cold/warm performance claim"]}
    # Repeated identical prefixes intentionally expose reuse, but do not label
    # them cold/warm without backend cache measurements or a verified reset.
    for stream in [False, True]:
        with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
            jobs = [pool.submit(latency_request, gateway, f"trial-{n}", stream,
                                "Synthetic neutral context. " * 256) for n in range(args.repeats)]
            result["latency"].extend(f.result() for f in jobs)
    for quantity in range(1, args.repeats + 1):
        result["tool_cases"].append(stateful_tool_case(gateway, quantity))
    result["latency_summary"] = summarize(result["latency"])
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "latency": result["latency_summary"],
                      "tool_cases_passed": sum(r["passed"] for r in result["tool_cases"])}))


if __name__ == "__main__":
    main()
