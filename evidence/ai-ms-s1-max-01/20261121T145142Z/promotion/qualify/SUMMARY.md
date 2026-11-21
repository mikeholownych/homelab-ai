# Stage 3f: dual-front-door qualify (20261121T145142Z)

Probes use the `operator` client token (read over ssh from each host, never stored). TLS verified with each gateway's own CA (MS-S1: evidence/ai-ms-s1-max-01/gateway-ca.crt; 5820: controller trust store). No deploy or config change was made in this stage.

## 1. MS-S1 local gateway (https://10.0.8.6:8443) - ms-s1-local/
- Unauthenticated /v1/models -> 401; authenticated /v1/models serves only `engineering/interactive-rocm`; /health?strict=true healthy, 1 worker.
- Chat: `ready`, `x-aihost-route: rule=alias:engineering/interactive-rocm;pool=rocm;worker=ms-s1-hip-coder30b`, served `qwen3-coder-30b-a3b-instruct-q8_0`.
- Tool probe (get_weather): `finish_reason=tool_calls`; SSE stream ends with `[DONE]`.

## 2. 5820 gateway -> remote MS-S1 worker (https://10.0.8.5:8443) - 5820-rocm/
- Unauthenticated /v1/models -> 401; /v1/models lists engineering/{b0,deep,interactive,interactive-rocm,lead,lead-reasoning}; /health?strict=true healthy, 3 workers (lead, deep, rocm).
- Chat / tool / SSE on `engineering/interactive-rocm`: same `x-aihost-route ...pool=rocm;worker=ms-s1-hip-coder30b` header, served `qwen3-coder-30b-a3b-instruct-q8_0`, `finish_reason=tool_calls` for the tool probe, `[DONE]` for the stream.
- The ms-s1 worker log (service-ms-s1.txt) shows the llama.cpp slot completion for the request that arrived from 5820 (worker is reachable only from 10.0.8.5).

## 3. Intel regression (5820) - 5820-intel/
- `engineering/lead` -> `pool=lead;worker=b0-live-llama-worker1` (Qwen3.6-35B-A3B-UD-Q4_K_M, SYCL).
- `engineering/deep` -> `pool=deep;worker=b0-live-llama-deep-worker2` (Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M, SYCL).
- Neither routes to `ms-s1-hip-coder30b`; the rocm pool is reachable only through the explicit alias.

## Services
- service-ms-s1.txt: gateway + HIP worker active, NRestarts=0 (gateway), ufw 8101<-10.0.8.5, 8443<-10.0.8.95, 9100<-10.0.8.2.
- service-5820.txt: gateway active, NRestarts=0, no restart since the 14:27:09Z Stage 3d activation.
