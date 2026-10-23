# Gateway correctness and Intel LLM Scaler follow-through — October 23, 2026

**Completed:** repaired and deployed gateway cache/request-timeout handling, added bounded benchmark tools, ran live sequential/two-client probes, and prepared a source-bound SGLang candidate plan. **No model runtime promotion or SGLang GPU qualification occurred.**

All remote work used Ansible. Canonical main was rechecked at `5b83ac65899901a5c2470c703fa4238e015e64f3`. The preceding published branch at `a349e243eeda820d0a123fbc45543ba0df0b81df` completed full CI successfully: [39852521214](https://github.com/mikeholownych/homelab-ai/actions/runs/39852521214). That historical success does not stand for CI on the new commits.

## Implemented and deployed

- Cache keys include the complete request's response-affecting controls, including unknown future fields, plus runtime/client/worker/configuration scope. Only transport request IDs and explicit cache preferences are excluded from the request hash.
- Approximate text matching is removed from runtime response retrieval. Legacy similarity lookup additionally requires identical full requests and is disabled by default. Opposite operators, case changes, tool controls and schemas cannot borrow a similar prompt's answer.
- HTTP cache-bypass headers reach both synchronous and ASGI dispatch, including the separate ASGI non-streaming path. Header names are case-insensitive; explicit `cache:false` bypasses too.
- Streaming announces `X-AIHost-Cache: BYPASS` when the stream starts, rather than after headers have already been sent.
- Cache reuse is isolated between clients, artifact/runtime changes and hot-reloaded policies.
- A request timeout remains a reported timeout, with no retry and bounded admission backoff. It does not fabricate a worker-health failure or trip worker/pool availability circuits. Existing independent probes and genuine provider-failure handling still mark unavailable workers unhealthy.

Reviewed code commit: `3fa01154308805e080bb6e42b4f82d5875fd09fd`. Matching release/inventory commit: `ca6179920a9fa1111661f2ef130edc478a194756`. Deployed release: `/var/lib/aihost/releases/t5820-gateway-3fa0115`.

Ansible retained rollback unit/environment files, waited for idle production, deployed only the three gateway Python packages, restarted the gateway, verified strict readiness and authenticated admin list/drain/undrain, and selected the matching reconciliation snapshot. All 26 deployed Python files byte-match reviewed source (`deployed-gateway-source.json`). Client registry semantic equality with the pre-qualification backup passed. Both original workers retained their PIDs, start times and zero automatic restarts; both still use original immutable image `sha256:2f4940610095fe48aabff3db7f87feb4f553081302b1a5a8744a589eb123b451`. Kernel remains `7.0.0-38-generic`.

No kernel/driver modification, specialist-model download, SGLang image build/start or inference-backend switch was performed.

## Verification and retained failures

The new regression suite first reproduced **16 failures / 3 passes** against the unchanged published implementation (`baseline-regressions.log`). Development testing caught an incomplete removal of the old semantic-hit branch and then a missing non-streaming ASGI header path; both were corrected before deployment. These were implementation/test findings, not production incidents.

The corrected set passed **129 targeted tests**, including cache, health, timeout, HTTP, streaming, credential contracts and benchmark/preflight checks. The final early-stream-header change then passed **28 targeted stream/cache/correctness checks**, followed by matching release checks. Earlier lifecycle/release coverage passed 10 checks. These counts overlap and are not a unique-test sum. YAML lint and Ansible lint passed; the latter processed 1,204 files with zero rule failures/warnings. One Starlette HTTPX deprecation warning remains in tests.

**Seven live cache assertions passed** through authenticated TLS and original lead inference: initial MISS, exact HIT, lowercase Cache-Control no-store BYPASS, lowercase X-AIHost-Cache BYPASS, changed token allowance MISS, equality-expression MISS and inequality-expression MISS. Each answer and finish reason matched its contract. No credential or generated reasoning content is retained. See `live-cache-verification.json`.

The timeout/health regression exceeds the circuit-breaker threshold using six dispatched timeouts, verifies no replay, preserves the prior health observation without fabricating success, then completes the next request. A separate failure observation still blocks dispatch. The unchanged 600-second physical candidate workload was not rerun; do not call its earlier failure overturned by unit coverage or these short live probes.

## Fresh bounded benchmark

New tools: `evaluations/engx/controlled_probe.py`, `sample_drm_memory.py`, `candidate_preflight.py`, and `playbooks/qualification_probe.yml` with the `controller_qualification_probe.yml` lock-owning entrypoint. Credential material arrives on stdin; requests use the normal TLS gateway and scoped authority. The playbook owns the reconciliation lock externally, guarantees sampler stop/collection and leaves worker services intact.

Both profiles used the **original models/runtimes**, reasoning-off, temperature zero and three repeats per streaming/non-streaming mode. Each model also performed three quantity variants of one synthetic stock/reservation tool scenario: read stock, reserve the requested quantity, then return the receipt from the tool result. Tools are simulated data; no generated code or external side effects execute.

| Client profile | Model | Latency/output contracts | Sequential stateful variants | Median request seconds | Median first-content seconds (SSE) |
|---|---|---:|---:|---:|---:|
| sequential | lead | 6/6 | 3/3 | 0.170 | 0.100 |
| sequential | deep | 6/6 | 3/3 | 0.309 | 0.204 |
| two-clients | lead | 6/6 | 3/3 | 0.241 | 0.137 |
| two-clients | deep | 6/6 | 3/3 | 0.527 | 0.386 |

Every successful probe response was observed as BYPASS, including streaming. Client concurrency two applies to the latency requests; tool scenarios remain sequential. Each original worker still has one native slot, so the two-client profile exercises queueing, not GPU batch-size-two numerical invariance.

Prefix cache state is explicitly **uncontrolled**. Repeated prefixes and different request ordering can affect latency; these tiny READY responses are smoke measurements, not throughput, cold/warm comparisons or a runtime speedup claim. The synthetic scenario is **not BFCL**, a representative coding corpus or full long-context qualification. Reasoning-off successes do not replace the earlier reasoning-on deep named-tool failures or the earlier candidate engineering results. A pinned BFCL integration remains in the candidate plan.

High-frequency DRM sampling ran every 0.5 seconds, deduplicating repeated handles by device/client. The sequential profile retained 61 samples with maximum interval approximately 0.552 seconds. `resource-summary.json` reports both profiles. Resident totals are per-client observations and may double-count shared allocations across clients. Aggregate whole-device GPU metrics retain their independent age and approximately minute refresh. Neither source establishes an absolute transient peak or closes the existing deep-model 4 GiB headroom failure.

## SGLang preparation and unresolved prerequisites

The bounded read-only preflight inspected the actual lead GGUF: `qwen35moe`, 733 tensors, 22,134,528,992 bytes, unchanged mtime, and no MTP/nextn-named tensors. Header-declared context is 262,144; the required operating context remains 65,536. No matching Qwen3.6-35B-A3B HF configuration/tokenizer/index directory was found under the production model root. Existing dense Qwen3.8 config files are not substitutes.

Intel source is pinned at `09f2953998ef8274b48ecaa717dbfedad1e058c4`. Its SGLang recipe uses OMIX 0.1.0/Ubuntu 24.04/Torch 2.11, whereas its recently migrated vLLM recipe uses OMIX 0.4/Ubuntu 26.04/Torch 2.14. Keep those experiments distinct. The gateway currently has llama.cpp and vLLM native observation adapters; SGLang requires a separately validated observer and tokenizer contract before qualification.

`sglang-candidate-plan.md` provides concrete artifact/build/tokenization/isolation/memory/correctness/rollback gates. TP1 on GPU 0 comes first. Upstream's default TP2 consumes both production GPUs and requires a separate expanded isolation window if TP1 is insufficient. No unsupported self-draft MTP option was enabled on the existing GGUF.

## Acceptance ledger

| Item | Status and limit |
|---|---|
| Request-equivalence and bypass repair | Implemented, targeted tests passed, deployed bytes verified, live cache checks passed |
| Timeout classification | Implemented/deployed; regression preserves independent failure detection; long original timeout case not physically repeated |
| Bounded sequential/two-client probes | Completed on both original models, reasoning-off; all stated contracts passed |
| High-frequency memory observations | Implemented/exercised; no whole-device instantaneous peak guarantee |
| Original worker restoration/continuity | Original workers were never swapped in this run; PIDs/image/start times unchanged, fresh completions and 2/2 health passed |
| Previous llama.cpp candidate | No promotion; October 21 negative outcomes remain acceptance evidence |
| SGLang candidate | Preflight and gated plan prepared; missing matching model configuration and native adapter; no image/GPU execution |
| BFCL / MTP / LMCache / OMIX physical comparison | Unqualified, separate follow-up experiments |
| Full CI for newly published commits | Separate from the successful prior branch CI; consult the publication receipt/status |

Evidence is retained alongside this report. Implementation and evidence are published on the existing qualification branch; as-run receipts marked `published:false` retain their historical meaning. Production release identity is bound to code commit 3fa0115; later tooling/evidence commits do not change deployed gateway Python bytes.
