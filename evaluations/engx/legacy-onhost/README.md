# Retired: on-host direct-worker evaluation runners (2026-10-06/07)

`cand.sh`, `runqueue.sh` and the queue files ran candidate llama.cpp servers on ai-5820-01 and called them directly. They were
used once, for the 2026-10-06/07 model evaluation. That use was an operator-approved exception that predates the gateway-only
(docs/design/04) and remote-origin (docs/design/05) policies.

They are kept only as the exact record of how that evaluation was run. They are **not a supported path**. Qualification now runs
from a remote client through the gateway, using the candidate aliases created by `playbooks/candidate.yml` (Design 03 R4).
