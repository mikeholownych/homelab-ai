VENV_DIR ?= .venv
PYTHON_BIN ?= python3
VENV_PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_PYTHON) -m pip
ANSIBLE_PLAYBOOK := $(VENV_DIR)/bin/ansible-playbook
ANSIBLE_LINT := $(VENV_DIR)/bin/ansible-lint
ANSIBLE_GALAXY := $(VENV_DIR)/bin/ansible-galaxy
PYTEST := $(VENV_DIR)/bin/pytest
YAMLLINT := $(VENV_DIR)/bin/yamllint

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
	ANSIBLE_CONFIG=ansible.cfg $(ANSIBLE_PLAYBOOK) --check playbooks/baseline.yml --tags foundation

idempotency: bootstrap-tools
	@echo "Foundation scaffold only; this target validates dry-run wiring and does not assert host convergence."
	ANSIBLE_CONFIG=ansible.cfg $(ANSIBLE_PLAYBOOK) --check playbooks/baseline.yml --tags foundation

quality: lint test syntax check idempotency
