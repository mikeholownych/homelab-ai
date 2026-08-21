# CMDB Integration Architecture

## Overview

The `cmdb_export` role and `playbooks/facts-export.yml` generate normalized Configuration Item (CI) records representing observed host topology and declared desired state.

## Schema

Export data conforms to `schemas/cmdb.schema.json`. It captures:
- Node identity: `node_id`, `hostname`, `environment`
- CI attributes: hardware profile, capabilities, cluster membership, runtime versions
- Expected vs observed state separation
- Timestamps: `last_convergence_at`, `last_validation_at`
- Provenance: Git SHA

## Adapter Neutrality

The export is product-agnostic and serves as the integration layer for:
- ServiceNow
- Jira Assets
- Device42
- NetBox
