# Canonical Architecture and Contracts: Phase 3
## Sustained Reliability, Human Work-Order Interface and Empirical Capability Characterization

---

## 1. Work-Order Revision Contract

### 1.1 Revision Taxonomy
A human direction or instruction change submitted against an existing active or paused work order is classified into one of five explicit categories:

```python
class RevisionKind(str, Enum):
    CLARIFICATION = "CLARIFICATION"          # Ambiguity resolution; no scope or criteria expansion
    SCOPE_EXPANSION = "SCOPE_EXPANSION"      # Adds new mutation paths; requires explicit human authorization
    SCOPE_RESTRICTION = "SCOPE_RESTRICTION"  # Narrows authorized mutation paths
    CRITERIA_MUTATION = "CRITERIA_MUTATION"  # Modifies acceptance tests or validation criteria
    CANCELLATION = "CANCELLATION"            # Terminates execution cleanly; revokes active leases
```

### 1.2 Revision Invalidation Rules
When a revision is accepted by the control plane:
1. **Version Increment**: The work order version increments monotonically (`version = previous_version + 1`).
2. **Contract Hash Binding**: The new canonical contract hash is computed, and `parent_contract_hash` points to the prior version's contract hash, creating an immutable cryptographic chain.
3. **In-Flight Assignment Invalidation**:
   - For `SCOPE_EXPANSION`, `CRITERIA_MUTATION`, and `CANCELLATION`: All in-flight assignments (`ASSIGNED`, `RUNNING`) are immediately transitioned to `REVOKED` or `SUPERSEDED`.
   - For `SCOPE_RESTRICTION`: Assignments targeting removed paths are transitioned to `REVOKED`.
4. **Fencing Token Rejection**: Any in-flight worker holding a lease for a superseded version or expired fencing token is atomically rejected upon calling `complete_assignment`:
   ```sql
   UPDATE task_assignments
   SET status = :new_status, output_artifact_hash = :output_hash, fencing_token = fencing_token + 1
   WHERE assignment_id = :assignment_id
     AND work_order_version = :expected_version
     AND fencing_token = :expected_fencing_token
     AND status IN ('ASSIGNED', 'RUNNING');
   ```
   If zero rows are updated, the worker is a stale zombie and its write is refused.

---

## 2. Human Interface & Session Detachment Contract

### 2.1 Interface Separation Boundary
The human interface (`HumanInterfaceAdapter` / `aes-cli`) is strictly decoupled from execution authority:
- **No Direct Capability Issuance**: The interface cannot issue `CapabilityToken` objects. Only the control plane `OrchestratorControlPlane` issues capability tokens upon task dispatch after admission evaluation.
- **No Direct Validator Bypass**: The interface cannot mark a work order or step `ACCEPTED`. Only the `IndependentValidator` executing clean Bubblewrap sandboxes produces validation reports, which the control plane supervisor verifies.
- **Detached Execution**: Once submitted via `submit_work_order()`, execution proceeds independently in the background. The interface may disconnect, terminate, or reconnect at any time without impacting workflow progression.

### 2.2 CLI Command Specifications
```bash
# Submitting a new work order
aes-cli submit --prompt "Fix calculate_moving_average..." --repo "/path/to/repo" \
               --commit "8b25d26" --scope "src/stats_utils.py" --test "tests/test_stats_utils.py"

# Inspecting compiled work order and ambiguities
aes-cli inspect <work_order_id> [--version <v>]

# Submitting explicit clarification or authorization
aes-cli clarify <work_order_id> --decision "Approve scope expansion to src/discounts.py"

# Querying authoritative status, active assignments, and audit trail
aes-cli status <work_order_id> [--json]

# Pausing, resuming, or cancelling execution
aes-cli pause <work_order_id>
aes-cli resume <work_order_id>
aes-cli cancel <work_order_id> --reason "User requested stop"

# Submitting a bounded revision
aes-cli revise <work_order_id> --kind SCOPE_EXPANSION --add-scope "src/new_mod.py"

# Delivering accepted deliverables and verification instructions
aes-cli deliver <work_order_id> [--export-dir ./delivery]
```

---

## 3. External Artifact Delivery & Verification Contract

### 3.1 Deliverable Bundle Schema
Accepted artifacts are packaged for consumption outside the execution engine:
```json
{
  "work_order_id": "wo-123456789abc",
  "version": 1,
  "contract_hash": "a1b2c3d4...",
  "terminal_disposition": "ACCEPTED",
  "repository": {
    "repository_id": "homelab-ai",
    "baseline_commit": "8b25d26"
  },
  "deliverable": {
    "artifact_type": "PATCH",
    "artifact_hash": "e5f6g7h8...",
    "changed_files": [
      "src/stats_utils.py"
    ],
    "patch_content": "diff --git a/src/stats_utils.py b/src/stats_utils.py\n..."
  },
  "verification": {
    "validator_type": "pytest",
    "validation_status": "PASSED",
    "test_target": "tests/test_stats_utils.py",
    "execution_duration_sec": 0.08,
    "exit_code": 0
  },
  "review": {
    "reviewer_worker_id": "worker-b65-1",
    "disposition": "RECOMMEND_ACCEPT",
    "findings_count": 0
  },
  "supervisor_audit": {
    "events_count": 6,
    "fencing_token": 2,
    "completed_at": "2026-09-27T01:25:00Z"
  },
  "local_inspection": {
    "check_command": "git apply --check deliverable.patch",
    "apply_command": "git apply deliverable.patch",
    "stat_command": "git apply --stat deliverable.patch"
  }
}
```

### 3.2 Post-Validation Tamper Invariant
If an artifact file on disk or in the CAS is mutated after validation:
1. The artifact hash re-computation fails the cryptographic match.
2. The `IndependentValidator` or supervisor invalidates prior acceptance immediately.
3. The work order transitions to `REJECTED` or `VALIDATION_FAILED` with an audit event recorded.

---

## 4. Physical Dual B65 Worker Specification

### 4.1 Deployed Hardware Profile
```yaml
worker_nodes:
  worker-b65-0:
    device_type: intel_arc_pro_b65
    pci_slot: "0000:51:00.0"
    vram_bytes: 34240299008  # 31.89 GiB
    driver_version: "xe-24.1 / Linux 7.0.0-34-generic"
    level_zero: "libze-intel-gpu1=26.22.38646.7-1~26.04~ppa1"
    host: "ai-5820-01 (10.0.8.5)"
    assigned_roles: ["investigation", "defect_patch", "implementation", "test_development", "refactoring"]
  worker-b65-1:
    device_type: intel_arc_pro_b65
    pci_slot: "0000:93:00.0"
    vram_bytes: 34240299008  # 31.89 GiB
    driver_version: "xe-24.1 / Linux 7.0.0-34-generic"
    level_zero: "libze-intel-gpu1=26.22.38646.7-1~26.04~ppa1"
    host: "ai-5820-01 (10.0.8.5)"
    assigned_roles: ["independent_review", "defect_patch", "refactoring"]
```

### 4.2 Independence Invariant
For any work order where both authoring and review tasks are scheduled:
$$\text{worker}(\text{task}_{\text{review}}) \neq \text{worker}(\text{task}_{\text{author}})$$
The capability router strictly rejects any routing hypothesis where the author worker is assigned to review its own patch.
