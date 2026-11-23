# Lead + ROCm Capability Mix Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace failing lead (Qwen3.6-35B) and rocm-primary (Coder-30B) pins with an orchestrator-fit lead that earns `coding.routine`, and an MS-S1 general text primary plus OCR + image-gen bolt-ons (coding CAIS not required on rocm primary).

**Architecture:** Dual-track campaign under `research/capability-mix/`. Track L runs on `ai-5820-01` (candidate SYCL worker → orchestration probe → engx `coding.routine` → grant → cut over `engineering/lead`). Track R runs on `ai-ms-s1-max-01` in parallel (R-text smoke → R-ocr fixtures → R-img feasibility/smoke → cut over primary + document bolt-on seams). Deep stays pinned and already granted.

**Tech Stack:** Ansible inventory/host_vars, llama.cpp SYCL/HIP, CAIS (`run_qualification.py`, `cais_cli`), `evaluations/engx/controlled_probe.py` patterns, pytest contracts, podman, optional ComfyUI/ROCm for image-gen.

**Spec:** `docs/superpowers/specs/2026-11-22-lead-rocm-capability-mix-design.md` (commit `5689811`)

**Prerequisites:**
- Testing window open (operator acknowledges live inference OK)
- Qualification token available; gateway CA on controller
- Deep grants live on runtime `sha256:6cd97c37…` (do not demote deep)

---

## File Map

| Path | Responsibility |
| --- | --- |
| `docs/superpowers/specs/2026-11-22-lead-rocm-capability-mix-design.md` | Approved design |
| `research/capability-mix/README.md` | Campaign index, track order, kill criteria |
| `research/capability-mix/orchestration-probe.md` | Probe scenarios + scoring rubric |
| `research/capability-mix/prompts/orch_tools.json` | Multi-tool agent scenario |
| `research/capability-mix/prompts/orch_route.json` | Routing/decomposition scenario |
| `evaluations/capability_mix/orchestration_probe.py` | Runnable probe against gateway alias |
| `tests/test_capability_mix_research_contract.py` | Tree + probe schema contracts |
| `research/capability-mix/evidence/<UTC>/` | Smoke, probe, engx pointers, Track R lab notes |
| `research/capability-mix/r-img-feasibility.md` | Strix image-gen stack choice |
| `evaluations/cais/profiles/` | Live profile JSON for engx |
| `evaluations/cais/results/2026-11-22/` | Engx bundles (extend as needed) |
| `inventory/production/host_vars/ai-5820-01.yml` | Lead cutover + candidate runtime digests |
| `inventory/production/host_vars/ai-ms-s1-max-01.yml` | R-text primary + optional OCR/img workers |
| `inventory/production/cais/` | Grants for qualified lead only |
| `docs/superpowers/specs/2026-11-22-fleet-auto-cais-routing-design.md` | Follow-up amend (Task 10) — coding matrix |

---

### Task 1: Campaign scaffold + contract test

**Files:**
- Create: `research/capability-mix/README.md`
- Create: `research/capability-mix/orchestration-probe.md`
- Create: `research/capability-mix/prompts/orch_tools.json`
- Create: `research/capability-mix/prompts/orch_route.json`
- Create: `tests/test_capability_mix_research_contract.py`

- [ ] **Step 1: Write the failing contract test**

```python
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "research" / "capability-mix"


def test_capability_mix_tree_exists():
    assert (RES / "README.md").is_file()
    assert (RES / "orchestration-probe.md").is_file()
    assert (RES / "prompts" / "orch_tools.json").is_file()
    assert (RES / "prompts" / "orch_route.json").is_file()


def test_readme_names_tracks_and_bars():
    text = (RES / "README.md").read_text()
    for needle in ("Track L", "Track R", "coding.routine", "R-text", "R-ocr", "R-img"):
        assert needle in text


def test_orch_prompts_are_objects_with_id():
    for name in ("orch_tools.json", "orch_route.json"):
        data = json.loads((RES / "prompts" / name).read_text())
        assert "id" in data and "messages" in data
```

- [ ] **Step 2: Run test — expect RED**

Run: `.venv/bin/pytest tests/test_capability_mix_research_contract.py -q`

Expected: FAIL (missing tree).

- [ ] **Step 3: Create scaffold**

`research/capability-mix/README.md`:

```markdown
# Capability mix campaign (lead + rocm)

Spec: `docs/superpowers/specs/2026-11-22-lead-rocm-capability-mix-design.md`

## Tracks
- **Track L (5820):** lead bake-off — smoke → orchestration probe → `coding.routine` → grant → cut over
- **Track R (MS-S1):** R-text primary + R-ocr + R-img bolt-ons (parallel; coding CAIS not required for R-text)

## Kill criteria
- Lead candidate: SYCL OOM / tools broken / orchestration probe clear loss vs baseline / engx not grantable
- R-text: HIP/Vulkan load failure or tools unusable at 32k+
- R-ocr / R-img: fixture failure after two stack attempts → document and defer that bolt-on only

## Evidence
Write under `research/capability-mix/evidence/<UTC>/`.
```

`research/capability-mix/orchestration-probe.md`:

```markdown
# Orchestration probe rubric

Not a CAIS grant. Score each scenario 0–2 (0 fail, 1 partial, 2 pass).
Winner needs total ≥ baseline lead total, and no scenario scored 0.

## orch_tools
Model must propose valid tool calls, consume results, and finish with a concrete answer.
Pass = schema-valid tools + correct final answer from tool output.

## orch_route
Given a user ask + peer/capability menu (lead, deep, rocm-text, ocr, image-gen),
model must pick the right next hop and a stop condition.
Pass = correct primary hop + explicit stop/done rule.
```

`research/capability-mix/prompts/orch_tools.json`:

```json
{
  "id": "orch_tools",
  "messages": [
    {
      "role": "system",
      "content": "You are an orchestrator. Use tools when needed. Do not invent tool results."
    },
    {
      "role": "user",
      "content": "What is 17*19? Use the calculator tool, then answer with only the integer."
    }
  ],
  "tools": [
    {
      "type": "function",
      "function": {
        "name": "calculator",
        "description": "Evaluate a basic arithmetic expression",
        "parameters": {
          "type": "object",
          "properties": {"expression": {"type": "string"}},
          "required": ["expression"]
        }
      }
    }
  ],
  "tool_result": {"expression": "17*19", "value": 323},
  "expect_final_contains": "323"
}
```

`research/capability-mix/prompts/orch_route.json`:

```json
{
  "id": "orch_route",
  "messages": [
    {
      "role": "system",
      "content": "You route work. Peers: deep (reasoning+coding grants), rocm-text (general/long-ctx), ocr (documents/images to text), image-gen (create images). Reply as JSON only: {\"hop\":\"...\",\"reason\":\"...\",\"stop_when\":\"...\"}."
    },
    {
      "role": "user",
      "content": "Extract the invoice total from this scanned PDF page image and put it in a spreadsheet later. First hop only."
    }
  ],
  "expect_hop": "ocr"
}
```

- [ ] **Step 4: Run test — expect GREEN**

Run: `.venv/bin/pytest tests/test_capability_mix_research_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_capability_mix_research_contract.py research/capability-mix/
git commit -m "$(cat <<'EOF'
chore(capability-mix): scaffold Track L/R research tree and probe prompts

EOF
)"
```

---

### Task 2: Orchestration probe runner

**Files:**
- Create: `evaluations/capability_mix/orchestration_probe.py`
- Modify: `tests/test_capability_mix_research_contract.py` (import/help check)

- [ ] **Step 1: Add failing import/help assertion**

Append to `tests/test_capability_mix_research_contract.py`:

```python
import subprocess
import sys

def test_orchestration_probe_module_help():
    script = ROOT / "evaluations" / "capability_mix" / "orchestration_probe.py"
    assert script.is_file()
    proc = subprocess.run([sys.executable, str(script), "--help"], capture_output=True, text=True)
    assert proc.returncode == 0
    assert "orchestration" in (proc.stdout + proc.stderr).lower() or "--base" in proc.stdout
```

- [ ] **Step 2: Run test — expect RED**

Run: `.venv/bin/pytest tests/test_capability_mix_research_contract.py::test_orchestration_probe_module_help -q`

Expected: FAIL (missing script).

- [ ] **Step 3: Implement runner**

Create `evaluations/capability_mix/orchestration_probe.py`:

```python
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
```

- [ ] **Step 4: Run tests — expect GREEN**

Run: `.venv/bin/pytest tests/test_capability_mix_research_contract.py -q`

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add evaluations/capability_mix/orchestration_probe.py tests/test_capability_mix_research_contract.py
git commit -m "$(cat <<'EOF'
feat(capability-mix): add orchestration probe runner for lead bake-off

EOF
)"
```

---

### Task 3: Track L — baseline probe on current lead + refresh Qwen3.8 candidate

**Files:**
- Modify: `inventory/production/host_vars/ai-5820-01.yml` (candidate `qwen38-deep` → also usable as lead candidate; bump `runtime_image_digest` to live `sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9`)
- Evidence: `research/capability-mix/evidence/<UTC>/orch-baseline-lead.json`

- [ ] **Step 1: Confirm live digests on 5820**

```bash
ssh mike@10.0.8.5 'systemctl is-active aihost-llama-worker1 aihost-llama-worker2; podman inspect localhost/sycl-research/llama --format "{{.Digest}}" 2>/dev/null | head -1'
```

Expected: workers active; runtime digest matches `6cd97c37…` (or the image currently used by worker1).

- [ ] **Step 2: Run baseline orchestration probe against `engineering/lead`**

```bash
export SSL_CERT_FILE=$HOME/.config/opencode/t5820-gateway-ca.crt
UTC=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p research/capability-mix/evidence/$UTC
.venv/bin/python evaluations/capability_mix/orchestration_probe.py \
  --base https://10.0.8.5:8443 \
  --token-file /tmp/cais-qualification.token \
  --ca "$SSL_CERT_FILE" \
  --model engineering/lead \
  --prompts-dir research/capability-mix/prompts \
  --out research/capability-mix/evidence/$UTC
```

Record `total` as **baseline**. Exit code may be 1 if current lead scores a 0 — still save the JSON.

- [ ] **Step 3: Ensure Qwen3.8-27B GGUF present; bump candidate runtime digest in inventory**

In `inventory/production/host_vars/ai-5820-01.yml` under `qwen38-deep.gateway_worker`, set:

```yaml
runtime_image_digest: sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9
```

(Use the exact digest from Step 1 if different.)

If `model_file` is missing on host, download the pinned GGUF to `/var/lib/local-ai/models/gguf/qwen3.8-27b/` before starting the candidate unit.

- [ ] **Step 4: Start candidate worker (GPU1 / port 8003) without stopping deep production unless inventory already swaps**

Prefer: run candidate **only if GPU1 can host it without killing deep**. If deep occupies GPU1, schedule a maintenance window to pause deep briefly **or** run Qwen3.8 as a **lead replacement candidate on GPU0** via a new `candidate/qwen38-lead` block mirroring `qwen38-deep` but `gpu: 0`, `port: 8002`, `replaces: worker1`. Prefer the dedicated `candidate/qwen38-lead` path when deep must stay up:

Add inventory block (same artifact as qwen38-deep, GPU0):

```yaml
  qwen38-lead:
    replaces: worker1
    replaces_gateway_worker_id: b0-live-llama-worker1
    worker:
      worker_id: candidate-qwen38-lead
      service_name: aihost-llama-candidate-qwen38-lead.service
      container_name: llama-candidate-qwen38-lead
      gpu: 0
      port: 8002
      config_dir: /etc/local-ai/llama/candidate/qwen38-lead
      model_file: qwen3.8-27b/Qwen3.8-27B-UD-Q4_K_M.gguf
      served_name: Qwen3.8-27B-UD-Q4_K_M
      context: 65536
      args: ["-ngl", "99", "--jinja", "-np", "1", "-fa", "on", "-b", "4096", "-ub", "2048", "--metrics", "--lazy-mode", "on"]
    gateway_worker:
      worker_id: candidate-qwen38-lead
      pool: candidate-qwen38
      engine: llama.cpp
      port: 8002
      public_model_id: candidate/qwen38-lead
      model_id: Qwen3.8-27B-UD-Q4_K_M
      artifact_digest: sha256:322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482
      runtime_image_digest: sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9
      topology: llama-cpp-sycl
      hardware_class: intel-arc-pro-b65-32g
      context_limit: 65536
      max_concurrency: 1
```

(Verify `artifact_digest` against `sha256sum` of the on-disk GGUF before converge.)

- [ ] **Step 5: Converge candidate only; verify `/v1/models` shows `candidate/qwen38-lead`**

```bash
ansible-playbook -i inventory/production/hosts.yml playbooks/candidate.yml \
  -l ai-5820-01 -e candidate=qwen38-lead
curl -sS --cacert "$SSL_CERT_FILE" -H "Authorization: Bearer $(cat /tmp/cais-qualification.token)" \
  https://10.0.8.5:8443/v1/models | python3 -c "import sys,json; print([m['id'] for m in json.load(sys.stdin)['data'] if 'qwen38' in m['id']])"
```

Expected: play succeeds; catalog includes `candidate/qwen38-lead`. Do **not** run `playbooks/inference.yml` while this candidate is active (it asserts and refuses).

- [ ] **Step 6: Commit inventory candidate additions**

```bash
git add inventory/production/host_vars/ai-5820-01.yml
git commit -m "$(cat <<'EOF'
inventory(5820): add qwen38-lead candidate with live runtime digest

EOF
)"
```

---

### Task 4: Track L — probe Qwen3.8-27B; engx `coding.routine` if probe wins/ties

**Files:**
- Create: `evaluations/cais/profiles/lead-qwen38.json`
- Evidence under `research/capability-mix/evidence/<UTC>/`

- [ ] **Step 1: Run orchestration probe on `candidate/qwen38-lead`**

Same command as Task 3 Step 2 with `--model candidate/qwen38-lead`. Compare `total` to baseline. Proceed only if `total >= baseline` and no scenario scored 0.

- [ ] **Step 2: Write profile JSON from live serving identity**

```json
{
  "model_id": "Qwen3.8-27B-UD-Q4_K_M",
  "artifact_digest": "sha256:322e194ff79741c7baa497c240f677f54b201b0efab44ca8e50f122b39123482",
  "runtime_image_digest": "sha256:6cd97c37c443c47f095424ef443c9a3eaa0bad3cbf9dbbc5f3136b3256c163e9",
  "engine": "llama.cpp",
  "topology": "llama-cpp-sycl",
  "hardware_class": "intel-arc-pro-b65-32g",
  "reasoning_budget": 0,
  "reasoning": {"mode": "off", "answer_allowance": 8192}
}
```

Replace digests with values observed from `/v1/models` for the candidate alias. Set `reasoning.mode` to match the alias.

- [ ] **Step 3: Run engx `coding.routine`**

```bash
export SSL_CERT_FILE=$HOME/.config/opencode/t5820-gateway-ca.crt
export ENGX_PYTHON=$PWD/.venv/bin/python
export PYTHONUNBUFFERED=1
.venv/bin/python -u evaluations/cais/run_qualification.py run \
  --base https://10.0.8.5:8443 \
  --token-file /tmp/cais-qualification.token \
  --model candidate/qwen38-lead \
  --profile evaluations/cais/profiles/lead-qwen38.json \
  --capability coding.routine \
  --corpus base \
  --reps 2 \
  --out evaluations/cais/results/2026-11-22
```

- [ ] **Step 4: Assess (and grant only if qualified)**

```bash
BUNDLE=$(ls evaluations/cais/results/2026-11-22/coding.routine-322e194ff797-*.json | tail -1)
.venv/bin/python -m orchestrator_runtime.cais_cli assess inventory/production/cais --bundle "$BUNDLE"
# If qualified:true:
.venv/bin/python -m orchestrator_runtime.cais_cli grant inventory/production/cais \
  --bundle "$BUNDLE" --authority mike@controller
```

If **not** qualified: do **not** grant; continue Task 5 with next shortlist model (Gemma 4 / GLM-Flash / gpt-oss-20b) using the same funnel (smoke → probe → engx). Stop Track L cutover until one candidate grants.

- [ ] **Step 5: Commit profiles, evidence pointers, ledger/bundles if granted**

```bash
git add evaluations/cais/profiles/lead-qwen38.json evaluations/cais/results/2026-11-22/ \
  inventory/production/cais/ research/capability-mix/evidence/
git commit -m "$(cat <<'EOF'
cais: qwen38-lead routine evidence (and grant if qualified)

EOF
)"
```

---

### Task 5: Track L — cut over `engineering/lead` (only after grant)

**Files:**
- Modify: `inventory/production/host_vars/ai-5820-01.yml` (worker1 model → winner; aliases)
- Modify: reconcile snapshot / release id per repo convention

- [ ] **Step 1: Point production worker1 at the winning artifact**

Update `b0-live-llama-worker1` (or equivalent) `model_file`, `model_id`, `artifact_digest`, `runtime_image_digest` to the granted profile. Keep `-np 1`, context 65536, reasoning off for default lead.

- [ ] **Step 2: Converge 5820 llama + gateway; verify**

```bash
# after converge:
curl -sS --cacert "$SSL_CERT_FILE" -H "Authorization: Bearer $(cat /tmp/cais-qualification.token)" \
  https://10.0.8.5:8443/v1/models | python3 -c "import sys,json; m=next(x for x in json.load(sys.stdin)['data'] if x['id']=='engineering/lead'); print(m['serving'][0]['model_id'], m['serving'][0]['artifact_digest'][:24])"
ssh mike@10.0.8.5 'systemctl is-active aihost-llama-worker1 aihost-orchestrator-gateway; journalctl -u aihost-llama-worker1 -n 20 --no-pager'
```

Expected: serving identity matches grant; services active.

- [ ] **Step 3: Bump reconcile snapshot so rollback cannot restore Qwen3.6**

Follow the repo’s existing reconcile pin pattern (same as HIP worker converge).

- [ ] **Step 4: Commit cutover**

```bash
git add inventory/production/host_vars/ai-5820-01.yml inventory/production/
git commit -m "$(cat <<'EOF'
inventory(5820): cut over engineering/lead to capability-mix winner

EOF
)"
```

---

### Task 6: Track R — R-text shortlist smoke on MS-S1

**Files:**
- Create: `research/capability-mix/r-text-shortlist.md`
- Evidence: `research/capability-mix/evidence/<UTC>/r-text-*.md`

- [ ] **Step 1: Write shortlist file with concrete GGUF targets**

```markdown
# R-text shortlist (MS-S1)

Order:
1. Qwen3.8-27B Q4_K_M (general; Halo-comfortable)
2. Gemma 4 31B Q4_K_M (general; HIP/Vulkan smoke required)
3. gpt-oss-20b Q8_0 or Q4 (orchestration-leaning control)
4. gpt-oss-120b Q4 only if sole-tenant window

Kill: tools broken, OOM at 32k, unusable TTFT for interactive use.
Coding CAIS not required.
```

- [ ] **Step 2: Download first candidate to MS-S1 model store** (operator window)

```bash
ssh mike@10.0.8.6 'ls -lh /var/lib/local-ai/models/gguf/ | head'
# download into /var/lib/local-ai/models/gguf/<family>/ using the fleet’s usual hf/aria2 pattern
```

- [ ] **Step 3: Lab smoke with existing HIP llama server (loopback or temp unit)**

Smoke checklist (record in evidence markdown):
1. Load with `-c 65536 -np 1 --jinja -ngl 99`
2. Chat completion OK
3. Tools schema round-trip OK (reuse calculator tool from orch_tools)
4. No HIP correctness nonsense (set `HIP_LAUNCH_BLOCKING=1` if batched garbage appears)

- [ ] **Step 4: If #1 fails, repeat Steps 2–3 for next shortlist entry**

- [ ] **Step 5: Commit shortlist + evidence notes**

```bash
git add research/capability-mix/r-text-shortlist.md research/capability-mix/evidence/
git commit -m "$(cat <<'EOF'
research(capability-mix): R-text shortlist and MS-S1 smoke notes

EOF
)"
```

---

### Task 7: Track R — R-ocr bolt-on fixtures

**Files:**
- Create: `research/capability-mix/fixtures/ocr/invoice_sample.png` (or `.jpg`) — small synthetic invoice
- Create: `research/capability-mix/r-ocr-lab.md`
- Evidence JSON/markdown with extracted text

- [ ] **Step 1: Add a tiny fixture image under `research/capability-mix/fixtures/ocr/`**

Use a simple generated PNG with clear text `INVOICE TOTAL: 42.00` (commit the binary).

- [ ] **Step 2: Smoke an OCR GGUF via llama.cpp multimodal on MS-S1**

Preferred first try: `ggml-org/GLM-OCR-GGUF` (or Qwen3-VL-2B) with `llama-server`/`llama-cli --image` per [llama.cpp OCR blog](https://huggingface.co/blog/ggml-org/using-ocr-models-with-llama-cpp).

Pass criterion: extracted text contains `42.00` (or the fixture’s total) without inventing extra line items.

- [ ] **Step 3: Document chosen model, prompt, memory footprint, and “on-demand vs resident” recommendation in `r-ocr-lab.md`**

- [ ] **Step 4: Commit**

```bash
git add research/capability-mix/fixtures/ocr/ research/capability-mix/r-ocr-lab.md research/capability-mix/evidence/
git commit -m "$(cat <<'EOF'
research(capability-mix): OCR bolt-on fixture and lab choice

EOF
)"
```

---

### Task 8: Track R — R-img feasibility + smoke

**Files:**
- Create: `research/capability-mix/r-img-feasibility.md`
- Evidence: sample output path (git-lfs or evidence dir pointer; do not force huge binaries into git)

- [ ] **Step 1: Write feasibility note choosing one stack**

Must pick **one** of:
1. ComfyUI + ROCm/HIP Flux or SD on Strix
2. Existing host image pipeline if already working
3. Defer with written blocker if neither works in-window

Document: install path, VRAM/GTT budget vs R-text, start/stop commands, gateway wrap later.

- [ ] **Step 2: Generate one 512–1024px test image from prompt `red ceramic mug on wood table`**

Pass: file exists; visually matches prompt on operator review (note in markdown).

- [ ] **Step 3: Commit feasibility doc + small preview if &lt; 256KB, else path-only evidence**

```bash
git add research/capability-mix/r-img-feasibility.md research/capability-mix/evidence/
git commit -m "$(cat <<'EOF'
research(capability-mix): image-gen bolt-on feasibility and smoke

EOF
)"
```

---

### Task 9: Track R — cut over R-text primary; inventory seams for OCR/img

**Files:**
- Modify: `inventory/production/host_vars/ai-ms-s1-max-01.yml`
- Modify: `inventory/production/host_vars/ai-5820-01.yml` (remote HIP worker advertisement / alias)
- Optional: keep Coder-30B as non-primary coding alias only if disk kept

- [ ] **Step 1: Replace primary HIP worker model fields with R-text winner**

Update `ms-s1-hip-coder30b` **or** rename worker_id to a general name in the same change set. Align `engineering/interactive-rocm` (or new `engineering/interactive` alias) to the general model. If renaming aliases, update gateway catalog + client docs in the same PR.

- [ ] **Step 2: Add stub inventory comments or disabled worker blocks for OCR/img ports**

Example comment block (enable in a follow-up wire task once units exist):

```yaml
# capability-mix bolt-ons (not yet enabled):
# r-ocr: llama.cpp multimodal on 127.0.0.1:8021
# r-img: comfyui / diffusion API on 127.0.0.1:8188
```

- [ ] **Step 3: Converge MS-S1 + 5820 gateway advertisement; verify health**

```bash
ssh mike@10.0.8.6 'systemctl is-active aihost-llama-hip-coder30b || systemctl is-active aihost-llama-hip-*; curl -sS -m 5 http://127.0.0.1:<port>/health'
# front door:
curl -sS --cacert "$SSL_CERT_FILE" -H "Authorization: Bearer $(cat /tmp/cais-qualification.token)" \
  https://10.0.8.5:8443/v1/models | python3 -c "import sys,json; print([m['id'] for m in json.load(sys.stdin)['data'] if 'rocm' in m['id'] or 'interactive' in m['id']])"
```

- [ ] **Step 4: Bump reconcile; commit**

```bash
git add inventory/production/host_vars/ai-ms-s1-max-01.yml inventory/production/host_vars/ai-5820-01.yml
git commit -m "$(cat <<'EOF'
inventory(ms-s1): cut over rocm primary to capability-mix R-text

EOF
)"
```

---

### Task 10: Amend fleet-auto CAIS matrix note + campaign wrap

**Files:**
- Modify: `docs/superpowers/specs/2026-11-22-fleet-auto-cais-routing-design.md` (capability expectations section)
- Create: `research/capability-mix/evidence/<UTC>/recommendation.md`

- [ ] **Step 1: Patch fleet-auto spec decisions table**

Replace the requirement that every production peer must hold coding grants with:

```markdown
| Qualifications | deep must hold live coding grants; lead must hold at least `coding.routine` after capability-mix cutover; rocm **primary** is general/visual and is **not** required to hold coding grants; coding-shaped auto traffic prefers deep then lead |
```

- [ ] **Step 2: Write recommendation.md** summarizing winners, grants, bolt-on choices, follow-ups (gateway OCR/img aliases, video)

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-11-22-fleet-auto-cais-routing-design.md research/capability-mix/evidence/
git commit -m "$(cat <<'EOF'
docs: align fleet-auto CAIS matrix with capability-mix roles

EOF
)"
```

---

## Parallelism note

Tasks 3–5 (Track L) and Tasks 6–9 (Track R) may run in parallel once Task 2 lands, as long as:
- deep GPU on 5820 is not stolen without a window
- MS-S1 downloads do not starve 5820 candidate work
- only one production cutover per host at a time

---

## Plan self-review

| Spec requirement | Task |
| --- | --- |
| Dual-track approach | Tasks 3–5 vs 6–9 |
| Lead orchestration + `coding.routine` floor | Tasks 1–2, 4–5 |
| Replace Qwen3.6 lead | Task 5 |
| Replace Coder-30B primary | Task 9 |
| R-text coding-optional | Task 6 |
| OCR + image-gen bolt-ons | Tasks 7–8 |
| Deep untouched / already granted | Prerequisites + Task 3 safety |
| Fleet-auto matrix amend | Task 10 |
| No new CAIS classes yet | Probe is non-grant (Tasks 1–2) |
