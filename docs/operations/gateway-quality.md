# Gateway hardening and acceptance ledger

## Source and deployment boundary

This change is based on deployed snapshot e463fafa2552bdf51bf5ee2594c1d1ecf663c509,
so candidate recovery and ASGI worker drain routes are retained. The controller source
checkout is /home/mike/Projects/aihost; the isolated implementation branch is
feat/gateway-quality. Production is unchanged until an explicit snapshot promotion.

The gateway supports the documented chat, tokenization, model/route, outcome and management
APIs. It does not claim implementation of every OpenAI API or every optional field.

## Implemented controls

| Review item | Implementation | Acceptance evidence / remaining gate |
| --- | --- | --- |
| GQ-01 ownership | Root-owned source and per-release environment; read-only unit paths; MemoryMax 1G and TasksMax 256 | Role syntax/lint; service-confined ownership checks still required on a staged appliance |
| GQ-02 ingress | Actual-byte limit, total upload deadline, JSON object/chat shape checks, explicit HTTP concurrency | Oversize, chunk, malformed and stalled-upload tests |
| GQ-03 execution | Dedicated bounded executors shared by listeners; per-client execution limits; async stream queues; offloaded tokenizer | Concurrent streams with one default executor thread; health stays responsive during a stalled tokenizer |
| GQ-04 cancellation | Disconnect monitor from dispatch through response; cancellation event reaches provider; actual thread owns capacity release | Real local socket disconnects before headers, streaming and non-streaming; executor cancellation slot ownership |
| GQ-05 contract | Preserved drain/undrain, added ASGI outcomes and summary, shared runtime scopes/ownership | ASGI drain authority and existing protocol/runtime regression tests |
| GQ-06 deployment | Stage distinct content identity; manifest verification; immutable identity refusal; activation identity/readiness gate; previous unit/env rollback | Real Ansible tasks tested with temporary files, fake health server and substituted systemd commands for readiness, identity and restart failures |
| GQ-07 dependencies | Complete hash-pinned wheel closure in gateway-requirements.lock; per-release venv; only-binary hash-checked pip | Offline clean install and imports from the exact lock; appliance platform acceptance pending |
| GQ-08 retention | Bounded evidence/span rings; streaming verification; sealed 64-MiB evidence segments; atomic replacement; export-drop counters | Soak of ring bounds, predecessor tamper detection and injected interruption before segment switch |
| GQ-09 quotas/SLOs | Requests charged before cache; per-client dispatch cap; bounded-cardinality HTTP metrics include streams/errors | Cache quota and competing-client capacity tests; representative workload SLO qualification pending |

## Policy defaults

- HTTP body: 1,000,000 bytes and 15 seconds total upload time.
- HTTP connections/tasks: 128; completion dispatches: 32 globally, 8 per client;
  tokenization dispatches: 4. These are distinct from the per-pool GPU queue and worker slots.
- Workload/operator clients: 60 requests/minute each; qualification client: 6/minute.
  Cache hits count as requests but do not charge newly generated tokens. Existing optional
  per-model/per-pool/token-day policies remain available. No arbitrary daily token allowance is imposed.
- Evidence diagnostic ring: 1024 records; trace diagnostic ring: 1024 spans.
  Evidence segments seal at 64 MiB; old segments are retained and verified through predecessor hashes.
  Segment size and ring sizes are configurable via ORCHESTRATOR_EVIDENCE_SEGMENT_BYTES,
  ORCHESTRATOR_EVIDENCE_RING_SIZE and ORCHESTRATOR_TRACE_RING_SIZE.
- Pure Python Uvicorn backend is intentionally locked without platform-specific optional standard extras.
  Repeat performance qualification before considering an alternate backend.

## Deployment and rollback behavior

Each runtime change needs a new commit-derived release identity. The role refuses an existing
unsealed release and refuses different code under an already sealed identity. Source and dependency
lock are verified before activation. Unit/environment files use Ansible atomic file replacement;
activation is a multi-step operation, not a single filesystem transaction across controller loss.

Pending gateway handlers run before readiness is accepted. Health must name the exact expected
release and pass strict readiness. On activation failure, prior unit/environment are restored,
the old service is restarted and checked; failed first installation is stopped and disabled.
Credential rotation is not reversed by this rollback. An unreachable host or lost controller
cannot execute Ansible rescue, and therefore requires independent operational recovery.

Automatic historical-release pruning is removed from convergence. Retain the active and last
known-good releases and their environments until qualification/rollback checks pass. Disk-space
alerts and owner-controlled archival/pruning remain required; sealed evidence is never silently
deleted, because predecessor integrity depends on it.

## Remaining qualification (do not label this release frontier-qualified yet)

1. On a non-production appliance or equivalent VM, verify actual unit confinement, root ownership,
   credential access and real systemd failure recovery, including unreachable/controller-loss cases.
2. Exercise the exact locked environment and release under sustained mixed-client streaming,
   cancellation, queue saturation, slow consumers, collector outage and worker loss. Confirm memory
   plateaus and select a safe MemoryMax with measured headroom before production promotion.
3. Measure p50/p95/p99 TTFT, inter-token latency, queue latency, health responsiveness, cancellation
   release latency and accepted/completed goodput. Proposed initial bounds: health p99 <250 ms under
   overload and disconnect-to-slot-release <2 seconds; local unit tests are not those qualifications.
4. Decide degraded-start policy explicitly. Existing all-required-workers startup policy is preserved.
5. Evaluate representative engineering/tool/structured-output workloads through the exact gateway.
   Healthy HTTP transport is not proof of frontier model quality.
6. The single T5820 remains a single-host failure domain. Independent standby/failover qualification
   is a separate project; neither multi-worker routing nor this change supplies host-level HA.

Run the targeted gateway/runtime/activation tests with PYTHONPATH=. in the checkout. The existing
release-identity contract must pass after the inventory points at the code commit. Run all configured
playbook syntax checks and role lint. Production promotion must use the reviewed final snapshot,
retain the recovery preflight, and record post-deployment identity, worker health and rollback evidence.
