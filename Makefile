VENV_DIR ?= .venv
PYTHON_BIN ?= python3
VENV_PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_PYTHON) -m pip
ANSIBLE_PLAYBOOK := $(VENV_DIR)/bin/ansible-playbook
ANSIBLE_LINT := $(VENV_DIR)/bin/ansible-lint
ANSIBLE_GALAXY := $(VENV_DIR)/bin/ansible-galaxy
PYTEST := $(VENV_DIR)/bin/pytest
YAMLLINT := $(VENV_DIR)/bin/yamllint
ANSIBLE_TIMEOUT := timeout -k 5s 60s

PLAYBOOKS := \
	playbooks/bootstrap.yml \
	playbooks/baseline.yml \
	playbooks/site.yml \
	playbooks/drift-check.yml \
	playbooks/patch.yml \
	playbooks/upgrade.yml \
	playbooks/validate.yml \
	playbooks/benchmark.yml \
	playbooks/facts-export.yml

.PHONY: bootstrap-tools lint syntax test check idempotency quality

bootstrap-tools:
	$(PYTHON_BIN) -m venv $(VENV_DIR)
	$(PIP) install --require-hashes -r requirements.txt
	$(ANSIBLE_GALAXY) collection install -r requirements.yml

lint: bootstrap-tools
	$(YAMLLINT) .
	$(ANSIBLE_LINT) .

syntax: bootstrap-tools
	set -eu; for playbook in $(PLAYBOOKS); do ANSIBLE_CONFIG=ansible.cfg $(ANSIBLE_PLAYBOOK) --syntax-check $$playbook; done

test: bootstrap-tools
	$(PYTEST) -q

check: bootstrap-tools
	@echo "Running localhost-safe Ubuntu 24.04 contract check mode; this validates baseline wiring and does not assert host convergence."
	ANSIBLE_CONFIG=ansible.cfg $(ANSIBLE_PLAYBOOK) -i tests/fixtures/inventory/healthy.yml --check tests/integration/baseline_os.yml

idempotency: bootstrap-tools
	@tmp_root=$$(mktemp -d .ansible/idempotency.XXXXXX); \
	trap 'rm -rf "$$tmp_root"' EXIT; \
	printf '%s\n' "Seeding localhost-safe baseline state for idempotency probe..."; \
	ANSIBLE_CONFIG=ansible.cfg LOCALHOST_SAFE_ROOT="$$tmp_root" $(ANSIBLE_TIMEOUT) $(ANSIBLE_PLAYBOOK) -i tests/fixtures/inventory/healthy.yml tests/integration/baseline_idempotency.yml >/dev/null; \
	second_run_output=$$(ANSIBLE_CONFIG=ansible.cfg LOCALHOST_SAFE_ROOT="$$tmp_root" $(ANSIBLE_TIMEOUT) $(ANSIBLE_PLAYBOOK) -i tests/fixtures/inventory/healthy.yml tests/integration/baseline_idempotency.yml); \
	printf '%s\n' "$$second_run_output"; \
	printf '%s\n' "$$second_run_output" | awk '/localhost[[:space:]]*: ok=/{for(i=1;i<=NF;i++) if($$i ~ /^changed=/){split($$i,a,"="); found=1; if(a[2] != 0) exit 1}} END{if(found != 1) exit 1}'

quality: lint test syntax check check idempotency
