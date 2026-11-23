# R-ocr lab (MS-S1 bolt-on)

Plan: `docs/superpowers/plans/2026-11-22-lead-rocm-capability-mix.md` Task 7.
Host: `ai-ms-s1-max-01` (10.0.8.6), llama.cpp HIP image
`sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184` (same as production).

Verdict: **PASS** on the first stack attempt (no second attempt needed).

## Fixture
`fixtures/ocr/invoice_sample.png` (900x260 PNG, 12 KB, generated with PIL / DejaVu Sans Bold). Two lines:
`ACME SUPPLY CO.` and `INVOICE TOTAL: 42.00`.

## Model chosen
`ggml-org/GLM-OCR-GGUF`, Q8_0 (smallest official Q8; f16 also available, not needed).

| File | Size | sha256 |
|---|---|---|
| `GLM-OCR-Q8_0.gguf` | 950,433,408 B | `45bc244a6446aff850521dc41f18bc8d7105ad5f0c2c8c28af04e7cc4f4d50b1` |
| `mmproj-GLM-OCR-Q8_0.gguf` | 484,403,648 B | `9c4b58e33e316ed142eb5dcb41abec3844d3e6e5dc361ffb782c3fa9d175141f` |

Host path: `/var/lib/local-ai/models/gguf/glm-ocr/` (about 1.4 GB, root-owned, world-readable).
Qwen3-VL / Gemma-E fallbacks were not tried.

## Run
Temp container `llama-hip-rocr-smoke` as `aihost-runtime`, loopback `127.0.0.1:8191`, beside the production Coder-30B
worker (:8101, never stopped):

```
-m GLM-OCR-Q8_0.gguf --mmproj mmproj-GLM-OCR-Q8_0.gguf -c 8192 -np 1 -ngl 99 -fa on --jinja --metrics
```

Prompt (user message, image part + text part, temperature 0): `Text Recognition:`

Output (identical on both runs):

```
ACME SUPPLY CO.

INVOICE TOTAL: 42.00
```

- Contains `42.00`; no invented line items. **PASS.**
- Cold: 299 prompt tokens (image + prompt) in 183 ms (1,633 tok/s); 23 tokens decoded at 223 tok/s; 0.30 s wall.
  Warm (prompt cache): 0.11 s wall.
- Server ready in under 20 s from `podman run` (model page cache cold; weights downloaded just before).
- Evidence: `evidence/20261122T212800Z/r-ocr-smoke.py`, `r-ocr-glm-ocr-smoke.log`, `r-ocr-glm-ocr-server.log`.

## Memory footprint
GTT used (`mem_info_gtt_used`): 39.29 GB (production Coder-30B only) -> 41.79 GB with GLM-OCR loaded, about **2.5 GB**
(weights 0.95 GB + mmproj 0.48 GB + KV/compute at `-c 8192`). Back to 39.29 GB after `podman stop`.
Of the 65.9 GB GTT pool this leaves about 24 GB headroom with only production loaded.

## Recommendation: on-demand vs resident
- **Resident is affordable** (2.5 GB, sub-second per page), so a small always-on OCR worker is viable if document traffic
  is regular. But it is a second llama-server process with its own port, API key and gateway alias, which is ops overhead.
- **Recommended default: on-demand** (start per batch, stop afterward), unless OCR traffic is frequent. Cold start is
  seconds and the footprint is negligible next to the 6 GB headroom left by Coder-30B + a 27B R-text co-tenant (see
  `r-text-shortlist.md` memory notes). If the R-text co-tenant decision lands on a resident 27B, GLM-OCR still fits.
- Not wired into the gateway/inventory by this task. Wiring would need a new worker entry and alias, which is outside
  Task 7.

## Caveats
- One synthetic, clean, printed fixture. Real scans (skew, noise, tables, multi-page PDFs) are untested, and the
  "no invented items" check is only meaningful on this two-line page.
- No KV/buffer lines were captured from the server log (log output was empty at default verbosity), so the footprint
  figure comes from GTT deltas only.

## State after task
Temp container stopped; `llama-hip-qwen3-coder-30b.service` active, `/health` 200, GTT back to 39.29 GB. The GLM-OCR
GGUFs remain on disk at the path above for later use.
