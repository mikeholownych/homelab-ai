#!/usr/bin/env python3
"""Gateway-only long-context latency probe: time to first token and decode rate at agent-sized prompts.

Same CLI and stdin credential contract as controlled_probe.py (it reuses that module's Gateway client: TLS CA, cache bypass,
reasoning off). Prompts are deterministic synthetic text with a unique nonce FIRST, so the backend prefix cache cannot reuse a
previous request. Results keep sizes, timings and verdicts only, never prompt or response text. 429 responses are retried
with a pause and counted; they are never scored as model failures.
"""
import argparse
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from controlled_probe import Gateway

TARGET_TOKENS = [2000, 8000, 24000]
WORDS_PER_TOKEN = 0.6  # random 5-letter words tokenise to roughly 1.5-2 tokens each; actual size comes from usage


def build_prompt(target_tokens, nonce):
    rng = random.Random(f"long-context-v1:{target_tokens}")  # same filler each run, nonce differs
    words = ["".join(rng.choice("abcdefghijklmnopqrstuvwxyz") for _ in range(5))
             for _ in range(int(target_tokens * WORDS_PER_TOKEN))]
    return f"Request id {nonce}. Read the notes below and reply with exactly READY.\n" + " ".join(words)


def run_one(gateway, target, nonce, retries=3, pause=25):
    messages = [{"role": "user", "content": build_prompt(target, nonce)}]
    throttled = 0
    while True:
        row, data = gateway.chat(messages, stream=True, max_tokens=32)
        if row.get("http_status") == 429 and throttled < retries:
            throttled += 1
            time.sleep(pause)
            continue
        break
    usage = row.get("usage") or {}
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    row.update(target_tokens=target, prompt_tokens=prompt, completion_tokens=completion, throttled_retries=throttled)
    if row["passed"] and prompt and row.get("ttft_seconds"):
        row["prefill_tokens_per_second"] = round(prompt / row["ttft_seconds"], 1)
        if completion and completion > 1 and row["seconds"] > row["ttft_seconds"]:
            row["decode_tokens_per_second"] = round((completion - 1) / (row["seconds"] - row["ttft_seconds"]), 1)
    return row


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--ca", required=True)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--concurrency", type=int, choices=[1, 2], default=1)  # accepted for CLI parity; runs sequentially
    parser.add_argument("--repeats", type=int, choices=range(1, 6), default=2)
    args = parser.parse_args()
    credentials = json.load(sys.stdin)
    gateway = Gateway(args.base, args.model, credentials["qualification"], args.ca)
    result = {"started_at": datetime.now(timezone.utc).isoformat(), "model": gateway.models(),
              "repeats": args.repeats, "reasoning": "off", "corpus": "synthetic-long-context-v1", "rows": [],
              "limitations": ["Synthetic text, not engineering prompts", "Sequential single client; no concurrency claim",
                              "TTFT includes gateway and network time", "Prompt sizes are measured from usage, targets are approximate"]}
    for target in TARGET_TOKENS:
        for n in range(args.repeats):
            result["rows"].append(run_one(gateway, target, f"{int(time.time())}-{target}-{n}"))
    result["finished_at"] = datetime.now(timezone.utc).isoformat()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"output": str(args.output),
                      "passed": sum(r["passed"] for r in result["rows"]), "requests": len(result["rows"])}))


if __name__ == "__main__":
    main()
