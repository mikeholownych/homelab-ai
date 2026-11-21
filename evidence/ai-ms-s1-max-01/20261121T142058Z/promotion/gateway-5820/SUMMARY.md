# Stage 3d: MS-S1 HIP worker advertised on the ai-5820-01 gateway (20261121T142058Z)

- Inventory (ai-5820-01): route `interactive-rocm` (model engineering/interactive-rocm -> pool rocm, no fallback, placed before `default`), alias `engineering/interactive-rocm`, remote worker `ms-s1-hip-coder30b` (http://10.0.8.6:8101, pool rocm), `orchestrator_gateway_production_worker_count: 3`. Lead/deep workers, their aliases and the other routes are untouched; `default` still routes to lead.
- Credential: streamed MS-S1 -> 5820 over ssh (never written on the controller) to /etc/local-ai/orchestrator/remote-ms-s1-hip-api-key, root:root 0600; sha256 prefix equal on both hosts (04b5733e7aaa89f2). Loaded into the gateway only via systemd LoadCredential. 5820 -> MS-S1:8101: /v1/models 200 with the key, 401 without.
- Release id unchanged (t5820-gateway-636b7fb...): no gateway code changed, tests/test_gateway_release_identity.py passes.
- pre/: engineering/lead -> worker=b0-live-llama-worker1 (SYCL), health healthy 2/2.
- ansible-check.log: --check --diff (changes: gateway.env, unit LoadCredential line; role also installs python3-venv, see concerns).
- ansible-deploy.log: playbooks/inference.yml --limit ai-5820-01 --tags orchestrator, failed=0; gateway restarted once at 14:27:09Z (~2 s), Intel workers not touched. ansible-rerun.log: changed=0, no restart.
- post/: lead -> b0-live-llama-worker1 (Qwen3.6 SYCL), deep -> b0-live-llama-deep-worker2 (Flash-Next SYCL), engineering/interactive -> interactive-model rule on lead,
  engineering/interactive-rocm -> x-aihost-route rule=alias:engineering/interactive-rocm;pool=rocm;worker=ms-s1-hip-coder30b (served qwen3-coder-30b-a3b-instruct-q8_0); tool call (finish_reason tool_calls) and SSE stream OK; /health?strict=true healthy with 3 workers; service-5820.txt: gateway, worker1, worker2, inference-policy active, NRestarts=0.
