# Window 3: model load / reload under failure (backlog: "default mmap and --no-mmap")

Run on ai-5820-01 GPU0 (worker1 stopped after an idle-gateway check, reconcile timer paused, production restored by `harness/restore_baseline.sh` every time: rc 0, gateway ready, 2/2 workers).
Image `localhost/sycl-research/llama@sha256:6cd97c37…` (the promoted one), Qwen3.6-35B-A3B Q4_K_M, production flags, ESIMD=0, research server on :18100/:18101, not via the gateway.
Harness: `harness/window3_load_failure.sh`. Logs: `load-run1-mmap-ok-nommap-invalid-flag.log` (mmap valid; its `--no-mmap` half invalid), `load.log` (modes none, dio).

Finding about the flag: this build has no `--no-mmap`; it uses `-lm/--load-mode {auto,none,mmap,mlock,mmap+mlock,dio}` (`error: invalid argument: --no-mmap`). Run 1 `nommap` rows are invalid and are not results.

| Case | auto/mmap (default) | `-lm none` | `-lm dio` |
|---|---|---|---|
| A clean load to healthy, then a request | 98 s, ok | 97 s, ok | 97 s, ok |
| B SIGKILL 10 s into load, then reload | unit inactive, reload 97 s, ok | inactive, 97 s, ok | inactive, 97 s, ok |
| C second server on the busy GPU | fails cleanly, first stays healthy and serves | same | same |
| host RAM after load (used) | ~6.2 GB | ~6.7 GB | ~6.7 GB |
| kernel `Timedout job` after each mode | 32 (unchanged) | 32 | 32 |

Conclusions: load time is the same in all three modes (about 97 s, dominated by device upload); there was no mmap hang, no stuck process after SIGKILL during load, and reloading after a kill needed no cleanup; mmap versus no-mmap makes no difference here, so keep the default. Case C fails with an explicit message
(`cannot allocate 18543 MiB … 9605 MiB free of 32656 MiB`, exit due to model loading error) and does not disturb the running server. Observation: the colliding process takes a general protection fault in libc during exit after the failed load
(`dmesg`: llama-server … in libc.so.6, once per mode run); it is exit-time only, with the failure already reported, but worth knowing if a supervisor ever restarts a worker into a full GPU.
Limits: one model (the 22 GB MoE), one GPU, memory-resident files (page cache warm: buff/cache about 52 GB), so a cold-cache load from disk was not measured.
