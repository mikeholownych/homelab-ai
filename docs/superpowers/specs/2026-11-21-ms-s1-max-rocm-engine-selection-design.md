# MS-S1 Max ROCm Engine Selection Design (Phase 2)

**Date:** 2026-11-21

**Status:** Awaiting implementation plan — Phase 1 platform accepted
(`platform_accepted_engines_deferred`, PR #56 / `4bbb907`)

**Host:** `ai-ms-s1-max-01` at `10.0.8.6` (Minisforum MS-S1 Max, lab only)

**Depends on:** `docs/superpowers/specs/2026-11-21-ms-s1-max-rocm-commissioning-design.md`

## Goal

On the accepted ROCm 7.2.0 / Strix Halo (`gfx1151`) + NPU (`aie2p`) lab
platform, select the best inference **engine × model** fit for this host using a
measured bake-off, then wire **only the winner** into Ansible/systemd while the
host remains lab-only.

## Non-Goals

- Production `ai_hosts` membership, reconcile-controller targeting, or gateway
  worker pool membership (promotion is a later design).
- Changing Phase 1 ROCm pins, Secure Boot policy, or APU GTT/VRAM carve-out
  unless a measured blocker forces a separately approved change.
- Using the NPU as the primary inference backend (NPU remains a Phase 1
  platform gate unless a survivor proves otherwise with evidence).
- Constraining the model shortlist to the current production Intel-fleet
  footprint (Qwen3.6 / Flash-Next / AWQ Coder pins are reference only).

## Decisions (operator-approved)

| Topic | Choice |
| --- | --- |
| Engine set | llama.cpp HIP + vLLM ROCm + SGLang (full three-way) |
| Campaign depth | Research + lab wire of winner (not production promotion) |
| Model scope | Best candidates for this host; not limited to production models |
| Optimization | Balanced scorecard: quality + TTFT + sustained tok/s + ops fit |
| Packaging | Containers preferred; native only if ROCm/container blocker measured |
| Approach | Phased funnel: shortlist → smoke → deep bake-off → lab wire |

## Architecture

```
Phase 1 platform (ROCm 7.2.0, storage, gfx1151 + aie2p)
        │
        ▼
 2a Model shortlist (3–5; APU-fit gates)
        │
        ▼
 2b Engine smoke (llama.cpp HIP / vLLM ROCm / SGLang)
        │ survivors only
        ▼
 2c Deep bake-off (scorecard) ──► written recommendation
        │
        ▼
 2d Lab wire (Ansible + systemd; winner only; lab inventory)
```

- **Evidence root:** `research/rocm-strix-halo/` (shortlist, harness notes,
  `evidence/<timestamp>/`) with on-host mirrors under
  `/var/lib/local-ai/evidence/` when useful.
- **One active engine process** on the APU during comparative runs.
- **Intel path untouched:** do not couple SYCL/XPU/OMIX mutation paths; extend
  existing roles with an AMD/ROCm backend profile when reuse is clean, else add
  a parallel role.

## Phase 2a — Model shortlist

**Purpose:** Choose 3–5 models that can use the ~61 GiB coarse APU pool well
before spending engine time.

### Hard fit gates (required to enter shortlist)

- Fits in ~61 GiB APU pool with runtime + KV headroom (target ≥ ~8–12 GiB free
  after load; tune per engine and record actuals).
- Declared max context usable for interactive coding (≥ 32k preferred; 8k is
  smoke-only floor).
- Open weights, redistributable, pinable artifact (revision and/or sha256).
- Formats: GGUF for llama.cpp and/or HF safetensors / AWQ / FP8 for
  vLLM/SGLang. Prefer families with both when comparability matters; a
  single-format specialist may still shortlist if quality/ops justify it.

### Ranking signals (not production-gated)

- Tool-calling / agent-coding strength (public signals + local qualify-style
  probes later).
- MoE and dense both allowed; prefer MoE when quality per memory looks better
  inside the APU envelope.
- Quant policy: highest quality quant that still meets latency floor for the
  host (Q4/Q5/Q6/AWQ/FP8 as supported) — no forced match to production GGUF
  names.
- Known gfx1151 / ROCm 7.x reports help but are not required.

### Deliverable

`research/rocm-strix-halo/model-shortlist.md` listing candidates, rejects with
reasons, download pins, and which engines can run each candidate.

## Phase 2b — Engine smoke

For each of llama.cpp HIP, vLLM ROCm, and SGLang:

1. Prefer container runtime with `/dev/kfd`, DRI render nodes, and required
   group access; archive a native attempt only if container path fails with a
   measured blocker.
2. Pin image digest and/or git SHA; host ROCm 7.2.0 pin stays immutable.
3. Load a shared small probe model and one mid-size shortlist candidate.
4. Complete a short chat completion and a tool-shaped request; clean shutdown.

**Pass/fail:** systemic engine failure drops the engine from 2c (with evidence).
Per-model failures drop that engine×model pair only.

## Phase 2c — Deep bake-off

Survivors only. Fixed prompts and concurrency tiers **1 / 2 / 4** where the
engine supports concurrent serving.

| Axis | Measure |
| --- | --- |
| Quality | Qualify-style tool/contract probes; spot-check coherence |
| TTFT | p50/p95 cold + warm (prefix reuse when available) |
| Sustained tok/s | Decode throughput; record prefill separately |
| Ops fit | Start time, GTT/VRAM stability, crash rate, pin/repro effort, systemd friendliness |

**Scoring:** weighted balanced scorecard; quality and TTFT weighted above raw
peak tok/s. Deliver a written recommendation naming **primary winner** and
optional **runner-up**. No gateway pool membership in this phase.

### Evidence layout

```
research/rocm-strix-halo/
  model-shortlist.md
  README.md
  evidence/<UTC-timestamp>/
    smoke/
    deep/
    recommendation.md
```

Mirror critical artifacts under
`/var/lib/local-ai/evidence/rocm-strix-halo/<timestamp>/` on the host.

## Phase 2d — Lab wire

**Trigger:** Operator accepts the written bake-off recommendation.

### Inventory / flags (lab only)

- Update `inventory/lab/host_vars/ai-ms-s1-max-01.yml`: enable inference
  capability/role flags and benchmarking as needed for the winner.
- Do **not** add the host to production inventory, gateway workers, or reconcile
  targets.
- Enable exactly one engine role path; keep losers disabled.

### Runtime wiring

- Prefer extending `llama_cpp_container` / vLLM / SGLang role patterns with an
  AMD/ROCm backend profile. Add a new parallel role only if reuse would couple
  Intel SYCL/XPU behavior.
- Systemd unit(s) with pinned image digest or binary SHA; model under
  `/var/lib/local-ai/models/` with checksum.
- Health: local OpenAI-compatible `/v1/models` plus a short generate probe;
  write converge evidence JSON.
- Second converge must be idempotent. Losing engines need not remain installed.

### Done when

Winner serves on the lab host via Ansible; bake-off + wire evidence archived;
production promotion remains an explicit follow-on design.

## Failure Handling

Checkpoints: `shortlist → smoke → deep → recommendation → lab wire`.

- Any blocking smoke/deep gate stops later phases for that engine or pair;
  retain last verified evidence.
- Container→native fallback requires archived failure evidence (not preference).
- ROCm package/channel drift, missing `/dev/kfd`, or loss of `gfx1151` / `aie2p`
  platform gates abort the campaign until Phase 1 health is restored.
- Do not silently change Secure Boot, ROCm pins, or production inventory to
  “make an engine work.”

## Testing Strategy

- **Contract/unit:** lab host_vars inference flags; winner role enablement;
  loser paths remain off; inventory stays out of production.
- **Harness:** reproducible smoke/deep scripts or playbooks with pinned inputs;
  golden prompt set checked into `research/rocm-strix-halo/`.
- **Physical:** all engine runs on `ai-ms-s1-max-01` via `inventory/lab` only.
- **Idempotency:** Ansible wire converges twice with no material drift.
- **Repo quality:** lint/syntax on touched roles/playbooks before host mutation.

## Completion Criteria

Phase 2 is complete only when:

1. Model shortlist document exists with pins and reject reasons.
2. Smoke evidence covers all three engines (pass or documented fail).
3. Deep bake-off scorecard and written recommendation exist.
4. Winner is Ansible-managed on the lab host with health probe evidence.
5. Host remains absent from production inventory and gateway pool.
6. A promotion design/plan is explicitly deferred (out of scope here).

## Follow-On (out of scope)

Separate design + plan to promote `ai-ms-s1-max-01` into the production
inference pool (gateway membership, reconcile, monitoring) if the lab winner
warrants it.
