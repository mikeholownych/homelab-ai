# Gate G14 Evidence Provenance and Reconstruction Audit

## 1. Requirement Specification

The preregistered requirement for Gate G14, frozen in [`phase11_engineering_plan.md`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization/phase11/docs/phase11_engineering_plan.md#L234), was:

> **Gate G14: Real-inference comparative campaign**  
> *Target Threshold*: Live evaluation executed against physical `engineering/b0` endpoint.  
> *Primary Verification Artifact*: Live campaign trace & report.

The primary objective of Gate G14 was to prove that model, prompt, or agent configuration optimizations produce measurable engineering improvements over the protected control when executed against the real physical inference hardware.

---

## 2. Reconstruction of Original Phase 11 G14 Execution

An audit of commit [`47071c3`](file:///home/mike/Projects/aihost/.worktrees/phase11-model-agent-optimization) identified the exact code executed to satisfy Gate G14:

```python
# From phase11/tests/test_phase11_preregistration_gates.py (lines 197-208)
def test_gate_g14_real_inference_comparative_campaign(tmp_path):
    # Verify live endpoint reaches physical engineering/b0
    token_path = Path("/home/mike/.config/opencode/t5820-client-token")
    assert token_path.exists()
    import urllib.request
    req = urllib.request.Request(
        "http://127.0.0.1:18010/v1/models",
        headers={"Authorization": f"Bearer {token_path.read_text().strip()}"},
    )
    with urllib.request.urlopen(req, timeout=5) as response:
        assert response.status == 200
```

### Analysis of the Executed Probe
- **Target Endpoint**: `http://127.0.0.1:18010/v1/models`
- **HTTP Method**: `GET`
- **Request Body**: None (empty)
- **Model Invocations**: 0 (zero completion or chat requests dispatched)
- **Workloads Executed**: 0 (no engineering tasks, no code edits, no tests run)
- **Telemetry Captured**: HTTP status 200 and JSON model enumeration (`{"id": "engineering/b0"}`)
- **Matched Control Comparison**: None

---

## 3. Evidence Level Classification

The audit taxonomy defines four distinct levels of qualification evidence:

- **Level A: Endpoint Availability Only** (Connectivity, HTTP 200, model list)
- **Level B: Real Completion Request Without Comparative Engineering Evaluation** (Isolated text completion prompt)
- **Level C: Real-Inference Engineering Evaluation Without Matched Control** (Single configuration solving a task)
- **Level D: Complete, Matched Real-Inference Comparative Campaign** (Control vs Candidate executing matched tasks against identical acceptance contracts)

### Finding
The evidence originally submitted for Gate G14 strictly established **Level A (Endpoint Availability Only)**.

Representing a `GET /v1/models` connectivity probe as satisfaction of a "Real-Inference Comparative Campaign" was a material qualification defect.

---

## 4. Remediation Plan

To fulfill the true intent of Gate G14 without disrupting protected serving:
1. Reclassify the historical G14 record as **Level A (Endpoint Availability Only)**.
2. Formulate and execute a genuine **Level D Real-Inference Comparative Campaign** (Workstream E):
   - Benchmark the protected control (`control-b0-qwen3-coder-awq-tp1-v1`) against an optimized prompt/context strategy configuration.
   - Dispatch actual engineering prompts to `http://127.0.0.1:18010/v1/chat/completions`.
   - Record genuine request payloads, completion tokens, time-to-first-token (TTFT), duration, and response digests.
   - Apply independent validation assertions to the returned code.
   - Publish complete raw trace telemetry in `phase11/reconciliation/real_inference_comparative_results.md`.
