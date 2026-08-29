# Inventory contracts

This inventory intentionally keeps one operator input placeholder: the
`ansible_host` value in production host vars. That sole exception is expected to
be replaced by an operator or automation layer before live execution.

Ansible reserves the flat variable name `environment`, so environment identity is
stored at `node_metadata.environment` instead of a top-level `environment` key.
That is an intentional compatibility choice to keep `ansible-inventory` and
`ansible-lint` warning-free while preserving explicit environment metadata.

## Adding a new host

Copy `production/host_vars/TEMPLATE.yml` to `production/host_vars/<hostname>.yml`,
register the host in `production/hosts.yml` under the `ai_hosts` child groups it
belongs to, then replace every `REPLACE_ME` value. The template documents every
field; a new platform needs a matching `profiles/hardware/<profile>.yml` (copy
`profiles/hardware/template.yml`), and OS tuning starts at the shipped
`baseline` profile until benchmark evidence justifies a candidate
(`profiles/tuning/_template/template.yml`). See README: How to Add Further Hosts.
