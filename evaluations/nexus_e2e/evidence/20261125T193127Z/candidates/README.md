# Challenger artifacts (on-disk, ai-5820-01)

Recorded 2026-11-25 during quality-levers campaign.

| Candidate | Path under `/var/lib/local-ai/models/gguf/` | sha256 |
|-----------|--------------------------------------------|--------|
| Devstral Small 2 24B Q4_K_M | `Devstral-Small-2-24B-Instruct-2512-Q4_K_M.gguf` | `d14ba9edee1bb4c4996a726deb81e49ae81800a3216f0774634238c380aee496` |
| GLM-4.7-Flash Q4_K_M | `glm-4.7-flash/GLM-4.7-Flash-Q4_K_M.gguf` | `29837ed2c0fc5f51981adf8ac8083fcf80743c598381f13e9f06cbad0498b174` |

Inventory profiles: `devstral-small2`, `glm47-flash` in `host_vars/ai-5820-01.yml` (`llama_cpp_container_candidate_profiles`).

Qualify via durable candidate transaction (not ad-hoc port hits):

```sh
# From repo root, after inventory is deployed/synced as required by candidate playbooks:
# playbooks/controller_candidate_transaction.yml -e candidate=devstral-small2 ...
```

Do not promote to production pins without CAIS engx evidence.
