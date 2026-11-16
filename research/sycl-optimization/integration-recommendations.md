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

## Ansible gaps found in `roles/llama_cpp_container` (read-only inspection, 2026-11-16)
1. **No per-worker environment.** `templates/llama-worker.service.j2` hard-codes four `-e` variables; head-stackB needs
   `GGML_SYCL_ENABLE_XMX_ESIMD=0`. Add an optional `llama_worker.env` map rendered as `-e K=V`, default empty (no change for current workers),
   with a role-structure test.
2. **Digest model assumes a registry.** `tasks/main.yml` asserts `llama_cpp_container_digest` matches `^sha256:[0-9a-f]{64}$` and runs
   `podman pull <image>@<digest>`. The candidate exists only in `aihost-runtime`'s local store (`localhost/sycl-research/llama:head-stackB`).
   Options: (a) push to a registry the operator controls and pin that digest (recommended: reproducible, pull-verified, rollback is the old
   digest already in `llama_cpp_container_digest`); (b) a `podman load` task from a built archive with sha256 check. Do not point units at a tag.
3. **Rollback** = revert the digest and env vars in host_vars and re-run the role; the old image stays in the store. Rehearse on one worker
   (GPU1 first) with the same idle-check/EXIT-trap discipline, verify through the gateway, and confirm `ansible-playbook --check` shows 0 changes
   after convergence (idempotency).
4. Supply-chain note: the candidate Dockerfile installs old IGC/NEO from Intel's release assets; pin their SHA-256 in the Dockerfile before building
   the registry image.
