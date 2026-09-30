# Issue #4 Ansible checks

Run these commands from the repository root. The fixture inventory contains
only `localhost` with `ansible_connection=local`; it has no production hosts or
IP addresses.

```sh
export ANSIBLE_CONFIG=tests/fixtures/issue4/ansible.cfg
export ANSIBLE_LOCAL_TEMP=/tmp/issue4-ansible-tmp
mkdir -p "$ANSIBLE_LOCAL_TEMP" /tmp/issue4-ansible-remote-tmp

.venv/bin/ansible-playbook --syntax-check \
  -i tests/fixtures/issue4/inventory.ini playbooks/vault-server.yml
.venv/bin/ansible-lint roles/vault_server playbooks/vault-server.yml
.venv/bin/ansible-playbook --check \
  -i tests/fixtures/issue4/inventory.ini playbooks/vault-server.yml \
  -e ansible_become=false -e vault_server_manage=false
```

In an unrestricted local development runner, the final command is expected to
fail at the first explicit approval assertion. It validates the fail-closed
guard using local fact gathering only; it does not install software, write
service configuration, contact a Vault endpoint, or load production inventory.
Some restricted runners deny Ansible Core's local RPC subprocess/socket before
the play starts; record that as a blocked execution test, not as a passed
fail-closed test. Do not change the fixture inventory to point at a remote
host. Full role execution, initialization, recovery and backup/restore tests
require the approved design decisions and a disposable VM/NFS fixture.

The repository's `requirements.txt` is hash-pinned and includes the Ansible
Core, ansible-lint, and yamllint versions. A clean development environment can
be created without involving production:

```sh
python3 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements.txt
.venv/bin/ansible-galaxy collection install -r requirements.yml
```
