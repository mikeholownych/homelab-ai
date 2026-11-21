# MS-S1 Max Production Promotion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Promote `ai-ms-s1-max-01` to a full production peer of `ai-5820-01` with a hardened HIP worker, local TLS gateway, parallel ROCm capacity alias on both gateways, monitoring, and reconcile — without touching Intel lead/deep aliases.

**Architecture:** Staged cutover 3a→3f. Single inventory source of truth in `inventory/production`. New gateway pool `rocm` + alias `engineering/interactive-rocm`. Worker LAN-bound with API key; ufw via `security_inference_api_*`. 5820 gateway gains a remote worker endpoint at `http://10.0.8.6:8101`.

**Tech Stack:** Ansible, llama_cpp_hip, orchestrator_gateway, security/ufw, Vault client tokens (existing patterns), pytest contracts, qualify/curl probes.

**Spec:** `docs/superpowers/specs/2026-11-21-ms-s1-max-production-promotion-design.md`

**Plan-locked names:**
| Item | Value |
| --- | --- |
| Pool | `rocm` |
| Alias | `engineering/interactive-rocm` |
| Route id | `interactive-rocm` |
| Worker id (local + remote) | `ms-s1-hip-coder30b` |
| Worker port | `8101` |
| Worker bind | `10.0.8.6` |
| ufw allow from | `10.0.8.5/32` (+ localhost implicit) |

---

## File Map

| Path | Responsibility |
| --- | --- |
| `docs/superpowers/specs/2026-11-21-ms-s1-max-production-promotion-design.md` | Approved design |
| `inventory/production/hosts.yml` | Add host to production groups |
| `inventory/production/host_vars/ai-ms-s1-max-01.yml` | Production peer contract |
| `inventory/lab/hosts.yml` | Remove live host |
| `inventory/lab/host_vars/ai-ms-s1-max-01.yml` | Delete (moved to production) |
| `roles/llama_cpp_hip/` | LAN bind + API key (relax loopback-only assert when keyed) |
| `inventory/production/host_vars/ai-5820-01.yml` | Remote worker + parallel alias/route |
| `tests/test_ms_s1_max_promotion_contract.py` | Inventory + alias exclusivity contracts |
| `docs/commissioning.md` | Phase 3 runbook |
| `evidence/ai-ms-s1-max-01/<ts>/promotion/` | Dual-front-door qualify |

---

### Task 1: Commit design + promotion contract scaffold

**Files:**
- Commit: design spec (if untracked)
- Create: `tests/test_ms_s1_max_promotion_contract.py`

- [ ] **Step 1: Failing test — host not yet in production**

```python
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]


def load(path: str):
    return yaml.safe_load((ROOT / path).read_text())


def test_production_hosts_registers_ms_s1_max():
    hosts = load("inventory/production/hosts.yml")
    for group in ("production", "inference", "gpu", "monitoring", "cluster"):
        assert "ai-ms-s1-max-01" in hosts["all"]["children"][group]["hosts"]


def test_lab_no_longer_lists_live_ms_s1_max():
    hosts = load("inventory/lab/hosts.yml")
    lab = hosts["all"]["children"]["lab"]["hosts"]
    assert "ai-ms-s1-max-01" not in lab


def test_production_host_vars_promotion_contract():
    hv = load("inventory/production/host_vars/ai-ms-s1-max-01.yml")
    assert hv["node_metadata"]["environment"] == "production"
    assert hv["llama_cpp_hip_enabled"] is True
    assert hv["orchestrator_gateway_enabled"] is True
    assert hv["llama_cpp_hip_host"] == "10.0.8.6"
    assert hv.get("intel_gpu_install_enabled") is False
```

- [ ] **Step 2: Run — expect RED**

Run: `.venv/bin/pytest tests/test_ms_s1_max_promotion_contract.py -q`

- [ ] **Step 3: Commit design only (scaffold test may stay red until Task 2)**

Prefer: commit design + empty/xfail-free test file that will go green in Task 2; or commit design now and add tests in Task 2 with TDD. **Do both in Task 2 if cleaner** — minimum for Task 1:

```bash
git add docs/superpowers/specs/2026-11-21-ms-s1-max-production-promotion-design.md \
  docs/superpowers/plans/2026-11-21-ms-s1-max-production-promotion.md
git commit -m "$(cat <<'EOF'
docs: MS-S1 Max Phase 3 production promotion design and plan

EOF
)"
```

---

### Task 2: Stage 3a — Inventory cutover

**Files:**
- Modify: `inventory/production/hosts.yml`
- Create: `inventory/production/host_vars/ai-ms-s1-max-01.yml`
- Modify: `inventory/lab/hosts.yml` (remove host)
- Delete: `inventory/lab/host_vars/ai-ms-s1-max-01.yml`
- Modify: `tests/test_ms_s1_max_inventory_contract.py` / wire contracts that assumed lab path
- Create/extend: `tests/test_ms_s1_max_promotion_contract.py`

- [ ] **Step 1: Write/extend failing promotion + update lab-era tests**

Any test that required `inventory/lab/host_vars/ai-ms-s1-max-01.yml` must target production path instead (or assert lab absence).

- [ ] **Step 2: Add production hosts.yml entries**

Under each of `production`, `inference`, `gpu`, `monitoring`, `cluster`:

```yaml
        ai-ms-s1-max-01: {}
```

- [ ] **Step 3: Create production host_vars**

Start from former lab file; set at minimum:

```yaml
node_metadata:
  environment: production
  hostname: ai-ms-s1-max-01
  hardware_profile: ms_s1_max_strix_halo
  os_tuning_profile: baseline

node_roles:
  inference: true
  gpu: true

capabilities:
  gpu: true
  inference: true
  benchmarking: true
  monitoring: true
  cluster_eligible: true

features:
  monitoring: true
  scheduled_reconciliation: true
  os_tuning: true
  observability: true
  # keep model_registry/clustering/cmdb/itsm/ray/distributed_vllm false unless 5820 peer requires otherwise

rocm_install_enabled: true
intel_gpu_install_enabled: false
intel_gpu_physical_validation_enabled: false

users_runtime_rootless_enabled: true
users_runtime_subuid_first: 165536
users_local_ai_manage_device_groups: true
users_local_ai_device_groups: [render, video]

llama_cpp_hip_enabled: true
llama_cpp_hip_digest: "sha256:9c44da4d33fa3e1250ec910d3af7b7acd1154baef3fe0efda53d91ae4a9f4184"
llama_cpp_hip_host: "10.0.8.6"
llama_cpp_hip_api_key_required: true
# worker map: keep qwen3_coder_30b_q8 pins; add api_key path in Task 3

orchestrator_gateway_enabled: true
# detailed gateway block filled in Task 4

security_firewall_enabled: true
security_inference_api_firewall_enabled: true
security_inference_api_cidrs: ["10.0.8.5/32"]
security_inference_api_ports: [8101]

storage_lvm:  # unchanged from lab
  enabled: true
  vg: ubuntu-vg
  lv: local-ai-lv
  size: 1024g
  fstype: xfs
  mount_path: /var/lib/local-ai
  reserve_gib: 100
  expected_pvs: ["/dev/nvme0n1p3"]
```

- [ ] **Step 4: Remove lab live host**

Delete lab host_vars; remove from `inventory/lab/hosts.yml` `lab` and `gpu` maps.

- [ ] **Step 5: Tests green + commit**

```bash
.venv/bin/pytest tests/test_ms_s1_max_promotion_contract.py tests/test_ms_s1_max_inventory_contract.py tests/test_ms_s1_max_engine_wire_contract.py -q
git add inventory/ tests/ docs/
git commit -m "$(cat <<'EOF'
feat(inventory): promote ai-ms-s1-max-01 into production

EOF
)"
```

---

### Task 3: Stage 3b — Harden HIP worker (API key + LAN + ufw)

**Files:**
- Modify: `roles/llama_cpp_hip/defaults/main.yml`
- Modify: `roles/llama_cpp_hip/tasks/main.yml` (relax loopback-only when API key required)
- Modify: `roles/llama_cpp_hip/templates/llama-hip.service.j2` (`--api-key-file`)
- Modify: `roles/llama_cpp_hip/tasks/start_worker.yml` (auth health check)
- Modify: `inventory/production/host_vars/ai-ms-s1-max-01.yml`
- Create: `tests/test_llama_cpp_hip_contract.py` (or extend existing)

- [ ] **Step 1: Failing contract**

```python
def test_hip_role_allows_lan_bind_when_api_key_required():
    defaults = yaml.safe_load(Path("roles/llama_cpp_hip/defaults/main.yml").read_text())
    assert "llama_cpp_hip_api_key_required" in defaults
    # Template must reference api-key-file when required — grep unit template
    text = Path("roles/llama_cpp_hip/templates/llama-hip.service.j2").read_text()
    assert "api-key" in text
```

- [ ] **Step 2: Implementation rules**

- If `llama_cpp_hip_api_key_required` is true: require `llama_cpp_hip_host != '127.0.0.1'` OR explicitly allow `0.0.0.0`; **forbid** unauthenticated non-loopback.
- If API key required is false: keep current lab assert (`host == 127.0.0.1`).
- Mount/write per-worker key file like SYCL (`/etc/local-ai/llama-hip/<worker>/worker-api-key`); unit passes `--api-key-file`.
- Health check sends `Authorization: Bearer …`.
- Ensure `security_*` firewall vars are applied via existing `security` role on site converge.

- [ ] **Step 3: Deploy harden on host**

```bash
ansible-playbook -i inventory/production playbooks/site.yml --limit ai-ms-s1-max-01 --tags llama_cpp_hip,security
# from 5820 or controller:
curl -fsS -H "Authorization: Bearer $(ssh mike@10.0.8.6 sudo cat /etc/local-ai/llama-hip/.../worker-api-key)" \
  http://10.0.8.6:8101/v1/models
# unauthenticated from elsewhere must fail
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(llama-hip): LAN bind with API key for production promotion

EOF
)"
```

---

### Task 4: Stage 3c — Local gateway on MS-S1

**Files:**
- Modify: `inventory/production/host_vars/ai-ms-s1-max-01.yml` (full gateway block)
- Possibly reuse PKI paths under `~/.local/share/aihost/pki/ai-ms-s1-max-01/`
- Tests: promotion contract asserts alias/route present and Intel aliases absent on this host

- [ ] **Step 1: Gateway host_vars (minimal peer)**

Mirror 5820 structure but ROCm-only:

```yaml
orchestrator_gateway_enabled: true
orchestrator_gateway_port: 8010
orchestrator_gateway_host: 127.0.0.1
orchestrator_gateway_local_listener_mode: local
orchestrator_gateway_engine: asgi
orchestrator_gateway_remote_host: 10.0.8.6
orchestrator_gateway_remote_port: 8443
orchestrator_gateway_tls_sans: [IP:10.0.8.6, DNS:ai-ms-s1-max-01]
# release_id: bump when packaging gateway bits for this host — follow existing release bump practice
orchestrator_gateway_routes:
  - id: interactive-rocm
    match: {model: [engineering/interactive-rocm]}
    pool: rocm
    fallback: []
    reasoning: {mode: "off", answer_allowance: 8192}
  - id: default
    match: {}
    pool: rocm
    fallback: []
    reasoning: {mode: "off", answer_allowance: 8192}
orchestrator_gateway_model_aliases:
  engineering/interactive-rocm: {pool: rocm, reasoning: {mode: "off", answer_allowance: 8192}}
orchestrator_gateway_workers:
  - worker_id: ms-s1-hip-coder30b
    pool: rocm
    engine: llama.cpp
    port: 8101
    endpoint: http://10.0.8.6:8101
    credential_source: /etc/local-ai/llama-hip/qwen3_coder_30b_q8/worker-api-key
    model_id: qwen3-coder-30b-a3b-instruct-q8_0
    topology: llama-cpp-hip
    hardware_class: amd-strix-halo-gfx1151
    # fill digest/revision from bake-off pins
```

Do **not** add `engineering/lead` or `engineering/deep` on this host.

- [ ] **Step 2: Converge gateway + vault clients as required**

```bash
ansible-playbook -i inventory/production playbooks/site.yml --limit ai-ms-s1-max-01 --tags orchestrator,vault
```

- [ ] **Step 3: Local qualify**

Probe `engineering/interactive-rocm` through MS-S1 TLS gateway (port 8443 pattern). Archive evidence.

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(gateway): enable ROCm parallel alias gateway on ai-ms-s1-max-01

EOF
)"
```

---

### Task 5: Stage 3d — Advertise on 5820 gateway

**Files:**
- Modify: `inventory/production/host_vars/ai-5820-01.yml`
- Extend promotion contract: 5820 has `engineering/interactive-rocm` → worker `ms-s1-hip-coder30b` with endpoint `http://10.0.8.6:8101`; lead/deep workers unchanged

- [ ] **Step 1: Failing test for 5820 alias exclusivity**

```python
def test_5820_rocm_alias_is_parallel_not_lead():
    hv = load("inventory/production/host_vars/ai-5820-01.yml")
    assert "engineering/interactive-rocm" in hv["orchestrator_gateway_model_aliases"]
    assert hv["orchestrator_gateway_model_aliases"]["engineering/lead"]["pool"] == "lead"
    workers = {w["worker_id"]: w for w in hv["orchestrator_gateway_workers"]}
    assert workers["ms-s1-hip-coder30b"]["pool"] == "rocm"
    assert workers["ms-s1-hip-coder30b"]["endpoint"] == "http://10.0.8.6:8101"
    assert workers["b0-live-llama-worker1"]["pool"] == "lead"
```

- [ ] **Step 2: Add route + alias + remote worker on 5820**

Append route `interactive-rocm` (match model `engineering/interactive-rocm`, pool `rocm`).  
Append alias.  
Append worker with credential — prefer reading key from MS-S1 via Vault-synced secret or documented copy into 5820 credential file path under `/etc/local-ai/orchestrator/remote-ms-s1-hip-api-key` (plan: use Vault platform credentials if a record exists; else file deployed by ansible from Vault lookup — follow existing remote/candidate patterns).

Bump `orchestrator_gateway_release_id` per repo convention when gateway config package changes.

- [ ] **Step 3: Pre-check Intel lead, converge 5820 gateway, post-check**

```bash
# pre: curl lead alias → SYCL worker
ansible-playbook -i inventory/production playbooks/site.yml --limit ai-5820-01 --tags orchestrator
# post: lead still SYCL; interactive-rocm → MS-S1
```

- [ ] **Step 4: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(gateway): advertise MS-S1 HIP worker as parallel ROCm alias on 5820

EOF
)"
```

---

### Task 6: Stage 3e — Monitoring + reconcile

**Files:**
- Modify: `inventory/production/host_vars/ai-ms-s1-max-01.yml` (features already true in 3a; wire observability role vars to match 5820 peer subset)
- Modify reconcile controller host maps / defaults if hosts are enumerated explicitly
- Grafana dashboards only if a static host list needs updating (prefer label discovery)

- [ ] **Step 1: Identify reconcile targeting**

Grep `reconcile` / `ai-5820-01` in reconcile_controller defaults and inventory; add `ai-ms-s1-max-01` wherever 5820 is explicitly listed for production reconcile.

- [ ] **Step 2: Converge monitoring tags on MS-S1**

```bash
ansible-playbook -i inventory/production playbooks/site.yml --limit ai-ms-s1-max-01 --tags observability,monitoring
```

Verify node metrics appear (or scrape config present). Document idle fallbacks.

- [ ] **Step 3: Commit**

```bash
git commit -m "$(cat <<'EOF'
feat(obs): enable monitoring and reconcile for ai-ms-s1-max-01

EOF
)"
```

---

### Task 7: Stage 3f — Dual-front-door qualify + docs

**Files:**
- Create: `evidence/ai-ms-s1-max-01/<UTC>/promotion/`
- Modify: `docs/commissioning.md` (Phase 3 section)

- [ ] **Step 1: Qualify MS-S1 local gateway** — models + chat + tool probe on `engineering/interactive-rocm`

- [ ] **Step 2: Qualify 5820 → remote** — same alias through 5820 TLS gateway

- [ ] **Step 3: Intel regression** — `engineering/lead` still SYCL-only (worker id / topology check)

- [ ] **Step 4: Docs** — Phase 3 runbook: inventory, harden, dual gateway, qualify commands

- [ ] **Step 5: Commit evidence + docs**

```bash
git commit -m "$(cat <<'EOF'
evidence: MS-S1 Max dual-front-door production promotion qualify

EOF
)"
```

---

### Task 8: PR to main

```bash
git push -u origin HEAD
gh pr create --title "feat: MS-S1 Max production promotion (Phase 3)" --body "$(cat <<'EOF'
## Summary
- Promote ai-ms-s1-max-01 into production inventory as a full peer
- Harden HIP worker (LAN + API key + ufw); local ROCm gateway
- Parallel alias engineering/interactive-rocm on MS-S1 and 5820 (Intel lead untouched)

## Test plan
- [ ] Promotion + inventory contracts
- [ ] Authenticated /v1/models from 5820 to 10.0.8.6:8101
- [ ] Dual-front-door qualify evidence
- [ ] Intel lead regression on 5820

EOF
)"
```

Merge after CI green (operator).

---

## Spec coverage checklist

| Spec requirement | Task |
| --- | --- |
| Production groups + remove lab live | Task 2 |
| Worker API key + LAN + ufw | Task 3 |
| Local gateway ROCm-only | Task 4 |
| 5820 remote worker + parallel alias | Task 5 |
| Intel aliases unchanged | Tasks 5, 7 |
| Monitoring + reconcile | Task 6 |
| Dual-front-door qualify + docs | Task 7 |
| Staged fail-closed | Tasks 2–7 order |

## Self-review notes

- Alias/pool/worker ids locked (no TBD).
- `llama_cpp_hip` loopback assert must become conditional — called out in Task 3.
- Uses existing `security_inference_api_*` rather than a one-off ufw script.
- Gateway release bump on 5820 called out explicitly.
- Lab host_vars deleted; tests retargeted to production.
