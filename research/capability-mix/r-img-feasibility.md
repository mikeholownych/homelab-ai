# R-img feasibility (MS-S1 bolt-on)

Plan: `docs/superpowers/plans/2026-11-22-lead-rocm-capability-mix.md` Task 8.
Host: `ai-ms-s1-max-01` (10.0.8.6), Strix Halo gfx1151, ROCm 7.2 host, 122 GiB unified, GTT pool 65.87 GB.

Verdict: **PASS (feasible, smoke OK)**.

## Stack chosen
**ComfyUI + ROCm PyTorch (gfx1151) + SDXL-Turbo fp16**, run in a podman container.

The other two options were ruled out first:
- No existing image pipeline on the host (no ComfyUI, diffusers, sd.cpp or Flux files; images on host were only
  llama.cpp ROCm, vLLM TheRock and SGLang).
- Defer was not needed; the first stack tried works.

Model: `stabilityai/sdxl-turbo`, `sd_xl_turbo_1.0_fp16.safetensors` (6.94 GB, ungated). Chosen as the smallest reliable
checkpoint: 1-4 step sampling, 512px native. Flux (schnell/dev) and SD3.x are untested; they would need more GTT and
a gated or larger download.

## Install path
All under `/var/lib/local-ai/img-lab/` (owned by `mike`, on the 1 TB `/var/lib/local-ai` volume; production uses no
files there):

| Item | Location |
|---|---|
| ComfyUI checkout | `ComfyUI/` (upstream `master` at `4c2b826d74a1827f5cc4a706608fc4653ed12972`, v0.46.0) |
| Checkpoint | `ComfyUI/models/checkpoints/sd_xl_turbo_1.0_fp16.safetensors` |
| Image build | `Containerfile` (copy in `evidence/20261122T213219Z/r-img-Containerfile`) |
| Output | `output/` (via `--output-directory /lab/output`) |

Container image `localhost/comfyui-rocm-gfx1151:smoke` (13.7 GB) is `docker.io/kyuz0/vllm-therock-gfx1151:latest`
(already on the host, torch `2.11.0+rocm10.0.0`, `torch.cuda.is_available()` true on "AMD Radeon 8060S") plus
`pip install -r requirements.txt` (torch lines removed, `torchsde` added). Do not let pip resolve torch: `pip --target`
or `--user` pulls CUDA 13 torch 2.15 and breaks the ROCm build, so bake the deps into a derived image.

Built and run as user `mike` (rootless podman, groups `render`/`video`), not as `aihost-runtime`. For production this
should move to a dedicated unit under `aihost-runtime` like the HIP worker.

## Start / stop
Start (loopback only, no auth, so keep it on 127.0.0.1 until a gateway wrap exists):

```
podman run -d --name comfyui-rocm-smoke --network host \
  --device /dev/kfd --device /dev/dri --group-add keep-groups \
  -v /var/lib/local-ai/img-lab:/lab:Z -e HOME=/tmp \
  localhost/comfyui-rocm-gfx1151:smoke \
  --listen 127.0.0.1 --port 8188 --output-directory /lab/output \
  --use-split-cross-attention --disable-dynamic-vram --disable-async-offload --disable-pinned-memory
```

Stop: `podman rm -f -t 15 comfyui-rocm-smoke` (SIGTERM is ignored by ComfyUI, so it takes the full timeout then
SIGKILL; harmless). Ready in about 30 s from `podman run` (about 14 s of that is aiter JIT at import).
API: `POST /prompt`, `GET /history/<id>`, `GET /view` (driver: `evidence/20261122T213219Z/r-img-smoke.py`).

### Required flags (found by failure)
| Flag | Why |
|---|---|
| `--use-split-cross-attention` | **Mandatory.** With the default (`--use-pytorch-cross-attention`, i.e. SDPA/AOTriton) every run failed with `hipErrorInvalidValue` ("CUDA error: invalid argument"), surfacing at the next `.to(dtype)` after the first attention (async launch failure). The same torch is fine for plain matmul and casts. Split attention runs cleanly. |
| `--disable-dynamic-vram` | Dynamic VRAM (comfy-aimdo) is a CUDA/NVML feature; disabled so ComfyUI uses estimate-based loading. |
| `--disable-async-offload`, `--disable-pinned-memory` | Conservative on a unified-memory APU; not individually shown to be required. |

`--disable-fast-disk`, `--disable-cuda-malloc` and `AMD_SERIALIZE_KERNEL=3` did not change the failure on their own.
Attention was not retried with other options (e.g. `--use-quad-cross-attention`), so the split-attention speed below is
what we have.

## Smoke (512x512, prompt `red ceramic mug on wood table`)
Workflow: CheckpointLoaderSimple -> CLIPTextEncode (empty negative) -> KSampler (4 steps, cfg 1.0, `euler_ancestral`,
`simple`) -> VAEDecode -> SaveImage. Seed 7.

| Metric | Value |
|---|---|
| Result | **PASS**: file exists, 512x512 PNG, 306,379 B, sha256 `088515f0112ac5e8c0353fb95e7bc9341e3fdcdc075854bcf059f1f45c3cfc13` |
| Cold (model load + 4 steps) | 3.70 s ComfyUI-side, 4.17 s wall |
| Warm (4 steps, 512px, new seed) | 0.68 s ComfyUI-side (seed 13: 1.17 s wall via API polling); about 6.7 it/s |
| Production health during/after | `llama-hip-qwen3-coder-30b.service` active, `:8101/health` 200 throughout |

**Operator note (visual review):** the image shows a single glossy red ceramic mug with a handle on the right,
standing on a weathered wood plank table, with a dark brown blurred background. It matches the prompt: red, ceramic,
mug, wood table. No text artifacts or extra objects. **Matches.**

Review was by the implementing agent viewing the PNG, not by a human operator; the operator should confirm.

Only 512px was run. 1024px was not tested (SDXL-Turbo is trained at 512; Turbo output at 1024 is usually worse).

## GTT budget vs R-text
Measured via `mem_info_gtt_used` (production Coder-30B Q8 resident throughout):

| State | GTT used |
|---|---|
| Coder-30B only (production) | 39.29 GB |
| + ComfyUI, SDXL-Turbo loaded, after first image | 49.04 GB (about **+9.8 GB**) |
| After `podman rm -f` | 39.29 GB (fully released) |

ComfyUI sees the whole GTT pool as "VRAM" (62.8 GB) and keeps models and caches resident after a run, so +9.8 GB
is the resident footprint (SDXL UNet + both CLIPs + VAE fp16 about 6.9 GB, plus activations/cache), not a hard need.

Against R-text (`r-text-shortlist.md`, `evidence/20261122T212239Z/r-text-qwen38-27b.md`):
- Beside Coder-30B only: 39.3 + 9.8 = 49 GB, about 17 GB headroom. Fits.
- Beside Coder-30B **and** Qwen3.8-27B at 64k (peak 59.7 GB): 59.7 + 9.8 = about 69.5 GB, over the 65.9 GB GTT pool.
  **Will not fit** (and GLM-OCR at +2.5 GB would only just squeeze in without it).
- If Qwen3.8-27B replaces Coder-30B as R-text primary (Task 9): about 20 GB less than the pair, so ComfyUI plus
  GLM-OCR fit comfortably (roughly 20 GB + 9.8 + 2.5 GB, plus KV).
- Recommendation: **on-demand**, never resident. Start for a batch, stop afterwards, as with R-ocr. While running it
  also shares GPU compute with the text worker, so text decode will slow during generation (not measured).

## Gateway wrap (later, not done here)
- ComfyUI has no auth and a graph-JSON API, so it should stay on loopback behind a thin adapter, not be exposed directly.
- Adapter would expose an OpenAI-style `POST /v1/images/generations` (`prompt`, `size`, `n`), build the workflow above,
  poll `/history`, and return PNG (b64 or URL). Needs a worker entry with API key and a gateway alias such as
  `engineering/image` (the gateway currently only routes text/chat).
- Lifecycle: either a systemd unit under `aihost-runtime` started on demand, or the adapter starts/stops the container
  and enforces a GTT admission check (refuse if resident text models leave under about 12 GB).
- Open items: SDXL-Turbo licence (non-commercial research licence unless a Stability membership applies) needs a decision
  before production use; pin the ComfyUI commit and the base image digest (the `:latest` tag was used here).

## Caveats
- One checkpoint, one prompt, one 512px image. No Flux/SD3, no quality or prompt-adherence benchmark, no concurrency test.
- AOTriton/SDPA is broken on this torch build for gfx1151; a newer TheRock torch may fix it and speed things up.
- Run as `mike` rather than the service user; image `:smoke` tag and `comfyui-rocm-smoke` container name are lab-grade.
- No inventory, gateway or monitoring changes were made. `comfyui-rocm-smoke` was removed; the container image, ComfyUI
  checkout and checkpoint (about 21 GB total) remain on disk for later use.

## Evidence
`evidence/20261122T213219Z/` (preview is a JPEG re-encode of the 306 KB PNG, which exceeds the 256 KB limit):
- `r-img-mug-seed7.jpg` (33 KB preview; full PNG stays on host at `/var/lib/local-ai/img-lab/output/r-img-mug_00001_.png`)
- `r-img-smoke.py`, `r-img-smoke-run-seed13.json`, `r-img-comfyui-server.log`, `r-img-Containerfile`

## State after task
`comfyui-rocm-smoke` removed, port 8188 free, GTT back to 39.29 GB, `llama-hip-qwen3-coder-30b.service` active,
`:8101/health` 200.
