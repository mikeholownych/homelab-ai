# Phase 11 Candidate Registry Report: Configuration Schema, Canonical Digests, and Control Protection

## Executive Summary

Phase 11 Workstream B established the Candidate Configuration Registry, providing an immutable, validated catalog of model identities, quantization profiles, specialized agent configurations, reasoning budgets, and physical worker mappings.

---

## 1. Candidate Configuration Schema

Every registered candidate must adhere to a strict 11-field specification:
1. `candidate_id`: Unique identifier string.
2. `model_identity`: Full model repository/identifier (e.g. `Qwen/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit`).
3. `model_revision`: Exact revision tag or commit hash (e.g. `2026-03-r1`).
4. `quantization`: Quantization format (e.g. `awq-4bit`, `fp8`, `none`).
5. `inference_parameters`: Dictionary specifying `tensor_parallel`, `max_model_len`, `gpu_memory_utilization`.
6. `profile_name`: Name of specialized agent profile (e.g. `implementation-engineer`).
7. `profile_version`: Semantic version string (e.g. `1.0.0`, `1.1.0`).
8. `reasoning_budget`: Reasoning configuration (`max_reasoning_tokens`, `effort_level`).
9. `context_strategy`: Context construction method (e.g. `full_file`, `targeted_symbols`, `diff_focused`).
10. `tool_adapter`: Tool interfacing adapter identity (e.g. `strict_sandboxed_v2`).
11. `physical_worker`: Target inference worker host/node (e.g. `worker-b65-0`).

---

## 2. Canonical SHA-256 Digesting

To prevent configuration spoofing or unrecorded drift, the registry calculates a 64-character hexadecimal SHA-256 digest over the canonical, key-sorted JSON representation of the configuration.
- Any discrepancy between the stored digest and the computed digest raises an immediate `CandidateValidationError`.
- Registrations with missing required fields or duplicate candidate IDs fail closed.

---

## 3. Protected Control Baseline Registration

The active operational serving baseline on node `10.0.8.5` is registered as the immutable control:
- Candidate ID: `control-b0-qwen3-coder-awq-tp1-v1`
- Model: `Qwen/Qwen3-Coder-30B-A3B-Instruct-AWQ-4bit` (`2026-03-r1`)
- Quantization: `awq-4bit` (TP=1)
- Context Window: 32,768 tokens
- Memory Target: 90% GPU VRAM utilization
- Serving Worker: Port 18010 on dual Intel Arc Pro B65 GPUs
- Control Status: Protected against uncoordinated eviction or in-place overwrite.
