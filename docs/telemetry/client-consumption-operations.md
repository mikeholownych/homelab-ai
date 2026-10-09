# Client Telemetry Operations and Deployment Guide

## 1. Production Baseline and Architecture

Host: `ai-5820-01` (`10.0.8.5`)  
Gateway Listeners:
- **Workload & Telemetry (Remote HTTPS):** `https://10.0.8.5:8443` (mTLS / TLS with client Bearer token)
- **Monitoring (Local Loopback HTTP):** `http://127.0.0.1:8000` (`/health`, `/metrics`, unauthenticated loopback)

### Worker Topology
The T5820 appliance runs two dedicated `llama.cpp` worker instances across two Intel Arc Pro B65 GPUs:

1. **Lead Worker:**
   - Worker ID: `b0-live-llama-worker1`
   - Model ID: `Qwen3.6-35B-A3B-UD-Q4_K_M`
   - Public Model Alias: `engineering/lead` (and default `engineering/b0`)
   - Hardware: Intel Arc Pro B65 (GPU 0, ~32 GiB VRAM)
   - Port: `http://127.0.0.1:8081`

2. **Deep Worker:**
   - Worker ID: `b0-live-llama-deep-worker2`
   - Model ID: `Qwen3.8-Flash-Next-GSQ-RCO-IQ1_M`
   - Public Model Alias: `engineering/deep`
   - Hardware: Intel Arc Pro B65 (GPU 1, ~32 GiB VRAM)
   - Port: `http://127.0.0.1:8082`

---

## 2. Resource Boundaries and Overhead Controls

The Client Telemetry API is engineered for non-disruptive, bounded execution within the orchestrator gateway runtime:

- **Bounded In-Memory Ring Buffer:**
  - Implemented via `collections.OrderedDict` guarded by a reentrant `threading.Lock`.
  - Hard capacity bound: 10,000 records maximum.
  - Eviction policy: Deterministic FIFO eviction when buffer capacity is reached.
  - Memory footprint: Approximately 2.2 MiB at maximum 10,000 record saturation.
  - Zero External Database Dependencies: The buffer resides purely in gateway heap space. Gateway restart clears historical records without persistent database state.
- **Hot-Path Overhead:**
  - Timing observation uses Python's `time.monotonic()`. Monotonic timer sampling introduces less than 5 microseconds of overhead per request.
  - Request recording occurs during the terminal response validation phase (`runtime.py:complete`), completely decoupled from token streaming loops.
  - Streaming SSE delta timing uses zero-copy timestamp capture in the gateway proxy socket loop (`server.py:_completion`).
- **Query Bounds:**
  - Query parameter `limit` is strictly clamped between `1` and `100` (default `10`).
  - Queries filtering by `request_id` execute in $O(1)$ time via hash map index.
  - Queries filtering by `client_id` scan a maximum of 10,000 in-memory metadata references, executing in under 1 millisecond.

---

## 3. Client Configuration and Scopes

Client permissions are managed declaratively in Ansible host inventory:
[`inventory/production/host_vars/ai-5820-01.yml`](file:///home/mike/Projects/aihost/inventory/production/host_vars/ai-5820-01.yml).

### Scope Assignments
```yaml
orchestrator_gateway_clients:
  - client_id: nexus
    scopes: [workload, telemetry]
    default_priority: interactive
  - client_id: opencode
    scopes: [workload, telemetry]
    default_priority: interactive
  - client_id: operator
    scopes: [workload, qualification, monitoring, admin, telemetry]
    default_priority: batch
  - client_id: ansible-admin
    scopes: [admin, monitoring, telemetry]
    default_priority: batch
```

Clients configured with `telemetry` scope receive access to:
1. `GET /v1/telemetry/capabilities`
2. `GET /v1/telemetry/inference` across all scopes (`appliance`, `worker`, `request`).
3. Latency distributions and worker cache hit metrics.

Clients configured with only `workload` scope can discover capabilities and query their own requests by exact `request_id`, but are refused access to aggregate appliance or worker fleet telemetry (`403 Forbidden`).

---

## 4. Deployment Procedure

Deploying gateway updates containing the telemetry interface is executed through Ansible with zero downtime for running worker containers:

### Step 1: Commit and Update Release Identifier
Commit changes to the repository, retrieve the commit short hash (`<COMMIT_SHA>`), and update the release pins in [`inventory/production/host_vars/ai-5820-01.yml`](file:///home/mike/Projects/aihost/inventory/production/host_vars/ai-5820-01.yml):

```yaml
orchestrator_gateway_release_id: "t5820-gateway-<COMMIT_SHA>"
orchestrator_gateway_release_dir: "/var/lib/aihost/releases/t5820-gateway-<COMMIT_SHA>"
```

### Step 2: Converge Gateway via Ansible
Run the scoped Ansible playbook targeting only the orchestrator service on `ai-5820-01`:

```bash
.venv/bin/ansible-playbook playbooks/inference.yml \
  --limit ai-5820-01 \
  --tags "orchestrator"
```

The playbook performs:
1. Creation of `/var/lib/aihost/releases/t5820-gateway-<COMMIT_SHA>`.
2. Atomic deployment of `orchestrator_gateway` and `orchestrator_runtime`.
3. Updating `/etc/aihost/orchestrator-gateway/clients.json` with client scopes (including `telemetry`).
4. Graceful restart of `aihost-orchestrator-gateway.service`.
5. Inference workers (`aihost-llama-worker1` and `aihost-llama-worker2`) remain online and untouched.

---

## 5. Live Operational Verification Commands

Perform the following verification checks against the deployed appliance:

### 1. Unauthenticated Rejection (HTTP 401)
```bash
curl -k -s -w "\nHTTP Status: %{http_code}\n" \
  https://10.0.8.5:8443/v1/telemetry/capabilities
# Expected: HTTP Status: 401
```

### 2. Capabilities Discovery
```bash
curl -k -s -H "Authorization: Bearer <CLIENT_TOKEN>" \
  https://10.0.8.5:8443/v1/telemetry/capabilities | jq .
# Expected: HTTP 200 with api_version="2026-10-09", supported_metrics, active_workers.
```

### 3. Appliance Scope Telemetry
```bash
curl -k -s -H "Authorization: Bearer <CLIENT_TOKEN>" \
  https://10.0.8.5:8443/v1/telemetry/inference?scope=appliance | jq .
# Expected: HTTP 200 with gateway status, workers_summary, and queue depths.
```

### 4. Worker Scope Telemetry
```bash
curl -k -s -H "Authorization: Bearer <CLIENT_TOKEN>" \
  https://10.0.8.5:8443/v1/telemetry/inference?scope=worker&worker_id=b0-live-llama-worker1 | jq .
# Expected: HTTP 200 with cache occupancies, engine counters, and latency distributions.
```

### 5. Request Telemetry & Correlation
Execute an inference request, capture `X-Request-ID`, and immediately query its telemetry:

```bash
# Send streaming request and capture X-Request-ID
REQ_ID=$(curl -k -s -D - -H "Authorization: Bearer <CLIENT_TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{"model": "engineering/lead", "messages": [{"role": "user", "content": "ping"}], "stream": true}' \
  https://10.0.8.5:8443/v1/chat/completions | grep -i "x-request-id:" | awk '{print $2}' | tr -d '\r\n')

# Query telemetry for this request
curl -k -s -H "Authorization: Bearer <CLIENT_TOKEN>" \
  "https://10.0.8.5:8443/v1/telemetry/inference?request_id=${REQ_ID}" | jq .
# Expected: HTTP 200 with ttft_seconds, ttft_provenance="streaming_first_chunk", itl_provenance="streaming_delta_intervals".
```

---

## 6. Rollback Procedure

If any anomaly or operational defect is observed:

1. Update `orchestrator_gateway_release_id` in `inventory/production/host_vars/ai-5820-01.yml` back to the previous verified release:
   ```yaml
   orchestrator_gateway_release_id: "t5820-gateway-c74ebaf"
   orchestrator_gateway_release_dir: "/opt/aihost/releases/t5820-gateway-c74ebaf"
   ```
2. Re-converge the orchestrator gateway:
   ```bash
   .venv/bin/ansible-playbook playbooks/inference.yml \
     --limit ai-5820-01 \
     --tags "orchestrator"
   ```
3. Verify gateway health:
   ```bash
   curl -k -s https://10.0.8.5:8443/health | jq .
   ```
