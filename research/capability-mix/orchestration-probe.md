# Orchestration probe rubric

Not a CAIS grant. Score each scenario 0–2 (0 fail, 1 partial, 2 pass).
Winner needs total ≥ baseline lead total, and no scenario scored 0.

## orch_tools
Model must propose valid tool calls, consume results, and finish with a concrete answer.
Pass = schema-valid tools + correct final answer from tool output.

## orch_route
Given a user ask + peer/capability menu (lead, deep, rocm-text, ocr, image-gen),
model must pick the right next hop and a stop condition.
Pass = correct primary hop + explicit stop/done rule.