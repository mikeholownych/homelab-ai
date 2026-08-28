# Model Catalog (dual-B65 inference hosts)

The model registry role ships a **curated, advisory catalog** of candidate
models, quantizations, and tensor-parallel sizes for the dual-Intel Arc Pro B65
hosts. It is **not desired state**: `model_registry_models` remains empty until
commissioning pins each model to an exact revision with per-artifact SHA256
hashes (downloads are sha256-enforced). The catalog is the reviewed starting
point for that pinning.

Source of truth: `roles/model_registry/files/model-catalog.yml`, validated at
runtime by `roles/model_registry/tasks/catalog.yml` and by
`tests/test_model_registry_contract.py`.

## Per-device sizing rule

The two B65 cards form a **multi-device memory pool** (2 × 32 GiB independent
buffers), not a single transparent 64 GiB device. Every catalog variant must
fit its per-device share plus a reserve (default 6 GiB for KV cache and
runtime/scheduler overhead) inside **one** card's 32 GiB pool:

```
size_gib / recommended_tensor_parallel + model_catalog_kv_cache_reserve_gib
    <= model_catalog_per_device_vram_gib
```

## Current catalog

| Model | Quant | Est. size | TP | Per-device fit | Notes |
|---|---|---|---|---|---|
| Llama-3.1-8B-Instruct (`gated`) | bf16 | 16 GiB | 1 | 22 ≤ 32 | default small serving model |
| Llama-3.1-8B-Instruct (`gated`) | fp8 | 8.5 GiB | 1 | 14.5 ≤ 32 | longer-context headroom |
| Qwen2.5-32B-Instruct | q4_k_m | 20 GiB | 1 | 26 ≤ 32 | single-device 32B-class |
| Qwen2.5-32B-Instruct | fp8 | 34 GiB | 2 | 23 ≤ 32/dev | multi-device span |
| Qwen2.5-32B-Instruct | bf16 | 64 GiB | — | excluded | 38 GiB/dev > 32 |
| Llama-3.3-70B-Instruct (`gated`) | q4_k_m | 40 GiB | 2 | 26 ≤ 32/dev | top-tier reasoning on pool |
| Llama-3.3-70B-Instruct (`gated`) | fp8 | 70 GiB | — | excluded | 41 GiB/dev > 32 |
| Phi-4 (`gated`) | fp8 | 14 GiB | 1 | 20 ≤ 32 | compact reasoning/code |
| Phi-4 (`gated`) | bf16 | 28 GiB | 2 | 20 ≤ 32/dev | spans both cards |

Variants listed with `TP —` (null `recommended_tensor_parallel`) are sized and
excluded for honesty: their per-device share exceeds the pool even at TP=2,
so they are not deployable on this hardware.

## Using the catalog

1. Pick an entry (and variant) whose fit you accept for the workload.
2. At commissioning, resolve the repository's exact **tag/commit** (never
   `main`/`master`/`HEAD`), enumerate every artifact, and verify real SHA256
   hashes.
3. Record the pin in `model_registry_models` for the host (or a `host_vars`
   file) as desired state — this is a Git commit with evidence, exactly like
   any other declared component.
4. Set `model_registry_enabled: true` and enable `features.model_registry` for
   the host only after the storage mount exists and the disk budget passes.

Gated repos (`gated` above, e.g. `meta-llama/*`, `microsoft/*`) require an HF
token retrieved via `model_registry_hf_token_secret_path` from Vault.