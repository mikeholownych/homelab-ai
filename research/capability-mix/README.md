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