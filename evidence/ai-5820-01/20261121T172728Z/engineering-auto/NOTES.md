# engineering/auto quality_first — live qualification on the 5820 front door

- UTC: 2026-11-21 17:27–17:29 (evidence dir `20261121T172728Z`)
- Branch `feat/engineering-auto-quality-first`, code commit 35008cb, release bump 0aecc88
  (`orchestrator_gateway_release_id` = `*-gateway-35008cba…` on both hosts)
- Front door: `https://10.0.8.5:8443`, operator token (read over ssh, not stored), controller trust store CA.

## Deploy

```
ansible-playbook -i inventory/production playbooks/inference.yml \
  --limit ai-5820-01,ai-ms-s1-max-01 --tags orchestrator,console \
  -e vllm_top_console_binary_src=/home/mike/Projects/aihost/vllm-top/target/release/vllm-top
```

- Check-mode run first (`--check --diff`), then real apply: ai-5820-01 ok=80 changed=17 failed=0; ai-ms-s1-max-01 ok=79 changed=21 failed=0 (`ansible-apply.log`).
- `vllm_top_console_binary_src` override: the default path (`<worktree>/vllm-top/target/release/vllm-top`) does not exist in the worktree (build output is untracked). The binary used is the 1.0.4 build from the main checkout; its sha256 equals the one already installed on 5820 (`1799f441…`).
- Post-deploy: both gateways active (new release dirs), 5820 readiness ExecStartPre passed, `vllm-top-console` active on MS-S1 (`service-verify.txt`).

## Probes (`X-AIHost-Route`)

| # | Request | Route header | Result |
|---|---------|--------------|--------|
| 1 | `engineering/auto`, "Say ready in one word." | `rule=engineering-auto;pool=lead;worker=b0-live-llama-worker1;fallback=false` | PASS (lead) |
| 2 | `engineering/auto`, code prompt + `tools` | `rule=engineering-auto;pool=rocm;worker=ms-s1-hip-coder30b;fallback=false` (termination `tool_calls`) | PASS (rocm) |
| 3 | `engineering/auto`, proof + trade-off reasoning | `rule=engineering-auto;pool=deep;worker=b0-live-llama-deep-worker2;fallback=false` | PASS (deep) |
| 4 | `engineering/interactive-rocm` | `rule=alias:engineering/interactive-rocm;pool=rocm;worker=ms-s1-hip-coder30b` | PASS (rocm only) |
| 5 | regression pins `engineering/lead`, `engineering/deep` | `rule=alias:engineering/lead;pool=lead…`, `rule=alias:engineering/deep;pool=deep…` | PASS (still SYCL workers) |

`/v1/models` lists `engineering/auto` alongside the existing aliases (`models.json`).

## Observations

- The response body `model` field shows the selected pool alias (`engineering/b0`, `engineering/interactive-rocm`, `engineering/deep`), not `engineering/auto`; the route header is the source of truth.
- Probe 3 stopped on `output_limit` (max_tokens=256); only routing was being qualified.

## ROCm worker health

`llama-hip-qwen3-coder-30b.service` active; health JSON `http_status: 200` (`rocm-worker-health.txt`).

## Failover live test — SKIPPED

Stopping the production HIP worker on ai-ms-s1-max-01 would take down the MS-S1 front door and `engineering/interactive-rocm`, and the 5820 gateway start is coupled to remote-worker readiness (`aihost-gateway-readiness`), so a mishap during restore could block a 5820 gateway restart. Failover is covered by unit tests instead; no live evidence is claimed.
