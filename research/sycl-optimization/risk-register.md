# Risk register
| Risk | Likelihood | Impact | Status / mitigation |
|---|---|---|---|
| HEAD kernels untested on IQ1_M hybrid model (worker 2) | medium | high | Test before any deploy; no reorder kernel for IQ1_M |
| Unreliable behaviour under long context / sustained load on HEAD | unknown | high | NOT TESTED; run 64K + soak |
| Upstream HEAD is a moving target; image built from unreleased commit | medium | medium | Pin SHA + digest; rebuild reproducibly from official Dockerfile |
| Deployed b11347 multi-sequence bug (KLD 0.34 at n_seq=2) | present | low today (`-np 1`) | Blocks `-np>1` on current build; report upstream |
| Reconcile timer restarts stopped workers during experiments | observed | medium | pause/restore scripts |
| Evidence only single-GPU; Gen3 x16 multi-GPU behaviour unknown | unknown | medium | NOT TESTED |
| Candidate image unpinned base images (node:24, intel/deep-learning-essentials tag) | medium | medium | Pin by digest before production use |
