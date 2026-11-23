# Lead + ROCm Capability Mix (Model Hunt)

**Date:** 2026-11-22

**Status:** Draft for operator review

**Depends on:**
- `reports/CAIS fleet model survey.md`
- `research_notes/CAIS fleet model survey/`
- `docs/superpowers/specs/2026-11-22-fleet-auto-cais-routing-design.md`
- `docs/operations/cais.md`
- Live engx results under `evaluations/cais/results/2026-11-22/`

## Goal

Replace the failing **lead** and **rocm primary** pins with models that match a
**capability mix**, not a stack of coding specialists:

| Peer | Host | Job | Hard pass bar |
| --- | --- | --- | --- |
| **lead** | `ai-5820-01` B65 SYCL | General **orchestrator**: multi-step tool/agent loops **and** task decomposition / routing (which peer or capability next; when to stop) | Earn live `coding.routine` grant; `coding.complex` optional |
| **deep** | `ai-5820-01` B65 SYCL | Reasoning + coding specialist | Already granted `coding.routine` + `coding.complex` on runtime `sha256:6cd97c37…` (2026-11-22) |
| **rocm primary** | `ai-ms-s1-max-01` HIP | General / long-context text tenant (**not** coder-first) | Fit + stable chat/tools; **no** coding CAIS required |
| **rocm visuals** | MS-S1 bolt-ons | OCR/VLM + image generation; video later | Separate services invoked when needed |

`coding.routine` is the **floor** for lead, not its identity. Deep remains the
coding/reasoning peer. ROCm stops being “the coder box” and becomes a general
peer with visual bolt-ons.

## Non-Goals

- Requiring every peer to pass both `coding.routine` and `coding.complex`.
- Requiring the rocm primary text model to earn coding CAIS grants.
- Inventing full new CAIS capability classes (`orchestration`, `ocr`,
  `image_gen`) **before** stacks exist (thin orchestration probe only for lead).
- A single checkpoint that does text + OCR + image generation.
- Multi-node board giants that do not fit B65 / Strix.
- Changing deep’s pin or churning deep mid-campaign.
- Making video a hard requirement.
- Committing gateway fleet-auto routing changes in this campaign (separate spec).

## Decisions

| Topic | Choice |
| --- | --- |
| Approach | **Dual-track**: Track L (5820 lead bake-off) ∥ Track R (MS-S1 hybrid stack) |
| Role mix | lead = general orchestrator; deep = reasoning/coding; rocm = general/long-ctx + visual bolt-ons |
| Pin disposition | **Replace** Qwen3.6-35B as lead; **replace** Coder-30B as rocm **primary** (optional coding alias later only if useful) |
| Lead CAIS bar | Must earn `coding.routine` on live `profile_identity`; complex nice-to-have |
| Rocm CAIS bar | Primary text: coding-optional; visuals are not coding CAIS |
| Visual packaging | **Hybrid**: one primary general text model + bolt-on OCR and image-gen services |
| Visual scope | Image generation + OCR required; video optional / deferred |
| License preference | Prefer Apache/MIT for new lead/rocm text pins; avoid Community License unless explicitly accepted |
| Candidate universe | Start from `reports/CAIS fleet model survey.md`; widen only if shortlists fail smoke |

## Baseline (verified 2026-11-22)

Live engx against front door `https://10.0.8.5:8443` (bundles in
`evaluations/cais/results/2026-11-22/`):

| Peer | `coding.routine` | `coding.complex` | Ledger |
| --- | --- | --- | --- |
| lead (Qwen3.6-35B Q4) | Not qualified (LB ~0.48 &lt; 0.6) | Not qualified (LB ~0.40 &lt; 0.45) | No grant |
| deep (Flash-Next IQ1, reasoning on, runtime `6cd97c37`) | Qualified 12/12 | Qualified 8/10 | Granted; stale runtime `2f494061` grant revoked |
| rocm (Coder-30B Q8) | Not qualified (LB ~0.40) | Not qualified (LB ~0.03) | No grant |

## Architecture

```
                    Clients (Nexus / OpenCode / …)
                              │
                              ▼
                     ai-5820-01 gateway
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
   lead (B65)            deep (B65)           rocm primary (MS-S1)
   orchestrator          reasoning+coding     general / long-ctx
   coding.routine floor  (grants live)              │
                                                    ├─ R-ocr  (bolt-on)
                                                    └─ R-img  (bolt-on)
```

Lead is expected to **decide** when to call deep vs rocm-text vs OCR vs
image-gen. Wiring those visual aliases into the gateway is a **later** step;
this campaign finds and proves the models/stacks.

## Track L — Lead bake-off (5820)

### Shortlist (general + tools; not coder-first)

1. **Qwen3.8-27B** Q4 — denser generalist; candidate path may already exist on host
2. **Gemma 4 26B-A4B or 31B** Q4 — general + tools; SYCL smoke first
3. **GLM-4.7-Flash** Q4 — MIT MoE peer; family diversity
4. **gpt-oss-20b** Q4/Q8 — orchestration/reasoning control if 1–3 disappoint

**Deferred for lead:** Devstral-first (too coding-specialist for this role),
Flash-Next as lead (license + deep role clash), board giants, abliterated merges.

### Funnel (per candidate)

1. **SYCL smoke** — load, chat, tools schema, 16k–65k envelope, no OOM / infra storm
2. **Orchestration probe** (thin, not a CAIS ledger grant) — multi-tool agent loop
   **and** a routing/decomposition scenario (peer/capability choice + stop)
3. **`coding.routine` engx** — grant only if `qualified: true` on live profile
4. **Optional** `coding.complex` if window remains

### Winner rule

First candidate that (a) passes smoke, (b) wins or ties the orchestration probe
against the current lead baseline, and (c) earns `coding.routine` becomes the
new `engineering/lead` pin. Deep stays untouched.

### Runtime safety

Use a candidate worker / scheduled window. Do not demote deep mid-grant.
Converge + bump reconcile only after grant.

## Track R — MS-S1 hybrid stack

Three pieces on one host (not one checkpoint):

| Piece | Role | Gate to “found” |
| --- | --- | --- |
| **R-text** | Replace Coder-30B as primary general / long-ctx chat+tools | HIP or Vulkan smoke; stable tools; 32k–65k; coding CAIS **not** required |
| **R-ocr** | Bolt-on OCR / document vision (prefer llama.cpp multimodal) | Correct extraction on a fixed fixture set; small dedicated worker |
| **R-img** | Bolt-on image generation (diffusion/flow — **not** llama.cpp) | Prompt → image on a Strix-proven path; gateway wrap later |

### R-text shortlist

Qwen3.8-27B, Gemma 4 31B, gpt-oss-20b, or gpt-oss-120b if sole-tenant headroom,
GLM-Flash class. Prefer Apache/MIT. Coder-30B remains optional coding alias
only after cutover if still useful.

### R-ocr shortlist

Small llama.cpp OCR/VLM workers (e.g. GLM-OCR, Qwen3-VL-small, Gemma-E2B/E4B
class). Prefer a dedicated service so R-text can stay resident.

### R-img shortlist

Strix-proven diffusion/flow stack (Flux/SD-class via ROCm or the host’s working
image pipeline). Pick after a short feasibility note in the implementation plan.
Video deferred.

### Memory policy

R-text is the default resident. OCR and image-gen start on demand or share GTT
under an explicit “no concurrent heavy” rule until measured.

## Sequencing and cutover

**Parallelism:** Track L and Track R run once a testing window is open. Contended
resources are operator time and downloads — not the deep GPU.

**Lead cutover**

1. Winner earns `coding.routine` on live `profile_identity`
2. Inventory swap on worker1 → converge 5820 → bump reconcile snapshot
3. Retire Qwen3.6 as production lead (candidate archive OK)
4. Verify catalog aliases and digests

**ROCm cutover**

1. Declare R-text winner on smoke + general fitness (not coding CAIS)
2. Inventory: replace Coder-30B as primary interactive/general alias
3. Ship R-ocr and R-img as separate workers/aliases (names in the plan)
4. Converge MS-S1 + advertise on 5820 front door; bump reconcile

**Delivery artifacts**

- Lead evidence: `evaluations/cais/results/` + ledger grant if qualified
- Track R: short lab note (smoke, fixtures, chosen OCR/img pair)
- No force-grants; no historical unqualified lead bundles

## Relationship to fleet-auto + CAIS

The fleet-auto design assumed coding qualifications on lead/deep/rocm. This
campaign **revises that expectation**:

- **deep** — coding grants required and already present
- **lead** — at least `coding.routine` so it can serve coding-shaped auto traffic
  and still act as orchestrator
- **rocm primary** — **not** required to hold coding grants; coding-shaped auto
  traffic prefers deep (and lead once qualified)
- Visual capabilities enter the gateway later; lead’s orchestration probe
  anticipates calling them

A follow-up should amend
`docs/superpowers/specs/2026-11-22-fleet-auto-cais-routing-design.md` so the
capability matrix matches this mix (out of scope for the model hunt itself).

## Success criteria

Done when:

1. A lead candidate is **granted** `coding.routine` and beats or ties today’s pin
   on the orchestration probe
2. MS-S1 has a chosen **R-text** primary plus concrete **R-ocr** and **R-img**
   selections ready to wire
3. Cutover plans for both hosts are written (inventory + converge + reconcile)

## Open items for the implementation plan (not blockers for this spec)

- Exact orchestration probe scenarios and scoring rubric
- Alias names for OCR / image-gen
- R-img concrete package (ComfyUI vs other) after Strix feasibility skim
- Whether Coder-30B is kept as a non-primary coding alias after R-text cutover
