# Phase 7 Qualification Report: Evidence Integrity, Deliverable Custody & TOCTOU Prevention (Workstream G)

## 1. Executive Summary

Workstream G evaluates the tamper-evident properties of the Autonomous Engineering System, focusing on Content-Addressed Storage (CAS) artifact custody, verifiable deliverable bundles, and Time-of-Check to Time-of-Use (TOCTOU) target repository race condition prevention.

Key Outcomes:
1. **Immutable CAS Lineage**: Every intermediate artifact (investigation logs, execution plans, initial patches, review findings, repaired patches, and validation verdicts) is keyed by SHA-256 content hashes, establishing an unforgeable provenance DAG.
2. **Deliverable Bundles with Human Integration Guides**: Accepted deliverables export self-contained bundles including `deliverable.patch`, `manifest.sha256`, and an authoritative `INTEGRATION_GUIDE.md`.
3. **TOCTOU Target Mutation Rejection**: Out-of-band modifications to the target repository between validation and export are detected and blocked via cryptographic tree hashing.

---

## 2. TOCTOU Target Repository Protection

### Vulnerability Mechanics:
If a validation step confirms that a patch passes all test criteria on repository state $S_0$, but an external actor or concurrent process mutates the target repository to state $S_1$ before deliverable export, applying the deliverable patch could introduce unvalidated or broken behaviors.

### Hardened Implementation:
1. **Pre-Validation Tree Snapshot**: During `execute_lifecycle`, immediately prior to invoking the independent validator, `HardenedRealRepoPipeline` computes a recursive SHA-256 tree hash of all files in the target repository (`validation_repo_snapshots[work_order_id] = compute_directory_tree_hash(target_repo_dir)`).
2. **Pre-Export Verification**: In `export_deliverable()`, the pipeline re-computes the target repository tree hash.
3. **Fail-Closed Abort**: If `current_repo_hash != expected_repo_hash`, the pipeline raises `TOCTOUMutationError` and immediately aborts export.

### Test Verification:
In `test_deliverable_custody_and_toctou.py::test_toctou_mutation_rejection` and `phase7/run_demo.py` section 7:
- Repository mutated between validation and export.
- Observed:
  ```text
  TOCTOUMutationError: Target repository was mutated after validation!
  Expected hash af8d8c06e979d095, observed f559e89d7f952990. Deliverable export aborted.
  ```
- No deliverable bundle was produced; integrity preserved.

---

## 3. Deliverable Bundle Structure & Human Integration Guide

When an accepted work order is exported, `export_deliverable()` generates an immutable bundle directory:
```text
exports/<work_order_id>/
├── deliverable.patch           # Unified diff formatted for git apply
├── manifest.sha256             # SHA-256 checksums of all bundle contents
├── integration_metadata.json   # Machine-readable provenance and routing metadata
└── INTEGRATION_GUIDE.md        # Authoritative human verification instructions
```

### Manifest Verification:
Every exported file is verified against `manifest.sha256` (`sha256sum -c manifest.sha256`). Any manual modification to `deliverable.patch` or metadata files immediately invalidates the checksum check.

Verified in `test_deliverable_custody_and_toctou.py::test_deliverable_bundle_integrity_and_guide`.
