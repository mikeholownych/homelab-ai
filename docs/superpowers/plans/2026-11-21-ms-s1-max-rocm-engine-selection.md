# MS-S1 Max ROCm Engine Selection Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** On lab host `ai-ms-s1-max-01` (10.0.8.6), shortlist host-best models for the ~61 GiB Strix Halo APU, smoke-test llama.cpp HIP / vLLM ROCm / SGLang, deep-bake survivors on a balanced scorecard, then Ansible-wire only the winner — still lab-only.

**Architecture:** Phased funnel under `research/rocm-strix-halo/`. Reuse `research/sycl-optimization/harness/engine_sweep_client.py` against loopback OpenAI-compatible ports (not the production gateway). Containers preferred; native HIP/ROCm builds only with archived container blockers. Phase 2d enables exactly one engine role path on `inventory/lab` host vars.

**Tech Stack:** Ansible, podman (or docker), ROCm 7.2.0 host pin, llama.cpp HIP (`-DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1151`), vLLM ROCm (`TRITON_ATTN` on gfx1151), SGLang ROCm (fail closed if stock gfx1151 unavailable), pytest contracts, `engine_sweep_client.py`.

**Spec:** `docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-engine-selection-design.md`

**Platform prerequisite:** Phase 1 complete (`platform_accepted_engines_deferred`, PR #56). Do not mutate production inventory.

---

## File Map

| Path | Responsibility |
| --- | --- |
| `docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-engine-selection-design.md` | Approved design (commit if not yet on main) |
| `research/rocm-strix-halo/README.md` | Campaign index, run order, scorecard weights |
| `research/rocm-strix-halo/model-shortlist.md` | Phase 2a deliverable |
| `research/rocm-strix-halo/prompts/` | Golden smoke/deep prompt JSON |
| `research/rocm-strix-halo/harness/` | Smoke/deep wrappers; symlink or thin wrap of engine_sweep_client |
| `research/rocm-strix-halo/evidence/<UTC>/` | Smoke/deep/recommendation artifacts |
| `tests/test_rocm_strix_halo_research_contract.py` | Tree + shortlist schema contracts |
| `tests/test_ms_s1_max_engine_wire_contract.py` | Lab wire inventory contracts (winner-gated) |
| `inventory/lab/host_vars/ai-ms-s1-max-01.yml` | Flip inference flags + winner pins in 2d |
| `roles/llama_cpp_container/` or new `roles/llama_cpp_hip/` | Winner path if llama.cpp |
| `roles/vllm_rocm/` (new parallel to `vllm_xpu`) | Winner path if vLLM |
| `roles/sglang_rocm/` (new) | Winner path if SGLang |
| `docs/commissioning.md` | Phase 2 runbook section |

---

### Task 1: Commit design + research scaffold

**Files:**
- Commit (if dirty): `docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-engine-selection-design.md`
- Create: `research/rocm-strix-halo/README.md`
- Create: `research/rocm-strix-halo/prompts/smoke_chat.json`
- Create: `research/rocm-strix-halo/prompts/smoke_tools.json`
- Create: `research/rocm-strix-halo/harness/README.md`
- Create: `tests/test_rocm_strix_halo_research_contract.py`

- [ ] **Step 1: Write the failing research-tree contract test**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RES = ROOT / "research" / "rocm-strix-halo"


def test_research_tree_scaffold_exists():
    assert (RES / "README.md").is_file()
    assert (RES / "harness" / "README.md").is_file()
    assert (RES / "prompts" / "smoke_chat.json").is_file()
    assert (RES / "prompts" / "smoke_tools.json").is_file()


def test_readme_names_three_engines_and_phases():
    text = (RES / "README.md").read_text()
    for needle in ("llama.cpp", "vLLM", "SGLang", "2a", "2b", "2c", "2d"):
        assert needle in text
```

- [ ] **Step 2: Run test — expect RED**

Run: `.venv/bin/pytest tests/test_rocm_strix_halo_research_contract.py -q`

Expected: FAIL (missing tree).

- [ ] **Step 3: Create scaffold files**

`research/rocm-strix-halo/README.md`:

```markdown
# ROCm Strix Halo engine selection (`ai-ms-s1-max-01`)

Lab-only campaign on ROCm 7.2.0 / gfx1151. Spec:
`docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-engine-selection-design.md`.

## Phases
- **2a** Model shortlist → `model-shortlist.md`
- **2b** Smoke: llama.cpp HIP, vLLM ROCm, SGLang
- **2c** Deep bake-off (survivors) → scorecard + `evidence/<ts>/recommendation.md`
- **2d** Lab wire winner via Ansible (not production)

## Scorecard weights (balanced)
| Axis | Weight |
| --- | --- |
| Quality (tool/contract probes) | 0.30 |
| TTFT (p50/p95 cold+warm) | 0.30 |
| Sustained tok/s (c=1/2/4) | 0.20 |
| Ops fit | 0.20 |

## Rules
- One engine process on the APU at a time.
- Containers preferred; native only with archived container blocker.
- Reuse `../sycl-optimization/harness/engine_sweep_client.py` against `127.0.0.1:<port>`.
- Do not touch `inventory/production`.
```

`research/rocm-strix-halo/prompts/smoke_chat.json`:

```json
{
  "messages": [{"role": "user", "content": "Reply with exactly: ok"}],
  "max_tokens": 16,
  "temperature": 0
}
```

`research/rocm-strix-halo/prompts/smoke_tools.json`:

```json
{
  "messages": [
    {"role": "user", "content": "Call tool echo with text=ping, then stop."}
  ],
  "tools": [{
    "type": "function",
    "function": {
      "name": "echo",
      "description": "Echo text",
      "parameters": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"]
      }
    }
  }],
  "tool_choice": "auto",
  "max_tokens": 256,
  "temperature": 0
}
```

`research/rocm-strix-halo/harness/README.md`: document wrappers that call
`../../sycl-optimization/harness/engine_sweep_client.py` and curl-based smoke
helpers; note gfx1151 starting points (llama.cpp `-DGGML_HIP=ON
-DAMDGPU_TARGETS=gfx1151`; vLLM `TRITON_ATTN` not `FLASH_ATTN`; SGLang may be
unavailable on stock ROCm 7.2 — record unavailable, do not invent zero tok/s).

- [ ] **Step 4: Run test — expect GREEN**

Run: `.venv/bin/pytest tests/test_rocm_strix_halo_research_contract.py -q`

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-engine-selection-design.md \
  research/rocm-strix-halo tests/test_rocm_strix_halo_research_contract.py
git commit -m "$(cat <<'EOF'
docs: MS-S1 Max ROCm engine-selection design and research scaffold

EOF
)"
```

---

### Task 2: Phase 2a — Model shortlist

**Files:**
- Create: `research/rocm-strix-halo/model-shortlist.md`
- Modify: `tests/test_rocm_strix_halo_research_contract.py`

- [ ] **Step 1: Extend contract test for shortlist schema**

```python
import re

REQUIRED_SECTIONS = (
    "## Candidates",
    "## Rejected",
    "## Download pins",
    "## Engine coverage",
)


def test_model_shortlist_schema():
    path = RES / "model-shortlist.md"
    assert path.is_file()
    text = path.read_text()
    for section in REQUIRED_SECTIONS:
        assert section in text
    # At least 3 candidate bullets under Candidates
    cand = text.split("## Candidates", 1)[1].split("## Rejected", 1)[0]
    assert len(re.findall(r"(?m)^\s*-\s+\*\*", cand)) >= 3
```

- [ ] **Step 2: Run test — expect RED**

Run: `.venv/bin/pytest tests/test_rocm_strix_halo_research_contract.py::test_model_shortlist_schema -q`

- [ ] **Step 3: Research + write shortlist on the live envelope**

From the controller, confirm platform still healthy:

```bash
ssh mike@10.0.8.6 'rocminfo | rg -n "gfx1151|aie2p"; rocm-smi; df -h /var/lib/local-ai'
```

Build `model-shortlist.md` by evaluating candidates **for this host** (not
production-limited). Starter evaluation set (accept/reject with reasons; replace
freely if better options appear):

| Family | Why consider | Likely formats |
| --- | --- | --- |
| Qwen3 / Qwen3-Coder MoE (~30B-A3B class) | Strong tools; known on Halo blogs | GGUF + HF AWQ/FP8/GPTQ |
| Qwen3 dense 14B–32B | Latency floor / smoke mid-size | GGUF + HF |
| Gemma 3 27B (or current Gemma coding peer) | Dense quality reference | GGUF + HF |
| GLM-4.5-Air / similar coding MoE | Agent coding reports | GGUF and/or HF |
| DeepSeek-R1 distill or V3-class quant that fits | Reasoning quality probe | GGUF / HF |
| Llama 4 Scout (or current Meta MoE that fits 61 GiB) | Large-context MoE | HF + GGUF if present |

**Hard reject** anything that cannot fit ~61 GiB coarse pool + ≥8 GiB headroom at
the intended quant/context, closed weights, or unpinned floating “latest” only.

Document for each accepted candidate: parameter class, quant, est. weight GiB,
target context, GGUF path and/or HF repo+revision, engines that can load it.

Select:
- **shared small probe** (≤ ~8B effective) for smoke
- **mid-size** shortlist member for smoke+deep entry
- **3–5 total** shortlist members for deep consideration

- [ ] **Step 4: Run test — expect GREEN**

- [ ] **Step 5: Commit**

```bash
git add research/rocm-strix-halo/model-shortlist.md tests/test_rocm_strix_halo_research_contract.py
git commit -m "$(cat <<'EOF'
research: Strix Halo model shortlist for ROCm engine bake-off

EOF
)"
```

---

### Task 3: Runtime prerequisites on the lab host

**Files:**
- Create: `research/rocm-strix-halo/harness/ensure_podman.sh`
- Create: `research/rocm-strix-halo/evidence/<UTC>/prereq/` (fetched)

- [ ] **Step 1: Check container runtime + device nodes**

```bash
ssh mike@10.0.8.6 'command -v podman || command -v docker; ls -l /dev/kfd /dev/dri/renderD* /dev/accel/accel0; id; groups'
```

- [ ] **Step 2: Install podman if missing (lab host only; do not change ROCm pins)**

Prefer Ansible ad-hoc or a tiny documented shell:

```bash
ssh mike@10.0.8.6 'sudo apt-get update && sudo apt-get install -y podman'
```

Ensure `mike` and future runtime user can access `render`/`video` (already Phase 1).

- [ ] **Step 3: Write `ensure_podman.sh`** that exits non-zero if podman/docker,
  `/dev/kfd`, and a render node are missing; prints JSON summary to stdout.

- [ ] **Step 4: Archive prereq evidence**

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p research/rocm-strix-halo/evidence/$TS/prereq
ssh mike@10.0.8.6 'bash -s' < research/rocm-strix-halo/harness/ensure_podman.sh \
  | tee research/rocm-strix-halo/evidence/$TS/prereq/ensure_podman.json
```

- [ ] **Step 5: Commit harness + evidence**

```bash
git add research/rocm-strix-halo/harness/ensure_podman.sh research/rocm-strix-halo/evidence/
git commit -m "$(cat <<'EOF'
research: lab host container/device prerequisites for Strix Halo bake-off

EOF
)"
```

---

### Task 4: Phase 2b — Engine smoke harness

**Files:**
- Create: `research/rocm-strix-halo/harness/smoke_openai.sh`
- Create: `research/rocm-strix-halo/harness/run_smoke_llamacpp_hip.sh`
- Create: `research/rocm-strix-halo/harness/run_smoke_vllm_rocm.sh`
- Create: `research/rocm-strix-halo/harness/run_smoke_sglang_rocm.sh`
- Create: `research/rocm-strix-halo/harness/stop_engine.sh`

- [ ] **Step 1: Implement shared smoke client**

`smoke_openai.sh` args: `BASE_URL MODEL PROMPT_JSON OUT_JSON`. Posts the prompt
file to `$BASE_URL/v1/chat/completions`, writes status/body/seconds to
`OUT_JSON`, exits 0 only on HTTP 200 with a choices array (tools smoke may
assert `tool_calls` or content containing a function call — record actual
behavior; do not fail solely because a model refuses tools if chat smoke
passed — flag `tools_supported: false` in JSON instead).

- [ ] **Step 2: Implement `stop_engine.sh`**

Stops/removes any bake-off container named `rocm-bake-*` and kills known native
PIDs recorded in `/tmp/rocm-bake-engine.pid` if present. Always leave APU idle
before starting the next engine.

- [ ] **Step 3: llama.cpp HIP smoke script**

Preferred path — container with host ROCm devices, image pinned by digest once
chosen. Starting recipe (adjust after first successful pull; record digest):

```bash
# Pseudocode committed as real script with set -euo pipefail
IMAGE="${LLAMA_HIP_IMAGE:?pin before run}"
MODEL_GGUF="${SMOKE_PROBE_GGUF:?}"   # from shortlist shared probe
PORT=8101
./stop_engine.sh
podman run -d --name rocm-bake-llamacpp --net=host \
  --device=/dev/kfd --device=/dev/dri \
  --group-add keep-groups \
  -v /var/lib/local-ai/models:/models:ro \
  -e HSA_OVERRIDE_GFX_VERSION="${HSA_OVERRIDE_GFX_VERSION:-}" \
  "$IMAGE" \
  -m "/models/${MODEL_GGUF}" -ngl 99 -fa on --host 127.0.0.1 --port "$PORT" -c 8192 -np 1
# wait /v1/models; smoke_chat + smoke_tools; stop_engine.sh
```

If container fails: archive logs under `evidence/<ts>/smoke/llamacpp/container-fail/`,
then optional native build (`cmake -DGGML_HIP=ON -DAMDGPU_TARGETS=gfx1151`) only
with that evidence. **Do not** set `HSA_OVERRIDE_GFX_VERSION` unless measured
necessary (`gfx1151` is native on this host).

- [ ] **Step 4: vLLM ROCm smoke script**

Use an AMD/ROCm image known for gfx1151 when available (e.g. community
`rocm/vllm` gfx1151 tags); pin digest. Force attention backend **TRITON_ATTN**
(not FLASH_ATTN). Mount HF cache under `/var/lib/local-ai/models/hub`. Port
`8102`. Same smoke prompts against served model id.

- [ ] **Step 5: SGLang ROCm smoke script**

Attempt container/source path compatible with host ROCm 7.2.0 + gfx1151. If
install/start fails after documented attempts, write
`evidence/<ts>/smoke/sglang/UNAVAILABLE.md` with commands + logs and **exit 0
from the campaign orchestrator with status `unavailable`** (not a fake zero
tok/s deep result). Do not patch host ROCm to 7.14 to force SGLang in this
campaign unless operator explicitly expands scope.

- [ ] **Step 6: Download shortlist probe (+ mid-size) weights to the host**

Store under `/var/lib/local-ai/models/` with checksums recorded in shortlist
pins. Prefer `huggingface-cli` / `curl` with sha256 verify.

- [ ] **Step 7: Run all three smokes sequentially; archive**

```bash
TS=$(date -u +%Y%m%dT%H%M%SZ)
mkdir -p research/rocm-strix-halo/evidence/$TS/smoke/{llamacpp,vllm,sglang}
# run each script with EVIDENCE_DIR set; stop_engine between
```

- [ ] **Step 8: Commit scripts + smoke evidence**

```bash
git add research/rocm-strix-halo/harness research/rocm-strix-halo/evidence/
git commit -m "$(cat <<'EOF'
research: Strix Halo engine smoke harness and first-pass results

EOF
)"
```

---

### Task 5: Phase 2c — Deep bake-off

**Files:**
- Create: `research/rocm-strix-halo/harness/run_deep_bakeoff.sh`
- Create: `research/rocm-strix-halo/harness/scorecard.py`
- Create: `research/rocm-strix-halo/prompts/deep_batch_note.md`
- Create: `tests/test_rocm_strix_halo_scorecard.py`

- [ ] **Step 1: Failing scorecard unit test**

```python
from research.rocm_strix_halo_scorecard import score  # or importlib from harness path


def test_scorecard_weights_sum_and_prefer_quality_ttft():
    weights = {"quality": 0.30, "ttft": 0.30, "tok_s": 0.20, "ops": 0.20}
    assert abs(sum(weights.values()) - 1.0) < 1e-9
    a = score({"quality": 0.9, "ttft": 0.9, "tok_s": 0.2, "ops": 0.5}, weights)
    b = score({"quality": 0.2, "ttft": 0.2, "tok_s": 0.9, "ops": 0.5}, weights)
    assert a > b
```

Place importable module at
`research/rocm-strix-halo/harness/scorecard.py` and load via path in the test
(`importlib.machinery.SourceFileLoader`) to avoid packaging churn — mirror
patterns used elsewhere in this repo's tests if a closer example exists.

- [ ] **Step 2: Implement `scorecard.py`**

Normalize each axis to 0–1 from raw metrics (document formulas in module
docstring: e.g. TTFT score = clamp(1 - p50_s/target), tok/s vs best-in-run,
ops rubric 0–1 from checklist). `score(axes, weights) -> float`.

- [ ] **Step 3: `run_deep_bakeoff.sh`**

For each **smoke survivor** × **deep shortlist model** (skip unavailable
engines):

1. `stop_engine.sh`; start engine with pinned image + model
2. Warmup short completion
3. Cold TTFT: `engine_sweep_client.py longctx <port> <model> 2048 8192`
4. Batch: `engine_sweep_client.py batch <port> <model> 1 2 4`
5. Warm TTFT: repeat a fixed 2k prefix twice; record second TTFT
6. Quality: tool-shaped request from `smoke_tools.json` (or deeper prompt if
   tools work); record pass/fail + notes (full `qualify.py` is gateway-oriented —
   do **not** require production gateway; keep worker-direct probes)
7. Ops checklist JSON: start_seconds, peak GTT from `rocm-smi`, restarts, pin
   friction (1–5)
8. Write `evidence/<ts>/deep/<engine>/<model>/metrics.jsonl`

- [ ] **Step 4: Run deep bake-off on the host; fill scorecard table**

Produce `evidence/<ts>/deep/scorecard.md` with per-row weighted scores.

- [ ] **Step 5: Commit**

```bash
git add research/rocm-strix-halo/harness tests/test_rocm_strix_halo_scorecard.py \
  research/rocm-strix-halo/evidence/ research/rocm-strix-halo/prompts/
git commit -m "$(cat <<'EOF'
research: Strix Halo deep bake-off harness and scorecard

EOF
)"
```

---

### Task 6: Written recommendation

**Files:**
- Create: `research/rocm-strix-halo/evidence/<ts>/recommendation.md`
- Modify: `research/rocm-strix-halo/README.md` (link latest recommendation)

- [ ] **Step 1: Write recommendation**

Must include:
- Primary winner: `{engine, model, quant, image_digest_or_sha, listen_port}`
- Optional runner-up
- Scorecard summary table
- Engines marked unavailable/failed with reasons
- Explicit: **lab wire next; production promotion deferred**

- [ ] **Step 2: Operator checkpoint**

Stop for operator acceptance of the recommendation before Task 7. Do not wire
a loser or a speculative dual-engine lab setup.

- [ ] **Step 3: Commit recommendation**

```bash
git add research/rocm-strix-halo/evidence/ research/rocm-strix-halo/README.md
git commit -m "$(cat <<'EOF'
research: Strix Halo engine×model recommendation

EOF
)"
```

---

### Task 7: Phase 2d — Lab wire (winner only)

**Files (touch only the winning path):**
- Modify: `inventory/lab/host_vars/ai-ms-s1-max-01.yml`
- Create: `tests/test_ms_s1_max_engine_wire_contract.py`
- Modify: `playbooks/site.yml` / role defaults as needed
- Modify: `docs/commissioning.md`
- One of:
  - **W-llama:** extend `roles/llama_cpp_container` with HIP/ROCm backend vars **or** add `roles/llama_cpp_hip/` parallel role if SYCL coupling is unsafe
  - **W-vllm:** create `roles/vllm_rocm/` parallel to `roles/vllm_xpu/` (do not mutate XPU defaults)
  - **W-sglang:** create `roles/sglang_rocm/`

- [ ] **Step 1: Winner-gated contract test**

```python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def test_lab_ms_s1_inference_enabled_for_winner_only():
    hv = yaml.safe_load((ROOT / "inventory/lab/host_vars/ai-ms-s1-max-01.yml").read_text())
    assert hv["node_roles"]["inference"] is True
    assert hv["capabilities"]["inference"] is True
    # Exactly one engine enable flag true among known keys
    flags = [
        bool(hv.get("llama_cpp_container_enabled")),
        bool(hv.get("llama_cpp_hip_enabled")),
        bool(hv.get("vllm_rocm_enabled")),
        bool(hv.get("sglang_rocm_enabled")),
    ]
    assert sum(1 for f in flags if f) == 1
    assert "ai-ms-s1-max-01" not in yaml.safe_load(
        (ROOT / "inventory/production/hosts.yml").read_text()
    ).get("all", {}).get("children", {}).get("ai_hosts", {}).get("hosts", {})
```

Adjust flag names to match the role actually implemented; keep the **exactly
one engine** invariant.

- [ ] **Step 2: Implement winner role**

**If llama.cpp HIP wins:** Prefer new `roles/llama_cpp_hip/` cloned structurally
from `llama_cpp_container` with:
- `llama_cpp_hip_enabled: false` by default
- image/digest pins from recommendation
- devices `/dev/kfd` + DRI; no SYCL env
- loopback bind `127.0.0.1`
- model path under `/var/lib/local-ai/models/gguf`
- health check task hitting `/v1/models`

**If vLLM ROCm wins:** New `roles/vllm_rocm/` parallel to `vllm_xpu`:
- `vllm_rocm_enabled: false` default
- `TRITON_ATTN` / gfx1151-safe args from bake-off
- do not import XPU oneAPI vars

**If SGLang wins:** New `roles/sglang_rocm/` with the same fail-closed defaults
pattern.

Wire role into `playbooks/site.yml` behind the enable flag. Keep
`intel_gpu_install_enabled: false` on this host.

- [ ] **Step 3: Update lab host_vars**

Set inference capabilities true; set winner enable true; pin image digest,
model id/path, port, and any measured CLI flags from recommendation. Leave
loser flags false/absent.

- [ ] **Step 4: Deploy + verify on lab host**

```bash
ansible-playbook -i inventory/lab playbooks/site.yml --limit ai-ms-s1-max-01 --tags <winner-tag>
# health
ssh mike@10.0.8.6 'curl -fsS http://127.0.0.1:<port>/v1/models'
# idempotent second converge
ansible-playbook -i inventory/lab playbooks/site.yml --limit ai-ms-s1-max-01 --tags <winner-tag>
```

Archive unit status + journal + `/v1/models` under
`research/rocm-strix-halo/evidence/<ts>/wire/`.

- [ ] **Step 5: Docs**

Add **MS-S1 Max Phase 2** subsection to `docs/commissioning.md`: shortlist →
smoke → deep → wire commands; note production promotion still deferred.

- [ ] **Step 6: Tests + commit**

```bash
.venv/bin/pytest tests/test_ms_s1_max_engine_wire_contract.py tests/test_rocm_strix_halo_research_contract.py -q
git add inventory/lab/host_vars/ai-ms-s1-max-01.yml roles/ playbooks/site.yml \
  docs/commissioning.md tests/ research/rocm-strix-halo/evidence/
git commit -m "$(cat <<'EOF'
feat(lab): wire Strix Halo bake-off winner on ai-ms-s1-max-01

EOF
)"
```

---

### Task 8: PR to main

- [ ] **Step 1: Push branch and open PR**

```bash
git push -u origin HEAD
gh pr create --title "feat: MS-S1 Max ROCm engine selection (Phase 2)" --body "$(cat <<'EOF'
## Summary
- Model shortlist + three-way smoke/deep bake-off on ai-ms-s1-max-01
- Scorecard recommendation and lab-only Ansible wire of the winner
- Production inventory / gateway pool unchanged

## Test plan
- [ ] `pytest` research + wire contracts
- [ ] Smoke/deep evidence reviewed
- [ ] Lab host `/v1/models` healthy after converge
- [ ] Second converge idle

EOF
)"
```

- [ ] **Step 2: Merge after CI green** (operator/self-merge policy as for PR #56)

---

## Spec coverage checklist

| Spec requirement | Task |
| --- | --- |
| Model shortlist 3–5, host-best, not prod-limited | Task 2 |
| Hard APU fit gates + pins | Task 2 |
| Smoke all three engines; containers first | Tasks 3–4 |
| SGLang unavailable ≠ zero tok/s | Task 4 |
| Deep scorecard weights quality/TTFT | Task 5 |
| Written recommendation + operator gate | Task 6 |
| Lab wire winner only; no production pool | Task 7 |
| Evidence under `research/rocm-strix-halo/` | Tasks 3–7 |
| Promotion deferred | Tasks 6–7, PR body |

## Self-review notes

- No TBD placeholders; winner-specific role paths are conditional but fully
  specified for each engine.
- vLLM gfx1151 attention backend locked to TRITON_ATTN per public Halo notes.
- Host ROCm 7.2.0 pin is not upgraded to chase SGLang.
- `qualify.py` stays gateway-oriented; deep quality uses worker-direct probes.
- Production `inventory/production` is never modified.
