# Hardened Canonical Work-Order and Artifact Contracts

**Document ID**: SPEC-HARDENED-CONTRACTS-PHASE1-2026-09-26  
**Status**: APPROVED  
**Author**: Antigravity Autonomous Engineering Agent  
**Context**: Phase 1 Contract Hardening, Section 5  

---

## 1. Cryptographic Digest Properties and Guarantees

In Phase 1, all SHA-256 digests serve explicit, bounded cryptographic purposes. The table below formalizes what each digest establishes and what it explicitly does not:

| Digest Field | Input Data Covered | What It Establishes | What It Does NOT Establish |
| :--- | :--- | :--- | :--- |
| **`source_instruction.content_hash`** | Raw text of user instruction as received at the interface. | Tamper-evident record of exact human words and instructions. | Does not guarantee instruction is unambiguous, safe, or admitted. |
| **`WorkOrder.contract_hash`** | Canonical JSON of intent, target repository ID & baseline commit, ambiguities, authorized paths, prohibited operations, acceptance criteria, budget, and predecessor hash. | Immutable binding of the complete authorized engineering task contract. | Does not guarantee that a worker has executed the task or that tests pass. |
| **`CapabilityToken.signature_hash`** | Token ID, work-order ID & version, baseline commit, contract hash, authorized paths, authorized tools, fencing token, timestamps. | Verifiable grant of bounded authority issued by control plane. | Does not grant permission to write outside authorized paths or execute tools outside whitelist. |
| **`ArtifactRecord.artifact_hash`** | Exact bytes of produced artifact (patch, log, script, report). | Content-addressable immutability and byte integrity. | Does not certify that the artifact is correct, accepted, or passes tests. |
| **`ValidationVerdict.verdict_hash`** | Verdict ID, artifact hash, status (`ACCEPTED`/`REJECTED`), check results, and diagnostic logs. | Authoritative independent acceptance or rejection verdict. | Does not permit model worker or router to override the result. |

---

## 2. Hardened Invalidation and Evolution Rules

1. **Version Supersession**: Modifying any field in an admitted work order requires creating Version $N+1$ with `predecessor_hash = contract_hash_N`.
2. **Capability Revocation on Revision**: The moment Version $N+1$ is registered, all active capability tokens for Version $N$ are revoked, and all in-flight task assignments on Version $N$ are marked `SUPERSEDED`.
3. **No Cross-Lineage Artifact Application**: A review or repair artifact referencing an obsolete work-order version or a parent artifact hash not in the current lineage is strictly rejected by the control plane.
4. **Independent Validation Binding**: The independent validator evaluates the exact bytes of the final patch artifact. Any subsequent file mutation immediately invalidates prior validation verdicts.

---
