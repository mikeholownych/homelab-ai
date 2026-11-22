#!/usr/bin/env python3
"""Thin orchestration probe for capability-mix Track L (not a CAIS grant).

  orchestration_probe.py --base URL --token-file F --ca FILE --model ALIAS \
      --prompts-dir research/capability-mix/prompts --out DIR
"""
from __future__ import annotations

import argparse
import json
import ssl
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _post(base: str, headers: dict, ca: str, body: dict, timeout: int = 120) -> dict:
    req = urllib.request.Request(
        base.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers=headers,
        method="POST",
    )
    ctx = ssl.create_default_context(cafile=ca)
    with urllib.request.urlopen(req, context=ctx, timeout=timeout) as resp:
        return json.load(resp)


def score_tools(scenario: dict, first: dict, second: dict | None) -> tuple[int, str]:
    choice = (first.get("choices") or [{}])[0].get("message") or {}
    tool_calls = choice.get("tool_calls") or []
    if not tool_calls:
        return 0, "no_tool_call"
    name = (((tool_calls[0] or {}).get("function") or {}).get("name"))
    if name != "calculator":
        return 0, f"wrong_tool:{name}"
    if second is None:
        return 1, "tool_called_no_final"
    final = ((second.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    expect = scenario.get("expect_final_contains") or ""
    if expect and expect in final:
        return 2, "pass"
    return 1, "final_missing_expect"


def score_route(scenario: dict, resp: dict) -> tuple[int, str]:
    content = ((resp.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
    try:
        start = content.find("{")
        end = content.rfind("}")
        data = json.loads(content[start : end + 1]) if start >= 0 and end > start else {}
    except json.JSONDecodeError:
        return 0, "non_json"
    hop = str(data.get("hop") or "").strip().lower()
    expect = str(scenario.get("expect_hop") or "").lower()
    if hop != expect:
        return 0, f"hop:{hop}"
    if not data.get("stop_when"):
        return 1, "missing_stop_when"
    return 2, "pass"


def main() -> int:
    p = argparse.ArgumentParser(description="capability-mix orchestration probe")
    p.add_argument("--base", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--ca", required=True)
    p.add_argument("--model", required=True)
    p.add_argument("--prompts-dir", required=True)
    p.add_argument("--out", required=True)
    args = p.parse_args()
    token = Path(args.token_file).read_text().strip()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "X-AIHost-Cache": "bypass",
        "Cache-Control": "no-store",
    }
    prompts = Path(args.prompts_dir)
    results = []
    # orch_tools: first turn with tools, second turn with tool result
    tools_sc = json.loads((prompts / "orch_tools.json").read_text())
    first = _post(args.base, headers, args.ca, {
        "model": args.model,
        "messages": tools_sc["messages"],
        "tools": tools_sc["tools"],
        "temperature": 0,
        "max_tokens": 512,
    })
    choice = (first.get("choices") or [{}])[0].get("message") or {}
    second = None
    if choice.get("tool_calls"):
        tc = choice["tool_calls"][0]
        messages = list(tools_sc["messages"]) + [
            choice,
            {
                "role": "tool",
                "tool_call_id": tc.get("id") or "call_1",
                "content": json.dumps(tools_sc["tool_result"]),
            },
        ]
        second = _post(args.base, headers, args.ca, {
            "model": args.model,
            "messages": messages,
            "temperature": 0,
            "max_tokens": 128,
        })
    s_tools, note_tools = score_tools(tools_sc, first, second)
    results.append({"id": "orch_tools", "score": s_tools, "note": note_tools})

    route_sc = json.loads((prompts / "orch_route.json").read_text())
    route_resp = _post(args.base, headers, args.ca, {
        "model": args.model,
        "messages": route_sc["messages"],
        "temperature": 0,
        "max_tokens": 256,
    })
    s_route, note_route = score_route(route_sc, route_resp)
    results.append({"id": "orch_route", "score": s_route, "note": note_route})

    total = sum(r["score"] for r in results)
    out = {
        "schema": "capability-mix-orchestration-probe/v1",
        "model": args.model,
        "gateway": args.base,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "total": total,
        "max_total": 4,
        "scenarios": results,
    }
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"orch-{args.model.replace('/', '_')}-{out['finished_at'][:19].replace(':', '')}.json"
    path.write_text(json.dumps(out, indent=2) + "\n")
    print(json.dumps({"path": str(path), "total": total, "scenarios": results}, indent=2))
    return 0 if all(r["score"] > 0 for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())