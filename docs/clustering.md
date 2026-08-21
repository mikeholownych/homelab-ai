# Multi-Node Fleet and Clustering Architecture

## Fleet Model

Although the initial target is a single Lenovo ThinkStation P620 (`ai-p620-01`), the inventory and role architecture are designed to scale cleanly across multi-node clusters.

## Inventory Metadata

Nodes define clustering properties in inventory:
```yaml
cluster:
  name: null # or cluster name string
  enabled: false
  roles:
    worker: false
    api: false
    scheduler: false
    storage: false
```

## Capabilities and Feature Toggles

- `capabilities.cluster_eligible`: Set to `true` on nodes capable of participating in distributed inference.
- `features.clustering`: Feature toggle enabling cluster daemon configuration (e.g. Ray / distributed vLLM) when activated.
