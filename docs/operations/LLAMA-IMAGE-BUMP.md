# llama.cpp image bump checklist and patch policy

Applies to any change of the llama.cpp worker image or its Intel runtime stack (IGC, NEO/level-zero, oneDNN, oneAPI). Origin: the
2026-11 SYCL investigation, where an upstream pin bump (`d5bbcd1f3`, #31540) silently regressed 32K prefill (upstream report
`ggml-org/llama.cpp#32399`). Evidence: `research/sycl-optimization/evidence/window2/README.md`.

## Image-bump checklist (all steps are gates; record evidence for each)

1. **Diff review.** Compare the new upstream commit range with the deployed build. Read every change that touches `ggml-sycl`,
   the Dockerfile/CI pins (IGC, NEO, oneDNN, oneAPI versions) and server slot/cache code. Note any pin change explicitly.
2. **Inspect what was built.** Record the image digest, `llama-server --version` (build number and commit) and the runtime
   package versions inside the image. Never deploy by tag; deploy by digest (`localhost/...@sha256:...` or `ghcr.io/...@sha256:...`).
   Pin third-party debs by SHA-256 in the build recipe.
3. **Accuracy gate.** KL divergence against the deployed build on a fixed prompt set, and dense perplexity: no NaN, KL not worse
   than the deployed build. Accuracy takes precedence over throughput.
4. **Performance gate.** Prefill and decode at short and long context (including 32K and larger), compared with the deployed
   build on the same hardware state. A regression beyond noise at any size blocks the bump.
5. **Behaviour gate.** Engineering task A/B (engx) on every routed model; tool-call and multi-turn cases; failure injection
   (client abort mid-stream, concurrency, SIGKILL then restart). A run only counts if the harness proves the intended model
   answered (port free beforehand, `/props` model check).
6. **Gateway-level validation.** Through the gateway only, from the controller: candidate via the durable candidate
   transaction (`controller_candidate_transaction.yml`), long-context TTFT and the qualification probe at concurrency 1 and 2.
7. **Rollout.** Ansible only, via the controller snapshot. Check idleness first (no `print_timing|launch_slot|slot update`
   in worker logs for 6 minutes). Canary one worker, then promote; rehearse the rollback (revert, re-pin snapshot, reconcile)
   before promoting both. The previous image digest must stay in the store.
8. **Soak.** At least several hours of service checks (units active, `NRestarts` 0, kernel `Timedout job` count unchanged)
   plus repeated probes before the bump is called done; record each point.

A bump is blocked if any gate is skipped. "It builds" and "the tests pass" are not gates.

## Patch policy for local llama.cpp changes

- **Additive only.** A local patch adds or guards behaviour; it does not rewrite upstream logic in place.
- **Upstream first.** Every patch links an upstream PR or issue before it ships. Patches without one are experimental and
  must not be deployed to production.
- **Removal condition recorded.** Each patch states, in the build recipe, the upstream change or version after which it is
  deleted, and an owner to check it at every bump.
- **Environment switches over code forks.** Prefer an upstream-supported runtime switch (for example per-worker
  `llama_worker.env` such as `GGML_SYCL_ENABLE_XMX_ESIMD=0`) to carrying a source patch.
- **Recorded in the image.** The image build output lists applied patches and their upstream links; the deployment record
  cites them.
