# T5820 upstream qualification — completed

**Decision: do not promote the tested llama.cpp candidate. Both original production runtimes are restored and healthy.** Physical runs completed October 21, 2026; final live verification completed October 22 at approximately 20:34 UTC (16:34 EDT). This report preserves the October 21 canonical-main snapshot separately from the later health check.

All remote operations used Ansible. The authorized gateway drain repair remains deployed. No kernel, driver or production runtime upgrade was deployed. GitHub main was not modified; the reviewed controller changes and this evidence are published on `feat/t5820-upstream-qualification-20261021`.

## Verified repository and production state

Canonical main was `5b83ac65899901a5c2470c703fa4238e015e64f3` at the October 21 17:27 UTC refresh. Its exact-SHA [quality workflow 38639692395](https://github.com/mikeholownych/homelab-ai/actions/runs/38639692395) passed. Recent canonical commits are release certification `5b83ac6`, controller/Vault runbooks `1db9175`, live dual-llama.cpp architecture reconciliation `9e57d56`, and optional Starlette/HTTPX test-import guards `8673ed5`. These are not evidence of a new production runtime. CI success does not erase the physical qualification failures below. Evidence: `canonical-repository-refresh.json`.

The active appliance is dual Intel Arc Pro B65, **32 GB nameplate VRAM per card**, using llama.cpp/SYCL. The expected GPU-internal PCIe 2.5 GT/s x1 reading is not a physical host-lane fault.

| Worker | Actual production model | Context | Reasoning policy |
|---|---|---:|---|
| GPU 0 / lead | Qwen3.6-35B-A3B-UD-Q4_K_M | 65,536 | Default lead off; opt-in lead-reasoning 8,192 |
| GPU 1 / deep | Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M | 65,536 | On, 4,096 |

Source: [inventory/production/host_vars/ai-5820-01.yml:185](https://github.com/mikeholownych/homelab-ai/blob/5b83ac65899901a5c2470c703fa4238e015e64f3/inventory/production/host_vars/ai-5820-01.yml#L185), [routing:327](https://github.com/mikeholownych/homelab-ai/blob/5b83ac65899901a5c2470c703fa4238e015e64f3/inventory/production/host_vars/ai-5820-01.yml#L327). Retired vLLM variables and issue wording are not the active inference stack.

Original runtime code: `5fc4f3c8c7103ffd0b7ff5ee4855bcc78a3ed5cd`, API `b11347-5fc4f3c8c` (binary reports 0.5.0-dev).

Original image: `ghcr.io/ggml-org/llama.cpp@sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451`.

Tested candidate code: `620d2225cc436ab0b001e3200e590e3b286ef9ab`, API `b11669-620d2225c`, v0.7.0 release artifact `llama-b11669-bin-ubuntu-sycl-fp32-x64.tar.gz`. Archive SHA-256: `bb18befb7a5c0ecbc01d334d5e671046e27d29275eec4fb3e44491e2faeef251`.

Isolated candidate image: `localhost/aihost/llama-sycl-qualification@sha256:1bd92baaab3a57b655614e524c39dabf42dc593e687cfff4d13d5a3bbb1cd2f8`. This qualifies this packaged FP32 build, not every possible v0.7.0 build or a fresh-install distribution pipeline. Actual container inspections bind each run to its immutable image; the public model descriptor alone does not expose that image digest.

Final health: two available/configured workers, no active or queued work, valid evidence chain, and fresh authenticated TLS completions from both original models. Both containers run the exact original digest; no candidate container remains running. Original lead started October 21 19:29:43 UTC; original deep started 17:11:30 UTC; both have zero automatic restarts. Gateway release is `t5820-gateway-b9d42e7`. Evidence: `production-final-oct22.json`, `final-runtime-images.json`, `final-service-journals.json`.

Final reconciliation snapshot and reviewed source are clean at `37e821a8f16ab01ff45213c64e75e24a21e17523`; the lock is released, temporary credential removed, replay copies removed after evidence collection, timer active, and latest scheduled reconciliation succeeded October 22 20:07 UTC. The earlier expected lock-contention event during qualification remains historical evidence; no unrelated failure was cleared. Client scopes were preserved. Production response caching was restored to its prior enabled setting despite the separate defect below. Evidence: `runtime/final-controller-state.json`, `runtime/qualification-orchestration.log`, `final-settings.json`.

### Measured model-file provenance

Final SHA-256 measurement completed October 22 20:37:51 UTC, with inode/size/mtime stable during each read:

| File | Bytes | Measured SHA-256 |
|---|---:|---|
| Qwen3.6-35B-A3B-UD-Q4_K_M.gguf | 22,134,528,992 | `ac0e2c1189e055faa36eff361580e79c5bd6f8e76bffb4ce547f167d53e31a61` |
| Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00001-of-00002.gguf | 29,608,446,496 | `e11083ba855e7666b48ea3f2db6a9c3a20c18751a012cc24f948de91b7087fad` |
| Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M-00002-of-00002.gguf | 28,800,138,432 | `316b46f3a2dbd68c900f43136ab9449f9dcc3725dfd8c794847c204bc161e113` |

The lead file equals its advertised artifact digest. Neither deep shard individually equals the advertised `sha256:935587187e4b…` identifier. No aggregate-manifest derivation was established in the inspected inventory/qualification records; this is an unresolved binding gap, not proof of file corruption. Future capability evidence should bind a documented ordered shard manifest to the actual file hashes. Both runtime variants used the same configured files; the gateway's static artifact label alone is not cryptographic proof of the complete shard set. Evidence: `model-file-hashes.json`.

## Matched qualification results

Each run used the same engineering corpus (`a2e49329628243ed`) and frozen replay manifest (`f5410a90ef007209b1107277c6a09c8568566d7a39fdad634cf8ae6fbf4333b2`), temperature zero, three protocol trials, and one engineering repeat with at most three attempts. Deep used its native 4,096 reasoning budget; lead engineering used opt-in reasoning-on 8,192. Default lead reasoning-off received contract tests, not a complete hard engineering corpus.

| Check | Deep original | Deep candidate | Lead original | Lead candidate |
|---|---:|---:|---:|---:|
| Single tool / parallel / streaming / structured / agent loop | Each 3/3 | Each 3/3 | Each 3/3 | Each 3/3 |
| Tool choice none | 0/3 | 3/3 | 3/3 | 3/3 |
| Named tool choice | 0/3 | 0/3 | 3/3 | 3/3 |
| Frozen replay structural checks | 20/20 | 20/20 | 20/20 | 20/20 |
| Reasoning-on contracts | 9/9 | 9/9 | 9/9 | 9/9 |
| Reasoning-off contracts | 9/9 | 9/9 | 9/9 | 9/9 |
| Context retrieval | 12/12 | 12/12 | 12/12 | 12/12 |
| Over-context gateway rejection | Pass | Pass | Pass | Pass |
| Exact prompt count equals completion usage | 12/12 | 12/12 | 12/12 | 12/12 |
| Engineering tasks validated | **9/10** | **7/10** | **7/10** | **8/10** |

All 12 prompt counts also match across each original/candidate pair. Deep named-tool tests returned `read_file` alongside the forced `run_tests` on every trial. Original deep none responses returned HTTP 200/normal stop but failed the output predicate; the retained result does not establish the exact underlying predicate failure. Replay success is structural, not semantic task success. Over-context rejection proves gateway admission behavior, not GPU-overflow recovery.

Response caching was globally disabled under the reconciliation lock during these runs. Protocol/context non-streaming completions additionally required observed BYPASS headers; streaming bypasses by design. Engineering uses the globally disabled setting but does not independently inspect each response header. Raw generated reasoning and session content were not retained in the delivered evidence.

### Engineering outcomes and failure classes

| Task | Deep original | Deep candidate | Lead original | Lead candidate |
|---|---|---|---|---|
| H01-semver-range | Pass (1 attempts) | Pass (1 attempts) | Pass (1 attempts) | Pass (1 attempts) |
| H02-cron-next | Pass (1 attempts) | Pass (1 attempts) | Fail (3 attempts) | Pass (3 attempts) |
| H03-json-patch | Pass (1 attempts) | Pass (1 attempts) | Pass (1 attempts) | Fail (3 attempts) |
| H04-build-order | Pass (1 attempts) | Pass (1 attempts) | Pass (1 attempts) | Pass (1 attempts) |
| H05-retry | Pass (1 attempts) | Pass (1 attempts) | Pass (1 attempts) | Pass (1 attempts) |
| H06-allocate | Pass (1 attempts) | Pass (1 attempts) | Pass (1 attempts) | Pass (1 attempts) |
| H07-sqlite-rebuild | Fail (3 attempts) | Request timeout, 600 s | Pass (2 attempts) | Pass (3 attempts) |
| H08-glob | Pass (2 attempts) | Not admitted: pool unavailable | Fail (3 attempts) | Fail (3 attempts) |
| H09-ledger-root-cause | Pass (1 attempts) | Not admitted: pool unavailable | Pass (1 attempts) | Pass (1 attempts) |
| H10-perf-report | Pass (1 attempts) | Pass (1 attempts) | Fail (3 attempts) | Pass (2 attempts) |

Deep candidate H07 was actually dispatched, then timed out after 600 seconds. The source harness reports zero completed attempts for that record; this does not mean no request ran. H08/H09 were rejected during health demotion, so their semantic correctness is unknown. H10 was subsequently admitted and passed. Ledger request `c955e54f-077a-485e-b7a6-35ebb419c3d8` establishes the selected worker, 746-token prompt, 12,288 completion allowance, timeout and following rejections. Recovery admitted the next successful request 9.65 seconds after the timeout. The inspected deep incident journal has no candidate crash/restart or kernel GPU reset/OOM observed; the candidate was stopped deliberately for restoration. See `deep-timeout-ledger.json` and sanitized `deep-incident-journals.json`.

Lead candidate improved cron and performance-report outcomes but regressed JSON Patch: all three attempts failed a hidden mutation/copy-semantics check (`{'b': [1, 2, 99]}` versus `{'b': [1, 2]}`). Glob remained incorrect on both. These are generated-code correctness failures, not admission failures. A higher aggregate score does not establish non-regression. One repeat does not establish a stable model-quality ranking.

For the seven deep tasks that passed on both runtimes, total wall time was 1,863.1 s original versus 1,891.6 s candidate (+1.53%). The candidate's raw ten-record average is misleading because two records never entered inference. No engineering speedup is established for deep.

### Memory, temperature and performance

| Run | Target GPU sampled minimum free VRAM | Maximum temperature | Throttling | Documented 4 GiB floor |
|---|---:|---:|---|---|
| deep-baseline | 0.603 GiB | 74°C | None sampled | Failed |
| deep-candidate | 0.949 GiB | 74°C | None sampled | Failed |
| lead-baseline | 9.220 GiB | 76°C | None sampled | Met in samples |
| lead-candidate | 9.174 GiB | 76°C | None sampled | Met in samples |

Deep fails the documented headroom floor on both versions. Lead retains over 9 GiB sampled free, but that does not override its correctness regression. Measurements use driver-reported byte totals, not an assumed 32-minus-reserve model budget. Five-second samples observe approximately minute-refresh GPU metrics, filtered to each completed run and freshness ≤120 seconds; these are sampled extrema, not absolute instantaneous peaks. All four complete test intervals have observations. Resource evidence: `resource-comparison.json` and `runtime/resource-samples.jsonl`.

Median tokens/s across the three insertion depths at each target prompt size:

| Model / target tokens | Original decode | Candidate decode | Original prompt eval | Candidate prompt eval |
|---|---:|---:|---:|---:|
| deep / 16,384 | 17.22 | 17.52 | 583.73 | 407.50 |
| deep / 32,768 | 15.20 | 15.66 | 522.87 | 359.93 |
| deep / 49,152 | 13.61 | 14.19 | 515.67 | 348.99 |
| deep / 59,392 | 12.73 | 13.35 | 497.27 | 335.72 |
| lead / 16,384 | 53.33 | 62.34 | 1167.26 | 962.31 |
| lead / 32,768 | 48.96 | 55.30 | 1050.22 | 891.51 |
| lead / 49,152 | 44.63 | 50.39 | 1024.60 | 880.50 |
| lead / 55,296 | 42.95 | 48.41 | 998.34 | 865.02 |

Candidate decode was descriptively faster, while observed prompt evaluation was slower (deep roughly 30–32%, lead 13–18%). Do not advertise decode alone as an end-to-end gain. Serial runs, different completion lengths and uncontrolled prompt-cache/GPU-clock state prevent a causal kernel speedup claim. The context configuration is 65,536; these retrieval prompts reserve reasoning and answer space rather than filling all 65,536 tokens with input. Full-context workload soak, concurrent-client fairness and broader performance distributions remain unqualified.

## Prioritized work now

### Current correctness work takes priority over blanket upgrades

1. **Timeout health classification — open [issue #9](https://github.com/mikeholownych/homelab-ai/issues/9).** The deployed, byte-matched runtime explicitly marks a worker unhealthy on `TimeoutError`: [`orchestrator_runtime/runtime.py:1819` at canonical main](https://github.com/mikeholownych/homelab-ai/blob/5b83ac65899901a5c2470c703fa4238e015e64f3/orchestrator_runtime/runtime.py#L1819). Fresh ledger evidence (`deep-timeout-ledger.json`) correlates request `c955e54f-077a-485e-b7a6-35ebb419c3d8`: selected at 12:55:41 EDT with 746 exact prompt tokens, 12,288 completion allowance and 65,536 context; timeout at 13:05:41, followed by two pool rejections. Another request was admitted 9.65 seconds later and completed. This is a request-timeout/recovery fan-out, not a context-capacity refusal or proof of a candidate-process crash. Issue #9's older 60-second incident must not be treated as the current timeout: this run used 600 seconds. Existing tests check no timeout replay (`tests/test_gateway_platform.py:434`) and timeout metrics (`tests/test_orchestrator_observability.py:443`), but the latter manually re-enables the worker afterward. Add the missing request-failure-versus-worker-health regression and retain genuine-unavailability coverage; do not hide the issue with blind retries or longer deadlines.
2. **Cache request equivalence.** An isolated synthetic probe reproduced a semantic hit across opposite `==`/`!=` operators (similarity 1.0), plus exact-key collisions when changing `max_tokens`, `response_format`, `tool_choice` or `parallel_tool_calls`. Source: [`orchestrator_runtime/cache.py:43`](https://github.com/mikeholownych/homelab-ai/blob/5b83ac65899901a5c2470c703fa4238e015e64f3/orchestrator_runtime/cache.py#L43), [`cache.py:133`](https://github.com/mikeholownych/homelab-ai/blob/5b83ac65899901a5c2470c703fa4238e015e64f3/orchestrator_runtime/cache.py#L133). Evidence: `cache-correctness-probe.json`, verdict `DEFECT_REPRODUCED`. The probe changed no deployed state. Fix and test request equivalence before trusting cached coding/tool responses. Qualification disabled response caching globally and checked observed bypass on protocol/context completions.
3. **Measured memory acceptance.** Both deep runtime variants fail the documented 4 GiB physical headroom requirement. [`docs/v1.0.0/V1.0.0-REQUIREMENTS.md:113`](https://github.com/mikeholownych/homelab-ai/blob/5b83ac65899901a5c2470c703fa4238e015e64f3/docs/v1.0.0/V1.0.0-REQUIREMENTS.md#L113) uses a systemd `MemoryCurrent` command to support a VRAM claim; service RAM is not GPU VRAM. Replace that acceptance evidence with actual device-memory observations at the required context point, and choose capacity/configuration changes through measured candidate experiments.
4. **Per-model capability evidence.** Deep named-tool choice fails on both runtimes; lead baseline passes the same dedicated test. Preserve that distinction and bind evidence to runtime, model artifact, template/configuration and budget. Static model-digest-level `VERIFIED` labels inherited by a new runtime do not establish current qualification. Bind the deep shard manifest explicitly; its advertised identifier was not derived from the newly measured file hashes in this review. The inventory’s 8 GiB reserve/floor declarations are not evidence of an enforced GPU-memory admission gate.


5. **Lead regression and repeatability.** Retain the failed candidate JSON Patch cases, run an isolated matched repeat before reconsidering a lead-only upgrade, and require task-level non-regression plus prompt/decode and end-to-end measurements. Do not replace these negative records with an aggregate 8/10 claim.
6. **Upstream the prerequisite work as reviewable changes.** The gateway repair, regression tests and optional per-worker image/cache controls are included in the qualification branch. Integrate them through normal review and exact-SHA CI before claiming canonical main supports the workflow. Do not overwrite production client scopes with a broader historical declaration.

## Upstream developments: relevance and limits

| Development | Verified relevance | Disposition now |
|---|---|---|
| llama.cpp v0.7.0 / b11669 | Exact binary/image physically tested against both actual models; CPU reasoning-budget 12 checks plus template/parser checks passed, with 8 Jinja skips. Protocol/context compatibility largely passes. | **No promotion:** deep timeout/admission, named-tool and memory failures; lead JSON Patch regression. |
| Quantized-KV TILE decode, PR 26689 | Merge `d077b4c21466cfad678b07b05b557599f4db3974` is already an ancestor of original `5fc4f3c8c…`, which is 677 commits beyond it. | Already deployed code ancestry; no new upgrade benefit. IQ1_M weights do not prove quantized KV. A q4/q8 KV experiment needs separate accuracy/headroom qualification. |
| oneAPI 2026.1 compiler | Both original and candidate binaries report IntelLLVM 2026.1.1. | Already that compiler generation; comparisons against 2025.3 do not transfer as a fresh appliance gain. |
| OMIX 0.4 | Intel support matrix includes B65. Appliance remains OMIX 0.3.0-9~26.04 and libze-intel-gpu1 26.22.38646.7-1~26.04~ppa1. | Vendor support reviewed; **not physically qualified or upgraded**. Host compiler package generation differs from the container binary's compiler. |
| Linux 7.3 | No measured appliance-specific benefit established; appliance remains 7.0.0-38-generic. | No kernel change or physical qualification. |
| Intel Vulkan prefill FA, PR 29357 | Targets Vulkan, whereas production uses SYCL. | No SYCL performance claim or backend change justified. |
| Decision/draft models | Upstream availability does not establish gateway integration, useful orchestration behavior or safe combined memory use here. | No download/deployment/physical model qualification. Define a bounded task, artifact/template identity, correctness and memory experiment after current blockers. |

Primary upstream references: [v0.7.0 release](https://github.com/ggml-org/llama.cpp/releases/tag/v0.7.0), [b11669 artifacts](https://github.com/ggml-org/llama.cpp/releases/tag/b11669), [quantized-KV TILE PR 26689](https://github.com/ggml-org/llama.cpp/pull/26689), [Intel OMIX support matrix](https://dgpu-docs.intel.com/overview/support-matrix/omix-support-matrix.html), [Vulkan PR 29357](https://github.com/ggml-org/llama.cpp/pull/29357). These sources establish scope/support; appliance outcomes come from the retained runs.

## Implementation, tests and historical setup failures

Canonical ASGI lacked the worker-list/drain/undrain routes already expected by `playbooks/candidate.yml` and `roles/llama_cpp_container/tasks/start_worker.yml`. The explicitly authorized parity repair delegates existing runtime semantics and retains admin scope and origin protections. It passed 13 isolated checks, the 87-check targeted gateway suite, and 10 lifecycle/release contracts; those counts overlap and are not a summed unique-test total. Authenticated live list/drain/undrain passed. Deployed Python packages byte-match reviewed source (`deployed-gateway-source.json`); rollback material remains on the appliance.

Reviewed implementation commits included in the qualification branch:

- `b9d42e73f06b7ac7cb794a933e11a95ead203350`: ASGI drain route parity.
- `3f6602366838838d249994bde0b0866057152eb5`: gateway release identity.
- `0012e15382e88589503338131ffe8a8b25c5061a`: regression tests.
- `2587bb1d2fcb6df796d752b2d6f11f963bc4e948`: optional immutable per-worker image selection; unchanged baseline renders.
- `56ac4e4d515ad2ee8c11f50041ff6153c143a1ec`: expose existing cache switch through Ansible.
- `37e821a8f16ab01ff45213c64e75e24a21e17523`: preserve deployed client scopes.

`runtime/qualification-source.patch` and `runtime/source-manifest.json` retain the complete delta against canonical main. Only one worker was replaced at a time. Existing lifecycle guards and an exclusive reconciliation lock were retained; no force-restart bypass was used. Deep candidate was explicitly drained to zero in-flight work before restoration. During lead isolation the deep container remained at its restored 17:11:30 start time; final image/start-time evidence corroborates continuity.

The initial isolated-controller attempt failed before candidate replacement because its CA fetch path was missing. Another controller Git-object ownership error prevented snapshot selection after successful restoration. Both were repaired through Ansible. The retry reused the completed deep baseline only after identity/input-manifest checks. An earlier strict READY smoke failed its exact answer check under a smaller output budget; it is retained as historical setup evidence, not current health. Final strict READY checks on both originals pass. No setup failure is counted as a candidate benchmark result.

## Evidence index and remaining acceptance

- Four run directories: `runtime/{deep,lead}-{baseline,candidate}/`, each with immutable identity, summary, protocol, reasoning contracts, long context and engineering results.
- `runtime/qualification-orchestration.log`: successful orchestration recap (`failed=0`); benchmark failures remain recorded separately.
- `deep-timeout-ledger.json`, `deep-incident-journals.json`: sanitized incident correlation.
- `cache-correctness-probe.json`: isolated negative fixture, verdict DEFECT_REPRODUCED; no cache fix deployed.
- `resource-comparison.json`, `runtime/resource-samples.jsonl`: timestamped matched observation intervals.
- `production-final-oct22.json`, `final-runtime-images.json`, `final-service-journals.json`, `final-settings.json`: fresh restored production proof.
- `runtime/final-controller-state.json`: reconciliation/cleanup proof.
- `model-file-hashes.json`: final measured GGUF file hashes, distinct from inventory artifact labels.
- `canonical-repository-refresh.json`: October 21 main, CI and open issues. Open #9 is directly reproduced; #6 Vault restore, #5 monitoring integration and #2 coordinated rotation remain separate backlog items. Nexus #8/#10/#12 do not substitute for appliance acceptance; #3/#4 were not open in this snapshot.

Promotion remains blocked. There is no physical OMIX/kernel qualification, new specialist-model qualification, broad concurrency/soak qualification, full default-lead-off engineering qualification, or clean-install/rollback acceptance for the disposable candidate image. Current health and successful CI establish their stated checks only. The next justified implementation work is gateway/cache correctness, measured deep-memory acceptance and runtime-bound capability evidence, followed by controlled candidate repeats.
