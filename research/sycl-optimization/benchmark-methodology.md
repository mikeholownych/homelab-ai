# Benchmark methodology (SYCL research, windows 1-2)

- **Isolation:** one production worker stopped per outage (reconcile timer paused); research server/bench on the same GPU, ports 18100+,
  separate systemd units `sycl-research-*`; EXIT trap runs `harness/restore_baseline.sh` and must print
  "OK: baseline restored, gateway ready, 2/2 workers available". Outages only when worker logs show no inference lines for 6 minutes.
- **Throughput:** `llama-bench -fa 1 -b 4096 -ub 2048 -p <512|2048|8192|32768> -n 128 -r 3` (mean of 3). Same flags as production
  (`-ngl 99`, 64K context for servers). Deployed image pinned by digest; candidates built from named commits and loaded by tag.
- **Build control (lesson 2026-11-16):** every candidate records source commit, compiler, and runtime-package versions; a bisect varies one
  input at a time (source / oneDNN / IGC+NEO) and a suspected cause is confirmed by reverting it.
- **Accuracy gate:** KL divergence of each build's logits against a CPU reference over 3 chunks of a fixed corpus (mean KLD, same-top-token %);
  candidate must match deployed within noise. Task-level: engx base corpus, 12 tasks x 2 reps, <=3 attempts.
- **Limits:** n=3 for throughput, n=2 reps for engx (cannot resolve small accuracy differences; flaky tasks dominate); single host, two GPUs,
  no concurrency (`-np 1`); no gateway-level latency; ESIMD default vs 0 compared per model.
