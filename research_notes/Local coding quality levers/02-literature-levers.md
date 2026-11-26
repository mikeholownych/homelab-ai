# Literature: what actually moves coding acceptance

Skeptical synthesis, Nov 2025–2026 sources. Prefer controlled / budget-matched results.

## Stronger signals

### 1. Verification + revision in the *agent harness* (not free-form LLM nits)

[Rethinking Verification in Agent Harnesses](https://arxiv.org/abs/2610.34577): across 7 frontier coding models, **independent review** of task requirements + **changes** (not full trajectories) gained **+3.9–9.5** points on Terminal-Bench / SWE-bench Verified at ~1.0–1.25× cost. Mid-turn reminders help modestly; completion gates can help but cost more. Trajectory-fed critics cost more and do not consistently win.

**Local fit:** Our dual reviewer saw proposed files but investigation grounded almost nothing → dropped everything. Literature’s “review” is closer to a **harness gate with required revision**, not soft JSON nits.

### 2. Budget-matched sampling often beats fancy multi-agent quality tricks

[Beyond Passing Tests](https://arxiv.org/abs/2610.38977): large SLR + controlled re-eval. At matched budgets, **best-of-n with an analyzer-weighted ranker** matched or beat prompting, planning, self-refinement, reviewer agents, and retrieval on several quality axes. Head-to-head: only **1/66** techniques beat best-of-n beyond chance on their primary target.

**Local fit:** We spent dual budget on a noop critic instead of a second independent implement sample + oracle pick.

### 3. Scaffold × model fit dominates “more agents”

[SWE-Effi](https://arxiv.org/html/2509.09853): scaffold performance is highly model-dependent. Agentless + Qwen3-32B hit 48% on a Verified subset vs SWE-Agent 28% with the same model. **Model choice often outweighs scaffold brand**, but wrong scaffold wastes a good model.

[Agentless](https://dl.acm.org/doi/10.1145/3715754): simple localize → repair → validate (with sampling) beat many complex agents at lower cost on SWE-bench Lite.

[Thinking Longer, Not Larger](https://arxiv.org/abs/2503.23803): 32B + test-time search → 46% SWE-bench Verified — compete with much larger models via **TTC**, not more peers.

### 4. Correlated errors / same-family review

[Homogenization in Multi-Agent Systems](https://arxiv.org/abs/2610.09824): MAS can amplify **shared** security blind spots; reviewers overconfident.

[Specification as Quality Gate](https://arxiv.org/html/2603.25773): same-family generator+reviewer share prior; without external spec/tests, review is circular. Spec/BDD gates caught planted bugs LLM review missed.

[Fresh Eyes Beat a Second Family](https://stephens.page/blog/fresh-eyes-beat-a-second-family/paper/fresh-eyes-beat-a-second-family.pdf): preregistered replay — gains often attributed to cross-family review were largely **fresh independent session**; placement of the second look mattered more than family. Also: authoring agent **declining** findings was as big a lever as finding them.

### 5. Verifier allocation under imperfect verifiers

[Sample, Mix, or Verify? (SPLIT)](https://arxiv.org/abs/2610.23255): how to split budget across sampling vs verification depends on verifier reliability; fixed rules lose points. More LLM judges can **lower** precision when correlated.

## What the evidence does **not** support

- “Add a third worker / more LLM roles” as a default quality strategy.
- Measuring collaboration value with an oracle that already passed **before** review.
- Treating engx chat FILE dumps as equivalent to SWE-agent / Nexus tool loops.
- Assuming Qwen-only fleet diversity is “multi-model.”

## Additional synthesis ([coding quality levers](1fda2058-d267-481d-86d3-95e7c678ef24))

- **Coverage ≫ selection:** heavy sampling raises oracle coverage; majority/reward selection recovers only part ([Large Language Monkeys](https://arxiv.org/abs/2407.21787), [CodeMonkeys](https://arxiv.org/abs/2501.14723)).
- **Execution is the judge:** Agentless gains came from regression + repro-test filters, not vote alone; intrinsic self-correction without feedback often hurts.
- **Pointwise LLM review is a weak gate** (high false-accept); groupwise comparison among *execution-passing* candidates is less bad.
- **Debate / MAD** rarely beats self-consistency at matched compute; heterogeneity helps more than role-play (mostly math/QA evidence).
- **Correlated errors cap ensembles** (~60% agree when both wrong); Self-MoA often beats mixed MoA unless peers are matched quality.
- **Scaffold spread can exceed model deltas**; harness union solves unique tasks — without an execution verifier, coverage ≠ acceptance.
- **Routing** is mostly a **cost** lever; learned routers rarely beat best-single on acceptance.
- **Hidden-test noise:** “resolved” can still be wrong under stronger suites — strengthen oracles before crowning a strategy.

## Ranked levers for *this* fleet (hypothesis order)

1. **Change the problem loop** — agent/scaffold + execution feedback + best-of-n under fixed token budget.
2. **Parallel rollouts + execution-gated selection** (treat ROCm-same-weights as extra sample, not critic) — only after (1).
3. **Change at least one artifact family** — non-Qwen peer (Devstral / GLM / Nanbeige / gpt-oss).
4. **Measure complementarity (β = all-fail rate)** before building heterogeneous generation or debate.
5. **Route for cost/latency**, not as an acceptance bet — unless fingerprints beat always-best in a paired test.
6. **LLM-LLM review last**, and only as **executable** critique (failing test / counterexample), never free-text veto.
