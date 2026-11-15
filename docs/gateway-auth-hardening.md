# Gateway authentication hardening (2026-11)

Behaviour of the orchestrator gateway (ASGI production engine `orchestrator_gateway/asgi.py`; the sync server
`server.py` mirrors the parts it shares).

| Rule | Behaviour |
|---|---|
| Admin routes (`/v1/admin/status`, `/v1/admin/reload`, `/v1/admin/workers/{id}/recover`, `/admin`, `/admin/workers…`) | Accept only a client holding the `admin` scope, presented as `Authorization: Bearer …`. The monitoring token never grants admin. |
| Monitoring token | Valid for the monitoring routes only (`/health`, `/metrics`, telemetry). Compared with `hmac.compare_digest`. |
| Query-string token | `?token=` is not read on any route. Browsers cannot reach `/admin` any more without an Authorization header (use a client such as curl, or a browser extension that adds the header). |
| Local origin | All admin routes refuse requests that originate on the gateway host when the listener is `remote`, exactly like `/admin/workers` already did. |
| JWT | One algorithm family, chosen from the configured key: `jwt_public_key` → `RS256` only, `jwt_secret` → `HS256` only. Configuring both is a startup error, as is an explicit algorithm list that crosses families or contains `none`. Tokens must carry `exp`. Only `jwt.PyJWTError` means "invalid token". |
| mTLS | `orchestrator_gateway_tls_require_client_cert` (default `false`) is rendered to `ORCHESTRATOR_TLS_REQUIRE_CLIENT_CERT`. It is **not** enabled in production inventory. |

## Callers of the admin routes

Nothing in this repository called an admin route with the monitoring token. The callers that exist already use
`admin`-scoped clients and are unchanged:

- `roles/llama_cpp_container/tasks/start_worker.yml` (drain/undrain through `/admin/workers/{id}/…`, admin client token file);
- `evaluations/engx/verify_production_gateway.py` (`/admin/workers`, admin input).

External tooling that used the monitoring token against `/v1/admin/*` or `/admin` (for example vllm-top, which lives
outside this repository) must be given an `admin`-scoped client, or moved to the monitoring routes.

## Follow-up: turning on mTLS

1. Issue a client certificate to every remote caller (engx host, workstation, orchestrators).
2. Set `orchestrator_gateway_tls_require_client_cert: true` in the host inventory and converge.
3. Verify each caller still reaches `/health` through the remote listener before closing the maintenance window.
