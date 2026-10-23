# SGLang candidate: prepared gates, no GPU qualification

Intel reference: intel/llm-scaler `09f2953998ef8274b48ecaa717dbfedad1e058c4` (main observed October 23, 2026). Read `sglang/scripts/start_qwen3_service.sh`, `sglang/docker/Dockerfile`, `sglang/README.md` and `sglang/scripts/bfcl/README.md` at that SHA.

The appliance remains on its original two llama.cpp/SYCL models. No SGLang image was built, downloaded or started, no model weights were downloaded, and no driver/kernel change was made in this work.

## Actual preflight

`sglang-model-preflight.json` records a bounded GGUF header inspection, without reading tensor data or executing model code:

- Existing lead: Qwen3.6-35B-A3B-UD-Q4_K_M.gguf, 22,134,528,992 bytes, architecture `qwen35moe`, 733 tensors.
- Header context declaration: 262,144; this is not the appliance's operating limit. Candidate acceptance remains at 65,536.
- No tensor names containing `mtp` or `nextn` were found. Do not enable self-draft MTP on this file by copying Intel's MTP example. A separate matching draft could be investigated later.
- The existing GGUF's inode/size/mtime stayed stable during inspection. Its mtime matches the October 22 measured-file evidence.
- No matching Qwen3.6-35B-A3B HF configuration/tokenizer/index directory was found under the production model root. The available Qwen3.8-27B directory describes a different, dense model; it is not a substitute.
- Appliance container filesystem had 29,151,592,448 free bytes; available host RAM was approximately 56 GiB at observation. Controller work filesystem had approximately 204 GiB free. These are preparation observations, not established image-build requirements or GPU admission proof.

## Keep independent experiments separate

Intel's inspected SGLang Dockerfile uses OMIX 0.1.0 / Ubuntu 24.04 and Torch 2.11 XPU. Its vLLM Dockerfile separately migrated to OMIX 0.4 / Ubuntu 26.04 and Torch 2.14 XPU in `1977a1a`. Do not describe an unmodified SGLang build as the OMIX 0.4 experiment, or mix backend, compiler, model format and cache changes into a claimed single-variable speedup.

## Execution gates

| Gate | Acceptance | Current status |
|---|---|---|
| Model provenance | Matching HF config, tokenizer, template and weight-name index pinned to source revision and hashed against the exact GGUF artifact | Missing matching local files; do not substitute another model |
| Build provenance | Pin Intel source and every base-image/source dependency; build on controller, retain build log and immutable image digest | Not built; Intel's SGLang base uses a version tag, requiring digest resolution |
| Native backend observation | Explicit SGLang identity, actual configured context, tokenizer and per-request exact counts | Not integrated; gateway currently has llama.cpp and vLLM engine adapters only |
| Tokenization parity | Validate SGLang v0.5.13 `/v1/tokenize` against completion usage, including tools, named/none tool choice, reasoning and output-format controls | Source API reviewed; no live SGLang result |
| Isolation | Start with GPU 0 only, `TP_SIZE=1`, one slot, explicit 65,536 context; drain original lead and restore it in an always block | TP1 fit/performance unestablished; no worker swap performed |
| Memory | At least 4 GiB measured device headroom during loading, prefill and decode; high-frequency DRM resident data and independently fresh whole-device data | No candidate measurements |
| Correctness | Existing engineering corpus plus forced/none/parallel tools, multi-turn state, JSON, reasoning on/off, SSE and long-context checks | Candidate untested; original negative results remain valid |
| Performance | Identical inputs/budgets, controlled or explicitly unknown prefix state, repeated prefill/decode/TTFT/end-to-end measurements | Candidate untested |
| Rollback | Exact original image, model and service identity; both original fresh completions; clean reconciliation source and released lock | Existing llama.cpp restoration mechanism verified; SGLang lifecycle needs its own implementation/tests |

SGLang v0.5.13 exposes `/model_info`, `/server_info` and `/v1/tokenize`. The tokenize handler uses its chat-serving template path. An adapter must preserve all template-relevant controls and fail closed on unsupported or unknown counts; mapping it to a generic vLLM adapter without checking those contracts is insufficient. Native HTTP source was inspected, not executed.

The upstream default TP2 recipe consumes both cards. It must not be substituted for the previously authorized one-worker isolation. If TP1 cannot meet the memory/correctness gates, prepare a separate two-GPU maintenance experiment before requesting the expanded window.

## BFCL and cache follow-up

The new synthetic multi-turn probe is not BFCL. The Intel BFCL kit pins `liu-shaojun/gorilla` at `9d49adb45bd765794fd6b0a0f8006e0b31b997d2`; its described validation is FP8. Review the pinned handler, adapt it to the authenticated gateway, retain selected case IDs/evaluator hash and run concurrency 1 before expanding. Do not advertise a BFCL score from the synthetic probe.

MTP, DFlash and LMCache remain separate later experiments. Begin any state-offload experiment with raw cache, prove eviction/reload/output equivalence, then compare compression; prefix reuse is not gateway response caching and does not repair request-equivalence defects.
