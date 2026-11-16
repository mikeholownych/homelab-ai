# Reliability results

Tested: restore path after ~20 outages (EXIT trap, verified every time); crash-at-load observed once (Flash-Next research server,
GPU1 xe VM job timeout 2026-11-16 06:07, `UR_RESULT_ERROR_DEVICE_LOST`; production restored cleanly; retry with a 20 s settle wait
in progress, see `evidence/window2/README.md`).
Not tested: soak, failure injection (kill mid-request, OOM, device reset), `-np 2`, multi-GPU, long-context retrieval/KV quant, gateway
fallback under worker loss. The latent b11347 multi-sequence batch bug (KLD 0.338 at `-b 4096`, n_seq=2) is avoided by `-np 1`.
No candidate is deployable on this evidence; see `integration-recommendations.md`.
