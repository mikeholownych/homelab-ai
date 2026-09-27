# Autonomous Engineering System: Phase 8 Operational Runbook
## Multi-Repository Service Administration, Incident Response & PR Delivery

### 1. System Overview & Authority Invariants

The Phase 8 Autonomous Engineering System operates as an unattended, multi-repository engineering execution service with strict human authorization gates over pull request publication and integration.

**Core Invariants**:
- **Explicit Onboarding**: No work order can be admitted for any repository that has not been explicitly onboarded with a validated `RepositoryContract`.
- **Protected Paths**: Files in protected directories (`.github/`, `ci/`, `security/`, `validators/`) cannot be mutated by any task.
- **Untrusted Workers**: All model outputs are untrusted. Diffs are verified at point-of-use and tested by `IndependentAcceptanceManager`.
- **Human Delivery Gate**: Remote branch creation and PR publication require an explicit `DeliveryAuthorizationRecord` signed by an authorized human.
- **Autonomous Merge Prohibited**: The system creates branches and formats reviewable pull requests. It has **no authority** to merge pull requests or deploy code.

---

### 2. Administrator Procedures

#### 2.1 Onboarding a Repository
```python
from autonomous_engineering.repository.onboarding import RepositoryContract, RepositoryOnboardingManager

mgr = RepositoryOnboardingManager(db_path=Path("/var/lib/autoeng/repo_contracts.sqlite"))
contract = RepositoryContract(
    repository_id="aihost-core",
    remote_url="git@github.com:mikeholownych/aihost.git",
    baseline_commit="512543a",
    permitted_branches=("main", "release"),
    authorized_mutation_paths=("orchestrator_gateway", "orchestrator_runtime"),
    protected_paths=(".github", "ci", "validators", "security"),
    required_test_commands=("pytest tests/",),
    designated_approver="principal-engineer",
)
mgr.onboard_repository(contract)
```

#### 2.2 Offboarding a Repository
To revoke future work orders while preserving audit evidence:
```python
mgr.offboard_repository("aihost-core")
```

#### 2.3 Starting the Multi-Repository Daemon
```bash
PYTHONPATH=phase8/src:phase7/src:phase6/src:phase5/src:phase4/src:phase3/src:phase2/src:phase1/src:phase0/src \
python3 -m autonomous_engineering.service.multi_repo_service \
  --db-path /var/lib/autoeng/state.sqlite \
  --max-concurrency 4 \
  --max-queue-depth 32
```

#### 2.4 Authorizing and Publishing a Pull Request
When a work order completes independent acceptance and enters `AUTHORIZATION_PENDING`:
```python
from autonomous_engineering.delivery.pr_manager import DeliveryAuthorizationRecord, PullRequestDeliveryManager

pr_mgr = PullRequestDeliveryManager()
auth = DeliveryAuthorizationRecord(
    authorization_id="auth-2026-09-27-01",
    work_order_id="wo-1234",
    work_order_version=1,
    deliverable_hash="<exact_sha256_deliverable_hash>",
    target_repository_id="aihost-core",
    target_branch="main",
    baseline_commit="512543a",
    approver_id="principal-engineer",
)
pr_mgr.record_authorization(auth)
pr_record = pr_mgr.publish_pull_request("wo-1234", contract, local_repo_path)
print(f"Published PR: {pr_record.pr_url}")
```

---

### 3. Incident Response & Troubleshooting

#### 3.1 Unplanned Service Daemon Termination
- SQLite WAL mode ensures atomic transactional recovery.
- Upon restart, `PersistentEngineeringService` and `MultiRepoEngineeringService` scan for expired leases, increment fencing tokens, and reset dispatched assignments.
- Any delayed commit from a zombie worker is rejected with `Stale fencing token`.

#### 3.2 Network Dropped During PR Push (Delivery Retry)
- If remote push is interrupted, retry by calling `publish_pull_request()`.
- The manager checks if `delivery/wo-<id>` already exists on the remote. It checks out the existing ref, verifies the patch and commit, and reconciles cleanly without generating duplicate PRs.

#### 3.3 Prompt Injection or Scope Breach Detected
- Intercepted automatically by `validate_patch_scope()`.
- Terminal disposition recorded as `REJECTED_SCOPE_VIOLATION`.
- Zero changes are applied to target repositories or pushed to remotes.
- Inspect `logs/audit_events.jsonl` for the task attempt identity and prompt payload.

#### 3.4 Target Repository Mutated Between Validation and Export (TOCTOU)
- If an out-of-band edit occurs on the target repo, export fails with `TOCTOUMutationError`.
- Clean working directory (`git checkout -f`, `git clean -fd`) and re-trigger validation.
