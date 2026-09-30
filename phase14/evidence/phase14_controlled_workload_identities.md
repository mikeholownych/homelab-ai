# Phase 14 Experiment 01: Controlled Workload Identities

## 1. Experimental Workload Design

To ensure an exact, rigorous causal comparison between **Configuration B** (Control) and **Configuration B+** (Candidate), the experimental workload comprises 6 standardized engineering project archetypes representing diverse software engineering disciplines.

Each archetype is executed twice under identical conditions:
1. **Control Run (Configuration B)**: Item 01 on Worker 1; Stage 2 parallelized; Stage 3 on Worker 1.
2. **Candidate Run (Configuration B+)**: Item 01 on Worker 2; Stage 2 parallelized; Stage 3 on Worker 1.

All runs use:
- **Temperature**: `0.0` (deterministic generation).
- **Physical Models**: Homogeneous dual-30B AWQ MoE (`cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`).
- **Target Git SHA**: `ca5385348321fba5a2f17f7f19f457bfe0d52eba`.
- **API Boundary**: Identical external authority containment and schema gates.

---

## 2. Project Archetype Specifications

### 2.1 Archetype 1: API Refactoring (`proj-api-01`)
- **Title**: API Gateway Endpoints and Schema Validation
- **Domain**: Distributed Gateway & HTTP Routing
- **Key Deliverables**:
  - Item 01: Analysis of endpoint routing tables, middleware latency, and request validation bottlenecks.
  - Item 02: Execution DAG for gateway decoupling and zero-downtime routing cutover.
  - Item 03: Async gateway handler implementation with rate limiting and circuit breaking.
  - Item 04: Advisory test suite covering 4xx/5xx edge cases and connection drops.
  - Item 05: Strict OpenAPI/JSON-Schema contracts for request/response payloads.
  - Item 06: Security audit of header parsing, CORS policies, and SSRF vulnerabilities.
  - Item 07: Multi-file integration with gateway router and downstream proxy.
  - Item 08: Acceptance signoff against performance SLAs (<10ms P99 overhead).

### 2.2 Archetype 2: Security Remediation (`proj-sec-02`)
- **Title**: RBAC Security Remediation and Input Sanitization
- **Domain**: Access Control & Threat Mitigation
- **Key Deliverables**:
  - Item 01: Threat model analysis, privilege escalation vector review, and token validation audit.
  - Item 02: Migration plan for least-privilege role matrix and session revocation.
  - Item 03: Core RBAC interceptor and cryptographic token verification logic.
  - Item 04: Adversarial test suite attempting privilege escalations and token replay.
  - Item 05: JSON Schema contract for permission tokens and audit log envelopes.
  - Item 06: Lead security review verifying zero bypass vectors and secure defaults.
  - Item 07: Integration of authorization middleware into protected service routes.
  - Item 08: Security signoff with compliance receipt.

### 2.3 Archetype 3: Schema Contract (`proj-schema-03`)
- **Title**: Structured Output Contract & Event Schema Migration
- **Domain**: Data Serialization & Event-Driven Architecture
- **Key Deliverables**:
  - Item 01: Audit of unstructured logging and polymorphic event payloads across services.
  - Item 02: Plan for backwards-compatible event schema versioning and registry dispatch.
  - Item 03: Schema registry client and serializing pipeline implementation.
  - Item 04: Mutation tests validating backward and forward schema compatibility.
  - Item 05: Canonical JSON Schema draft-07 definitions for domain events.
  - Item 06: Review of serialization memory footprint and deserialization denial-of-service risks.
  - Item 07: Integration across event bus publisher and subscriber boundaries.
  - Item 08: Schema conformance verification and project signoff.

### 2.4 Archetype 4: Async Worker (`proj-worker-04`)
- **Title**: Async Task Queue Worker Concurrency Engine
- **Domain**: Concurrency, Asynchronous Pipelines & Backpressure
- **Key Deliverables**:
  - Item 01: Profiling of thread contention, queue starvation, and dead-letter queue behavior.
  - Item 02: Execution DAG for lock-free worker pool rebalancing and bounded concurrency.
  - Item 03: Distributed worker pool implementation with dynamic batching and lease renewal.
  - Item 04: Stress tests evaluating worker crash recovery and poison-pill handling.
  - Item 05: Task message envelope and acknowledgment receipt schema.
  - Item 06: Concurrency and race condition safety audit under extreme load.
  - Item 07: Integration with Redis/Celery backend and queue health probes.
  - Item 08: Concurrency benchmark validation and project acceptance.

### 2.5 Archetype 5: Database Migration (`proj-db-05`)
- **Title**: Multi-Tenant Isolation and Transaction Engine
- **Domain**: Relational Persistence & Isolation Guarantees
- **Key Deliverables**:
  - Item 01: Database lock contention analysis, tenant cross-talk risks, and index efficiency.
  - Item 02: Phased migration plan with rollback triggers and shadow-writing validation.
  - Item 03: Row-level security (RLS) enforcement engine and tenant-scoped connection pool.
  - Item 04: Data integrity test suite validating isolation across concurrent tenant transactions.
  - Item 05: Tenant context header and audit log schema definitions.
  - Item 06: SQL injection and tenant data leak vulnerability review.
  - Item 07: Migration script execution and connection pool integration.
  - Item 08: Data verification and acceptance signoff.

### 2.6 Archetype 6: Observability Gateway (`proj-obs-06`)
- **Title**: Telemetry Ingestion Pipeline and Metrics Aggregator
- **Domain**: Distributed Tracing & High-Volume Telemetry
- **Key Deliverables**:
  - Item 01: Investigation of trace sampling rates, ingestion bottlenecks, and memory overhead.
  - Item 02: Implementation DAG for zero-allocation metric parsing and ring-buffer queuing.
  - Item 03: High-throughput telemetry parser and OpenTelemetry exporter.
  - Item 04: Benchmark tests simulating 100k events/sec with random drop injection.
  - Item 05: OTLP-compliant trace span and metric batch schema.
  - Item 06: Security audit of telemetry sanitization (PII redaction and header scrub).
  - Item 07: Integration with Prometheus/Jaeger pipeline and alert rules.
  - Item 08: Telemetry accuracy verification and signoff.

---

## 3. Workload Parity & Confounding Control

By evaluating each archetype under both configurations:
1. **Semantic Task Invariance**: The input prompts and expected outputs for each archetype are 100% identical.
2. **Model Invariance**: Both Worker 1 and Worker 2 run the exact same `cyankiwi/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` checkpoint.
3. **Causal Isolation**: Any difference in Worker 1 critical-path service demand and throughput is mathematically attributable to the scheduler task placement and handoff mechanism, eliminating model capability or prompt variance as confounding variables.
