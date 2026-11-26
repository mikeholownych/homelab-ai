#!/usr/bin/env python3
"""Shared helpers for nexus_e2e drivers (gateway identity, chat, tokens)."""
from __future__ import annotations

import json
import ssl
import sys
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PIN_ALIASES = {
    "deep": "engineering/deep",
    "lead": "engineering/lead",
    "rocm": "engineering/interactive-rocm",
}


def load_token(token_file: str) -> str:
    if token_file == "-":
        return sys.stdin.read().strip()
    return Path(token_file).read_text(encoding="utf-8").strip()


def http_json(base: str, path: str, headers: dict, body: dict | None = None, timeout: int = 1500) -> dict:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        headers=headers,
        method="GET" if body is None else "POST",
    )
    with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as resp:
        return json.load(resp)


def serving_snapshot(base: str, headers: dict, alias: str) -> dict:
    models = http_json(base, "/v1/models", headers, timeout=30)
    entry = next((m for m in models.get("data", []) if m.get("id") == alias), None)
    if entry is None:
        raise SystemExit(f"alias {alias!r} is not served by {base}")
    serving = entry.get("serving") or []
    if len(serving) != 1:
        raise SystemExit(
            f"alias {alias!r} reaches {len(serving)} workers; pin needs exactly one serving entry"
        )
    s = serving[0]
    return {
        "alias": alias,
        "context_length": entry.get("context_length") or entry.get("max_model_len"),
        "reasoning": entry.get("reasoning"),
        "worker_id": s.get("worker_id"),
        "pool": s.get("pool"),
        "model_id": s.get("model_id"),
        "artifact_digest": s.get("artifact_digest"),
        "engine": s.get("engine"),
        "engine_version": s.get("engine_version"),
        "quantization": s.get("quantization"),
    }


def check_lead_rocm_same_artifact(base: str, headers: dict, allow: bool) -> None:
    lead = serving_snapshot(base, headers, PIN_ALIASES["lead"])
    rocm = serving_snapshot(base, headers, PIN_ALIASES["rocm"])
    if lead["artifact_digest"] != rocm["artifact_digest"] and not allow:
        raise SystemExit(
            "lead/rocm artifact digests diverge "
            f"({lead['artifact_digest']!r} vs {rocm['artifact_digest']!r}); "
            "update the plan and pass --allow-digest-divergence"
        )


def chat_completion(
    base: str,
    headers: dict,
    model: str,
    messages: list[dict],
    max_tokens: int,
) -> dict:
    body = {
        "model": model,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": 0,
    }
    return http_json(base, "/v1/chat/completions", headers, body=body, timeout=1500)


def usage_tokens(resp: dict) -> int:
    usage = resp.get("usage") or {}
    return int(usage.get("prompt_tokens") or 0) + int(usage.get("completion_tokens") or 0)
