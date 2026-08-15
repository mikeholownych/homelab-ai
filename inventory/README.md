# Inventory contracts

This inventory intentionally keeps commissioning placeholders such as `CHANGE_ME`
for operator input. Those values are expected to be replaced by an operator or
automation layer before live execution.

Ansible reserves the flat variable name `environment`, so environment identity is
stored at `node_metadata.environment` instead of a top-level `environment` key.
That is an intentional compatibility choice to keep `ansible-inventory` and
`ansible-lint` warning-free while preserving explicit environment metadata.
