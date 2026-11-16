# Integration recommendation (as of 2026-11-16)

**Decision: EXPERIMENT FURTHER. Do not deploy anything yet.** The candidate is promising, but the production path (Ansible image pin with a tested rollback) and several gates are not done.

Candidate: `head-stackB` = llama.cpp a956a852 + current oneDNN + the OLD IGC 2.34.4 / NEO 26.18 / IGDGMM 22.10.0 pair, with `GGML_SYCL_ENABLE_XMX_ESIMD=0` for every worker.
Why: prefill beats deployed at every tested length on all three models, decode is at parity (Coder, Flash-Next) or better (Qwen3.6), KL is equivalent.

Required before deployment (the operator's rule: HEAD goes to production only through Ansible with a tested rollback):
1. Build the image with the stack pinned explicitly (a Dockerfile override, not upstream's default), record the digest and all component versions (plan 4ae/4af).
2. Ansible-managed image pin plus a rehearsed rollback to the current digest; per-worker env (ESIMD=0) in the same change.
3. Gateway-level validation: client-side TTFT/ITL under realistic load, trace replay, failure injection, `-np 1` confirmed (plan 4q, 4w, 4o).
4. engx on Coder and Flash-Next (only Qwen3.6 done), and the dense-model F16 check (plan 4ac).
5. Decide the decode-vs-long-prefill trade-off with real workload data (the new stack decodes 7-8% faster, the old pair prefills 15% faster at 32K).

Open upstream items: report the IGC 2.42.6 + NEO 26.40 32K regression (plan 4ag), after re-searching the tracker for the multi-sequence bug and XMX-ESIMD (#31068).
Risks: see `risk-register.md` (stack pin must be revisited; the old pair is not a permanent home).
