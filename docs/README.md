# Local AI Documentation Index

The documents in this directory describe the architecture, runbooks, and
reference material for the Local AI homelab (`aihost`). Files are grouped by
purpose; this index is the definitive map, individual files are also linked
from the relevant `README.md` sections, and coverage is contract-tested by
`tests/test_documentation_contract.py`.

## Design and architecture
- [`architecture.md`](architecture.md) — Configuration-as-Code end-to-end flow (Vault → inventory → playbooks → evidence).
- [`clustering.md`](clustering.md) — Multi-node fleet model and clustering architecture.
- [`cmdb.md`](cmdb.md) — Future CMDB integration boundary.
- [`itsm.md`](itsm.md) — Future ITSM change integration flow.
- [`observability.md`](observability.md) — Observability architecture: Alloy, VictoriaMetrics, vmalert, Loki, Grafana.

## Platform and hardware
- [`commissioning.md`](commissioning.md) — Hardware commissioning runbooks for the dual-B65 host.
- [`custom-kernel.md`](custom-kernel.md) — Custom kernel policy and workflow.
- [`intel-gpu.md`](intel-gpu.md) — Intel Arc Pro B65 and PyTorch XPU support.
- [`numa.md`](numa.md) — NUMA discovery and tuning.
- [`pcie.md`](pcie.md) — PCIe validation and benchmark evidence.
- [`tuning.md`](tuning.md) — OS tuning framework and idempotency policy.

## Operations
- [`operations.md`](operations.md) — Day-2 operator runbook (bootstrap, convergence, drift, benchmarking, patching).
- [`patching.md`](patching.md) — Host and platform patching guide.
- [`rollback.md`](rollback.md) — Component rollback runbook.
- [`upgrades.md`](upgrades.md) — Runtime and component upgrade workflow.

## Reference and integration
- [`model-catalog.md`](model-catalog.md) — Model catalog for the dual-B65 inference hosts.
- [`security-controls.md`](security-controls.md) — Baseline host security controls.
- [`vault.md`](vault.md) — HashiCorp Vault runtime integration.