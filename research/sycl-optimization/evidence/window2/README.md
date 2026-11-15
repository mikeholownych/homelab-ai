# Window 2 (2026-11-15) — Qwen3.8-Flash-Next IQ1_M on GPU 1, deployed b11347 vs HEAD a956a852

llama-bench (-ngl 99 -fa 1 -b 4096 -ub 2048, 5 reps):
| test | base t/s | HEAD t/s | change |
|---|---|---|---|
| pp512 | 434.6 ± 2.0 | ~595 (reps 2-5; rep 1 = 44.6 warm-up outlier, mean 484 ± 246) | +37% |
| pp2048 | 677.5 ± 4.7 | 740.1 ± 3.5 | +9% |
| pp8192 | 666.6 ± 3.4 | 721.1 ± 2.5 | +8% |
| tg128 | 19.5 | 23.0 | +18% |

CPU ground-truth KL (3 chunks x 2048, n_seq=1): base KLD 0.0153 (93.06% same top), HEAD KLD 0.0159 (93.29%) — equivalent within error.
Note: first-rep pp512 outlier on HEAD is one-time JIT/warm-up (44.6 t/s); production sees it once per server start.
Correction to window 1: Qwen3-Coder-30B-A3B-Instruct-Q4_K_M.gguf IS on the host (/var/lib/local-ai/models/gguf); it is the brief's primary target and is still to be benchmarked.

## Qwen3-Coder-30B-A3B-Instruct-Q4_K_M on GPU 0 (llama-bench, -fa 1 -b 4096 -ub 2048, 3 reps)
| test | base t/s | HEAD t/s | change |
|---|---|---|---|
| pp512 | 1026.8 | 1305.8 | +27% |
| pp2048 | 1596.5 | 1472.0 | **-8%** |
| pp8192 | 1477.7 | 1282.6 | **-13%** (re-run interleaved x2: 1481 vs 1298, confirmed) |
| pp32768 | 1022.7 | 829.6 | **-19%** |
| tg128 | 92.9 | 99.7 | +7% |
KV q8_0: pp2048 1587→1421 (-10%), pp32768 1015→822 (-19%), tg128 83.6→89.8 (+7%).
Toggles tried on HEAD at pp8192 (no effect, 1287-1303): GGML_SYCL_ENABLE_MKL_FA=0, ENABLE_XMX_ESIMD=1, ENABLE_GRAPH=1.
CPU-truth KL (3 chunks): base KLD 0.00563 (95.18% same top), HEAD 0.00614 (95.18%) — equivalent.

**Finding:** HEAD is NOT uniformly faster. On the brief's primary target (qwen3moe arch) it regresses prefill for prompts >=2K
tokens by 8-19%, the regime agentic coding lives in. Qwen3.6-35B (qwen35moe) and Flash-Next gain. Cause unidentified
(candidates: grouped-MoE prefill path for qwen3moe, or oneAPI 2026.2 vs 2026.1); a bisect is needed before any deployment.

## Compiler control (2026-11-15)
HEAD rebuilt with oneAPI 2026.1.1 (same compiler as deployed; APP_REVISION embedded, image head-a956a852-oneapi2611): Coder-30B
pp2048 1498, pp8192 1308, pp32768 840, tg 98.7 — same regression as the 2026.2.0 build. **Not a compiler effect; it is in the code.**
(Caveat: pp512 samples match the 2026.2.0 run to 0.01%, 1266.69/1322.91/1327.70 vs 1266.78/1323.02/1327.74 — looks deterministic
for that test; other tests differ run to run.)

## Regression bisect (Coder-30B, oneAPI 2026.1.1 builds, GPU 0, pp t/s)
| build | pp512 | pp2048 | pp8192 | pp32768 | tg128 |
|---|---|---|---|---|---|
| 75118a3a (parent of #29245 grouped MoE GEMM) | 967 | 1512 | 1457 | 1012 | 91.6 |
| 847f447c (#29245) | 1244 | 1573 | 1454 | 1008 | 89.7 |
| 18c5a95e (#30156 device MoE scheduler) | 1313 | 1461 | 1289 | 828 | 98.6 |
| a956a852 HEAD | 1306 | 1472/1498 | 1283/1308 | 830/840 | 99.7/98.7 |
=> #29245 is NOT the cause (it helps pp512 +29%). Regression lies in (847f447c, 18c5a95e], 49 commits.
Toggles on HEAD at pp8192 (t/s, none restore ~1450): MMID_SCHED=0 1295; MMID_SCHED=3 1352; FA_DPAS=0 1299; FA_ONEDNN=0 1128 (worse);
FA_ONEDNN=1 1291; ENABLE_ESIMD=0 1303; ENABLE_FUSION=0 1269; ENABLE_DNN=0 1330; MMVQ_WIDE=0 1289; ENABLE_FLASH_ATTN=0 50.
Regression scales with context (-8% @2K, -11% @8K, -18% @32K) -> suspect attention/KV path or a generic kernel change, not MoE routing.

### Bisect round 2 (Coder-30B pp2048/8192/32768 t/s, oneAPI 2026.1.1)
| commit (SYCL-touching index) | pp2048 | pp8192 | pp32768 | |
|---|---|---|---|---|
| e707790c (8) | 1589 | 1451 | 1020 | good |
| 493253fe (16) | 1570 | 1459 | 1026 | good |
| 0a9ef006 (24) | — | — | — | does not compile alone (can_use_mul_mat_vec_q signature) |
| 39febd2a (32) | 1408 | 1315 | 960 | **bad** |
| 2c93f0b6 (40) | 1428 | 1335 | 971 | bad |
Regression introduced in (493253fe, 39febd2a]: 16 SYCL commits. Next: 7377bada8 (graph record/replay, index 23).

### Bisect round 3 (build breakage in the middle of the range)
7377bada8 (graph replay, index 23) and 0a9ef006 (24) do not compile: ggml-sycl.cpp:6897 calls can_use_mul_mat_vec_q without the `device` argument
(fixed by f64a49819, index 25, #31014). Untestable alone. Building d81d0d8fb (22, XMX multi-column refactor) and f64a49819 (25):
22 good => culprit in {23,24,25} (graph replay / fattn-mkl dependency change); 22 bad => culprit in 17-22.

## Upstream already knows: ggml-org/llama.cpp #31068 (found 2026-11-15 14:2x UTC)
Open issue "SYCL: XMX-ESIMD path is ~35% slower for MoE prompt processing on Arc Pro B70 (regression in d81d0d8fb)". The reporter isolates it to #29864
(Multi-column on Intel XMX, = our bisect index 22) and shows that `GGML_SYCL_ENABLE_XMX_ESIMD=0` or `GGML_SYCL_XMX_MAX_COLS=0` on the same binary restores the old speed.
A maintainer confirms the env switch is the intended workaround. Related open: #31262 (PP ~35% slower, b11804 vs b11046, CPU-offloaded MoE); #30892 (F16 NaN on dense Qwen3.8-27B since #29107).
Note: my earlier test set GGML_SYCL_ENABLE_XMX_ESIMD=1, which is the default, so it showed no effect; the correct test is =0.

Our confirmation on HEAD a956a852, Coder-30B, GPU 0 (t/s; pp512 / pp2048 / pp8192 / pp32768 / tg128):
| config | pp512 | pp2048 | pp8192 | pp32768 | tg128 |
|---|---|---|---|---|---|
| deployed b11347 | 1027 | 1597 | 1478 | 1023 | 92.9 |
| HEAD default | 1306 | 1472 | 1283 | 830 | 99.7 |
| HEAD ENABLE_XMX_ESIMD=0 | 1308 | 1653 | 1413 | 872 | 100.3 |
| HEAD XMX_MAX_COLS=0 | 1306 | 1633 | 1407 | 870 | 95.9 |
=> The XMX-ESIMD path explains most of the 2K-8K loss (HEAD with it off beats deployed at 2K, -4% at 8K). A gap remains at 32K (-15% vs deployed): a second, context-scaling cause
   is still open (candidates: flash-attention changes such as #30684 fattn-mkl dependencies, or #31125 DPAS FA).

### Residual 32K gap (Coder-30B, GPU 0, pp32768 t/s, XMX-ESIMD off unless noted)
Deployed 1023. Bisect images with ESIMD=0: 493253fe 1022, 39febd2a 1019, 2c93f0b6 1024 (all match deployed); 18c5a95e 893; HEAD 872.
=> the second cause enters in the last SYCL commits after 2c93f0b6 up to and including 18c5a95e (#30156 device MoE scheduler). 
HEAD + ESIMD=0 plus one more toggle (none recover it): FA_DPAS=0 873; FA_ONEDNN=1 874; FA_ONEDNN=0 691 (worse); ENABLE_MKL_FA=0 876; MMID_SCHED=0 872;
ENABLE_GRAPH=1 876; ENABLE_FUSION=0 864; ENABLE_OPT=0 878; baseline-with-no-op 865.
Qwen3.6-35B on HEAD: XMX-ESIMD on/off identical (pp512/2048/8192/tg: 1400/1800/1777/80.8 vs 1403/1801/1776/81.0). The ESIMD switch matters for Coder-30B only.

### Bisect round 4 (Coder-30B, GPU 0, ESIMD=0, 3 reps; t/s mean, stddev)
| image (index) | pp2048 | pp32768 |
|---|---|---|
| 1b6935b2 (41) | 1549 (52) | 1029 (1.4) |
| 8766c027 (48) | 1591 (104) | 1054 (3.2) |
Deployed pp32768 = 1023; 18c5a95e (49) = 893; HEAD = 872.
=> Indices 41-48 are all good at 32K. The residual 32K regression enters at 18c5a95e (#30156, device-side MoE scheduler) and nowhere earlier.
Caveat: `GGML_SYCL_MMID_SCHED=0` on HEAD did not recover it, so either that switch does not bypass the new code path or part of the loss is in a commit after 18c5a95e (HEAD 872 vs 893). Next: read the #30156 diff for the switch's scope, and test HEAD with the #30156 change reverted.
pp2048 stddev at 8766c027 is wide (104), so the pp2048 numbers are indicative only.
Production restored after the outage: "OK: baseline restored, gateway ready, 2/2 workers available".

### Bisect round 5: do any #30156 switches recover 32K? (pp32768 t/s, ESIMD=0, 3 reps)
| image | extra env | t/s (sd) |
|---|---|---|
| 18c5a95e | MMID_SCHED=0 | 871.3 (2.6) |
| 18c5a95e | MMVQ_WIDE=0 | 873.0 (4.0) |
| 18c5a95e | MMID_SCHED=0 + MMVQ_WIDE=0 | 873.8 (1.6) |
| HEAD | MMVQ_WIDE=0 | 878.1 (1.1) |
| HEAD | MMID_SCHED=0 + MMVQ_WIDE=0 | 875.8 (3.0) |
=> No documented switch recovers it (all ~872-878 vs 1054 at 8766c027). `GGML_SYCL_MMID_SCHED` is a real env var (bitmask, bit 0 = device scheduler, ggml-sycl.cpp:455), so the loss is in code of #30156 that the switches do not bypass
   (it also rewrites fused-gemm.cpp and mmvq.cpp and removes ~76 lines of ggml-sycl.cpp). Not a Coder-only knob fix: the 32K gap stays (~-15% vs deployed) until the commit is understood or reverted.
Production restored: "OK: baseline restored, gateway ready, 2/2 workers available".

### Bisect round 6: reverting #30156 on HEAD does NOT recover 32K (CORRECTION to the previous section)
HEAD with 18c5a95e (#30156) reverted (`head-revert30156`, clean revert) vs plain HEAD, ESIMD=0, 3 reps, t/s (sd):
| image | pp2048 | pp32768 |
|---|---|---|
| head-revert30156 | 1644 (40) | 874.4 (3.7) |
| head-a956a852 | 1639 (18) | 872.2 (2.8) |
=> #30156 is NOT the cause. The previous section's conclusion ("the regression enters at 18c5a95e") was wrong: 18c5a95e is merely the first bisect point built AFTER another commit.
The git range 8766c0273..18c5a95e also holds non-SYCL commits that my SYCL-only commit list skipped. One of them, d5bbcd1f3 (#31540 "ci: update oneAPI 2026.2, oneDNN 2026.1 and Level Zero SDK 1.34.0"),
rewrites `.devops/intel.Dockerfile`: oneDNN 2026.0.2 -> 2026.1.0, Level Zero 1.28.2 -> 1.34.0, IGC 2.34.4 -> 2.42.6, compute runtime 26.18 -> 26.40, IGDGMM 22.10.0 -> 22.10.2 (default ONEAPI 2026.2.0; I override to 2026.1.1).
Each bisect image takes its runtime stack from ITS OWN commit's Dockerfile, so my "code" bisect also bisected the bundled libraries. All images at or before 8766c027 carry the old stack; 18c5a95e, HEAD and head-revert30156 carry the new one.
Hypothesis: the 32K loss comes from the newer oneDNN / IGC JIT / compute runtime inside the image (the 32K path uses oneDNN SDPA), not from llama.cpp source. Test running: HEAD source built with the 8766c0273 Dockerfile (`head-oldstack`).
Implication if true: pin the runtime stack separately from the llama.cpp commit in the bump checklist (plan 4b/4m); the stack is a second variable to test and to roll back. Production's pinned image keeps its own old stack.
Production restored after the outage: "OK: baseline restored, gateway ready, 2/2 workers available".
