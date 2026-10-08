# Design 05: work is initiated only by remote clients

- **Status:** ACCEPTED (review below), 2026-10-07.
- **Covers:** todo.md "Policy: no work initiated on the aihost".
- **Requirement (operator):**
  - production flow is remote client → gateway → worker;
  - SSH tunnelling is retired as a workload path;
  - no timer, smoke test, benchmark or service on ai-5820-01 initiates inference.

## Current state (verified 2026-10-07)
- The gateway binds 127.0.0.1:8010.
- The workstation (10.0.8.95) reaches it through an SSH tunnel (workstation `127.0.0.1:18010` → host `127.0.0.1:8010`), so all
  workload traffic arrives from loopback.
- On-host inference originators:
  - `roles/benchmarking/files/run_benchmark.py` (`/usr/local/libexec/local-ai-run-benchmark`);
  - `roles/vllm_xpu/files/validate_vllm.py` (`local-ai-validate-vllm`);
  - `tools/t5820_stream_probe.py`;
  - `~/engx/{engx.py,cand.sh,runqueue.sh}`.
- Retired vLLM units are still installed; `vllm_xpu` is still in `playbooks/inference.yml`.
- Non-inference local consumers (allowed):
  - the gateway HealthManager (`/health`, `/metrics`, `/slots` to workers);
  - the gateway readiness probe (`/v1/models`);
  - vllm-top (gateway `/health`);
  - node_exporter;
  - aihost-metrics.

## Selected design
1. **Two gateway listeners, separated by purpose:**
   - **Remote workload listener:**
     - HTTPS on `orchestrator_gateway_remote_address` (inventory: the host's VLAN address 10.0.8.5) port
       `orchestrator_gateway_remote_port` (8443).
     - Serves workload, admin and authenticated monitoring endpoints.
     - TLS: a private root CA is generated and retained on the Ansible controller under
       `~/.local/share/aihost/pki/ai-5820-01/`; its private key is mode 0600 and is never copied to the host or committed.
       The controller signs a gateway server leaf with SANs for IP 10.0.8.5 and DNS `ai-5820-01`, `CA:FALSE`, and
       `serverAuth` EKU. The host receives only the leaf certificate and its server private key.
     - The public CA trust anchor is published as `evidence/ai-5820-01/gateway-ca.crt` and installed by Ansible into the
       controller OS trust store and configured client trust paths. Clients trust that CA, not a pinned leaf. The Ansible role
       validates the chain, identity, EKU, key pair, and expiry; `orchestrator_gateway_tls_rotate_server` rotates the leaf
       without changing the CA trust anchor.
   - **Local monitoring listener:**
     - HTTP on 127.0.0.1:8010 (unchanged address, so vllm-top keeps working).
     - Serves only `GET /health` and `GET /metrics`. Any workload/admin path gets 403 `local_origin_forbidden`.
2. **Origin check (defence in depth):**
   - On the remote listener, a peer address that is loopback or any address configured on the host (collected at start and every
     60 s via `getifaddrs`) gets 403 `local_origin_forbidden` for workload/admin. This covers `curl https://10.0.8.5:8443` run on the
     host itself.
   - Evidence `local_origin_refused`; metric `aihost_local_origin_refused_total{listener}`.
3. **Network policy (`inference_policy` role, same table as Design 04):**
   - Chain `input`: `tcp dport 8443 ip saddr != @gateway_client_cidrs counter name gateway_remote_denied drop`.
   - `gateway_client_cidrs` is inventory `orchestrator_gateway_client_cidrs` (initially the operator workstation `10.0.8.95/32`).
   - Port 8010 is loopback-bound, so it is unreachable remotely by construction.
4. **Authentication:**
   - Per-client tokens with scopes (R6). Remote clients present them over TLS.
   - Admin (drain, candidate lifecycle) uses the `admin` scope over the same remote listener, from the controller.
5. **Retire on-host originators (W-CLEAN):**
   - Remove the benchmark and vLLM validate scripts from the host.
   - Remove the `vllm_xpu` and `benchmarking` roles from `inference.yml`.
   - Disable and remove the retired `aihost-vllm-worker1/2` units.
   - Remove `/usr/local/libexec/local-ai-{run-benchmark,validate-vllm,vllm-readiness}`.
   - Delete `~/engx` from the host after archiving evidence to the repository and controller.
   - `tools/t5820_stream_probe.py` stays in the repository as a client-side tool only.
   - Ansible validates afterwards that no unit or timer on the host references `/v1/chat/completions` or the gateway workload
     port. The check is part of Q-FINAL.
6. **Remote engx:**
   - `engx.py` runs on the client. Its bwrap sandbox uses a configurable interpreter `ENGX_PYTHON` with pytest (the client
     venv), bound read-only. It talks to `https://10.0.8.5:8443` with a `qualification`-scoped token and `model=candidate/<name>`
     or a production alias.
   - `ENGX_CA` points to the public gateway CA certificate.
   - Results are written client-side and committed to the repository (`evaluations/engx/results/`).
7. **Candidate lifecycle:** `playbooks/candidate.yml` on the controller (Design 03 R4). Nothing on the host starts workers ad hoc.
8. **Client migration (operator action; outside aihost control):**
   - Clients move from the tunnel to `https://10.0.8.5:8443` with their token and the configured CA trust anchor.
   - OpenCode 1.18.34's bundled Bun 1.3.14 honors `NODE_EXTRA_CA_CERTS`. On the verified Linux client, both OS trust and this
     additive runtime trust were tested. Set the variable before launching OpenCode; a running process does not inherit later
     shell or trust-store changes.
   - The report lists the exact values. aihost does not modify clients.

## Options considered
| Option | Verdict |
|---|---|
| Plain HTTP on the VLAN + IP allowlist | Rejected: removing the SSH tunnel would otherwise remove transport confidentiality for prompts (which may contain secrets). |
| mTLS | Deferred as unnecessary for now: bearer tokens over TLS with a private-CA-signed server identity plus an IP allowlist meet the requirement. Per-client tokens already give identity. |
| WireGuard to the host | Rejected for this workstream: adds a network dependency for every client, and the operator workstation is the only client. |
| Keep tunnel + header claiming remote origin | Rejected: unverifiable (a local process can claim anything). |

## Review (2026-10-07)
- **Requirement coverage:**
  - The remote path works (TLS + token + allowlist).
  - Host-originated workload is refused on both listeners: the loopback listener is monitoring-only, and the remote listener's
    origin check refuses host addresses.
  - The SSH tunnel lands on the monitoring-only listener, so workload over it is refused.
  - On-host originators are removed and checked.
  - Local monitoring keeps working.
  Passes.
- **TLS client compatibility correction (2026-10-07):** replaced the original self-signed CA:TRUE server certificate with a
  CA-signed CA:FALSE server leaf with `serverAuth`, IP/DNS SANs, and a controller-only CA key. A fresh OpenCode 1.18.34
  process completed a real authenticated request after leaf rotation. Native SSE returned HTTP 200, `text/event-stream`,
  multiple events and `[DONE]`. Untrusted Node TLS failed with `UNABLE_TO_VERIFY_LEAF_SIGNATURE`; configured trust passed.
  Host-origin workload remains 403, unauthenticated `/v1/models` remains 401 after TLS verification, and remote worker ports
  8000/8001/8003 remain blocked.
- **Fail-closed:**
  - The default listener allows no workload.
  - An unknown origin gets workload only on the remote listener with a valid token and an allowlisted source.
  Passes.
- **Ownership:** client reconfiguration is reported, not performed (aihost does not change clients). Passes.
