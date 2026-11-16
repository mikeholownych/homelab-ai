# Applicability to the production platform

- **Workload:** agent sessions (long prefill, short decode) via the gateway; `-np 1` per worker. Prefill gains (+30-70% on Qwen3.6, +4-30%
  on Coder, +37% on Flash-Next at 512) matter more than the 7-8% decode gain forgone by the old IGC/NEO pair. This weighting is a judgement,
  not measured gateway data.
- **Fit:** head-stackB must ship as an Ansible-pinned image with per-worker `GGML_SYCL_ENABLE_XMX_ESIMD=0` and a rehearsed rollback to the
  current digest; no unit-file edits outside Ansible.
- **Does not apply:** `-np 2` (deployed build has a multi-sequence bug; HEAD untested), multi-GPU tensor split, KV quantization.
- **Policy:** all validation so far ran on the host under the bounded research-window suspension; deployment evidence must come through the
  gateway from a remote client.
