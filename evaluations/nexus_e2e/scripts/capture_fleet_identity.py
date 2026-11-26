#!/usr/bin/env python3
"""Capture live gateway serving identity for the three production pins.

Writes fleet_identity.json for a Stage 0 evidence stamp. Enriches missing
hardware_class / runtime_image_digest / context_limit from inventory host_vars
when /v1/models omits them. Fails if lead and rocm artifact digests diverge.
"""
from __future__ import annotations

import argparse
import json
import ssl
import sys
import time
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
PINS = {
    "lead": "engineering/lead",
    "deep": "engineering/deep",
    "rocm": "engineering/interactive-rocm",
    "auto": "engineering/auto",
}


def _load_token(token_file: str) -> str:
    if token_file == "-":
        return sys.stdin.read().strip()
    return Path(token_file).read_text(encoding="utf-8").strip()


def _get(base: str, path: str, headers: dict) -> dict:
    req = urllib.request.Request(base.rstrip("/") + path, headers=headers)
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as resp:
        return json.load(resp)


def _parse_inventory_workers() -> dict[str, dict]:
    """Inventory-declared fields /v1/models may omit (hardware_class, runtime digest).

    Values mirror production host_vars for the three live workers. Kept as an
    explicit map so Stage 0 capture does not depend on a YAML parser.
    """
    return {
        "b0-live-llama-worker1": {
            "hardware_class": "intel-arc-pro-b65-32g",
            "runtime_image_digest": "sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9",
            "context_limit": 65536,
            "topology": "tp1",
            "source": "inventory/production/host_vars/ai-5820-01.yml",
        },
        "b0-live-llama-deep-worker2": {
            "hardware_class": "intel-arc-pro-b65-32g",
            "runtime_image_digest": "sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9",
            "context_limit": 65536,
            "topology": "tp1",
            "source": "inventory/production/host_vars/ai-5820-01.yml",
        },
        "ms-s1-hip-qwen38-27b": {
            "hardware_class": "amd-strix-halo-gfx1151",
            "runtime_image_digest": "sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184",
            "context_limit": 65536,
            "topology": "tp1",
            "source": "inventory/production/host_vars/ai-ms-s1-max-01.yml",
        },
    }


def build_identity(base: str, token: str) -> dict:
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    models = _get(base, "/v1/models", headers)
    inv = _parse_inventory_workers()
    pins = {}
    for name, alias in PINS.items():
        entry = next((m for m in models.get("data", []) if m.get("id") == alias), None)
        if entry is None:
            raise SystemExit(f"alias {alias!r} missing from {base}/v1/models")
        serving = []
        for s in entry.get("serving") or []:
            row = {
                "worker_id": s.get("worker_id"),
                "pool": s.get("pool"),
                "role": s.get("role"),
                "model_id": s.get("model_id"),
                "artifact_digest": s.get("artifact_digest"),
                "engine": s.get("engine"),
                "engine_version": s.get("engine_version"),
                "quantization": s.get("quantization"),
            }
            extra = inv.get(s.get("worker_id") or "", {})
            for k in ("hardware_class", "runtime_image_digest", "context_limit", "topology"):
                row[k] = s.get(k) or extra.get(k)
            row["inventory_source"] = extra.get("source")
            serving.append(row)
        pins[name] = {
            "alias": alias,
            "context_length": entry.get("context_length") or entry.get("max_model_len"),
            "reasoning": entry.get("reasoning"),
            "serving": serving,
        }

    lead_dig = (pins["lead"]["serving"] or [{}])[0].get("artifact_digest")
    rocm_dig = (pins["rocm"]["serving"] or [{}])[0].get("artifact_digest")
    same_artifact = lead_dig is not None and lead_dig == rocm_dig
    return {
        "schema": "nexus-e2e-fleet-identity/v1",
        "captured_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "gateway": base.rstrip("/"),
        "pins": pins,
        "constraints": {
            "lead_rocm_same_artifact": same_artifact,
            "lead_artifact_digest": lead_dig,
            "rocm_artifact_digest": rocm_dig,
            "note": (
                "lead≡rocm weights → weak for model-diverse review; still useful for "
                "capacity/hardware/runtime diversity."
                if same_artifact
                else "lead and rocm digests DIVERGE — update plan before comparing collaboration arms."
            ),
        },
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--base", default="https://10.0.8.5:8443")
    p.add_argument("--token-file", required=True, help="Path or '-' for stdin")
    p.add_argument("--out", required=True, type=Path)
    p.add_argument("--allow-digest-divergence", action="store_true")
    args = p.parse_args()
    token = _load_token(args.token_file)
    if not token:
        raise SystemExit("empty token")
    identity = build_identity(args.base, token)
    if not identity["constraints"]["lead_rocm_same_artifact"] and not args.allow_digest_divergence:
        raise SystemExit(
            "lead and rocm artifact digests diverge; refusing to write identity "
            "(pass --allow-digest-divergence after updating the plan)"
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(identity, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {args.out}")
    print(
        "lead_rocm_same_artifact=",
        identity["constraints"]["lead_rocm_same_artifact"],
        "lead=",
        (identity["constraints"]["lead_artifact_digest"] or "")[:24],
        "rocm=",
        (identity["constraints"]["rocm_artifact_digest"] or "")[:24],
    )
    for name in ("lead", "deep", "rocm"):
        pin = identity["pins"][name]
        s0 = (pin["serving"] or [{}])[0]
        print(
            f"  {name}: {pin['alias']} worker={s0.get('worker_id')} "
            f"hw={s0.get('hardware_class')} ctx={pin.get('context_length')} "
            f"reasoning={pin.get('reasoning')}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
