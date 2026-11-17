#!/usr/bin/env python3
"""Bounded gateway-level load probe (from a client machine, through the authenticated TLS gateway only).

  sweep:      concurrency 1/2/4 streamed requests of one synthetic prompt shape; TTFT, inter-chunk gaps, TPOT, status codes.
  interleave: long turn -> short request -> long turn (same prefix); TTFT of each, to show prefix reuse and head-of-line effects.
Credentials arrive on stdin as {"qualification": "<token>"}; nothing secret is printed or written. Total request count is bounded.
"""
import argparse
import concurrent.futures
import json
import statistics
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from controlled_probe import Gateway  # noqa: E402

LEVELS = (1, 2, 4)
PER_LEVEL = 3
MAX_REQUESTS = 40


def stream_request(gateway, prompt, max_tokens=128):
    body = {"model": gateway.model, "messages": [{"role": "user", "content": prompt + "\nReply with one short sentence."}],
            "temperature": 0, "max_tokens": max_tokens, "cache": False, "stream": True,
            "stream_options": {"include_usage": True}}
    req = urllib.request.Request(gateway.base + "/v1/chat/completions", json.dumps(body).encode(), gateway.headers)
    start = time.monotonic()
    row = {"status": None, "ttft_seconds": None, "chunk_gaps_seconds": [], "completion_tokens": None, "prompt_tokens": None,
           "cached_prompt_tokens": None, "finish_reason": None, "failure_class": None}
    last = None
    try:
        with urllib.request.urlopen(req, context=gateway.context, timeout=gateway.timeout) as response:
            row["status"] = response.status
            for line in response:
                line = line.decode().strip()
                if not line.startswith("data:") or line == "data: [DONE]":
                    continue
                chunk = json.loads(line[5:])
                usage = chunk.get("usage")
                if usage:
                    row["completion_tokens"] = usage.get("completion_tokens")
                    row["prompt_tokens"] = usage.get("prompt_tokens")
                    row["cached_prompt_tokens"] = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
                for choice in chunk.get("choices") or []:
                    if (choice.get("delta") or {}).get("content"):
                        now = time.monotonic()
                        if row["ttft_seconds"] is None:
                            row["ttft_seconds"] = now - start
                        else:
                            row["chunk_gaps_seconds"].append(now - last)
                        last = now
                    row["finish_reason"] = choice.get("finish_reason") or row["finish_reason"]
    except urllib.error.HTTPError as error:
        row["status"] = error.code
        try:
            row["failure_class"] = (json.loads(error.read()).get("error") or {}).get("type") or "http_error"
        except ValueError:
            row["failure_class"] = "http_error"
    except (OSError, ValueError) as error:
        row["failure_class"] = type(error).__name__
    row["seconds"] = time.monotonic() - start
    n, t = row["completion_tokens"], row["ttft_seconds"]
    if n and n > 1 and t is not None:
        row["tpot_seconds"] = (row["seconds"] - t) / (n - 1)
    return row


def pct(values, q):
    values = sorted(values)
    return values[min(len(values) - 1, int(q * len(values)))] if values else None


def summarize(rows):
    ok = [r for r in rows if r["status"] == 200]
    gaps = [g for r in ok for g in r["chunk_gaps_seconds"]]
    ttft = [r["ttft_seconds"] for r in ok if r["ttft_seconds"] is not None]
    tpot = [r["tpot_seconds"] for r in ok if "tpot_seconds" in r]
    statuses = {}
    for r in rows:
        statuses[str(r["status"])] = statuses.get(str(r["status"]), 0) + 1
    return {"requests": len(rows), "statuses": statuses, "truncated": sum(r["finish_reason"] == "length" for r in ok),
            "ttft_p50": pct(ttft, .5), "ttft_p95": pct(ttft, .95), "ttft_max": max(ttft, default=None),
            "tpot_p50": statistics.median(tpot) if tpot else None, "tpot_p95": pct(tpot, .95),
            "gap_p50": pct(gaps, .5), "gap_p95": pct(gaps, .95), "gap_p99": pct(gaps, .99),
            "wall_p50": pct([r["seconds"] for r in ok], .5), "wall_p95": pct([r["seconds"] for r in ok], .95)}


def strip(row):
    row = dict(row)
    row["chunk_gap_count"] = len(row.pop("chunk_gaps_seconds"))
    return row


def alternate(gateway, result, output):
    """Cache capacity: ROUNDS rounds over CONVERSATIONS distinct long prefixes (A B C A B C). Round 1 is cold; in later rounds the
    cached share of each prompt shows whether the worker still holds that conversation after the others ran."""
    convs = [f"Conversation {name}. " + (f"Synthetic neutral context for {name}. " * 3000) for name in "ABC"]
    result["alternate"] = []
    for rnd in range(2):
        for name, text in zip("ABC", convs):
            row = strip(stream_request(gateway, text, max_tokens=32))
            row.update(round=rnd + 1, conversation=name)
            result["alternate"].append(row)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(output), "alternate": [(r["conversation"], r["status"]) for r in result["alternate"]]}))
    return result


def fork(gateway, result, output):
    """Hybrid-model checkpoint behaviour: a cold long turn, its continuation (prefix + new turn), a mid-prompt fork (first half
    shared, different second half), then the original again. Cached-token counts and TTFT per step show what the slot kept."""
    unit = "Synthetic neutral context for fork. "
    base = unit * 3000
    steps = [("cold", base), ("continuation", base + "\nNext question: summarise the above in one line."),
             ("fork-mid-prompt", unit * 1500 + "Different second half. " * 1500), ("original-again", base)]
    result["fork"] = []
    for name, text in steps:
        row = strip(stream_request(gateway, text, max_tokens=32))
        row["step"] = name
        result["fork"].append(row)
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(output), "fork": [(r["step"], r["status"]) for r in result["fork"]]}))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ca", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--scenario", choices=["load", "alternate", "fork"], default="load")
    args = parser.parse_args()
    assert sum(c * PER_LEVEL for c in LEVELS) + 3 <= MAX_REQUESTS
    gateway = Gateway(args.base, args.model, json.load(sys.stdin)["qualification"], args.ca)
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "model": gateway.models(), "sweep": {}, "interleave": {}}
    if args.scenario in ("alternate", "fork"):
        {"alternate": alternate, "fork": fork}[args.scenario](gateway, result, args.output)
        return
    prompt = "Synthetic neutral context. " * 256
    for level in LEVELS:
        with concurrent.futures.ThreadPoolExecutor(max_workers=level) as pool:
            rows = list(pool.map(lambda _: stream_request(gateway, prompt), range(level * PER_LEVEL)))
        result["sweep"][str(level)] = {"summary": summarize(rows), "rows": [strip(r) for r in rows]}
        time.sleep(5)
    long_prompt = "Synthetic neutral context. " * 2500
    steps = [("long-1", long_prompt), ("short", "Say OK."), ("long-2", long_prompt)]
    for name, text in steps:
        result["interleave"][name] = strip(stream_request(gateway, text, max_tokens=64))
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "sweep": {k: v["summary"]["statuses"] for k, v in result["sweep"].items()}}))


if __name__ == "__main__":
    main()
