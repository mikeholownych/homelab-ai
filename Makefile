VENV_DIR ?= .venv
PYTHON_BIN ?= python3
VENV_PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_PYTHON) -m pip
ANSIBLE_PLAYBOOK := $(VENV_DIR)/bin/ansible-playbook
ANSIBLE_LINT := $(VENV_DIR)/bin/ansible-lint
ANSIBLE_GALAXY := $(VENV_DIR)/bin/ansible-galaxy
PYTEST := $(VENV_DIR)/bin/pytest
YAMLLINT := $(VENV_DIR)/bin/yamllint
DOCKER_HARNESS_TIMEOUT := timeout -k 10s 600s
BASELINE_CONTAINER_HARNESS := tests/integration/baseline_container_harness.py

PLAYBOOKS := \
	playbooks/bootstrap.yml \
	playbooks/baseline.yml \
	playbooks/site.yml \
	playbooks/drift-check.yml \
	playbooks/patch.yml \
	playbooks/upgrade.yml \
	playbooks/validate.yml \
	playbooks/benchmark.yml \
	playbooks/facts-export.yml \
	playbooks/reboot-verify.yml

.PHONY: bootstrap-tools lint syntax test check tuning-smoke idempotency quality

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

tuning-smoke: bootstrap-tools
	@echo "Running read-write OS tuning convergence against this machine (installs helpers under /usr/local/libexec, writes state under /var/lib/aihost)."
	$(ANSIBLE_PLAYBOOK) -i tests/fixtures/inventory/healthy.yml tests/integration/os_tuning_smoke.yml

tuning-idempotency: tuning-smoke
	@echo "Re-running tuning convergence and requiring a byte-stable second pass."
	scripts/check-tuning-idempotency

idempotency: bootstrap-tools
	$(DOCKER_HARNESS_TIMEOUT) $(VENV_PYTHON) $(BASELINE_CONTAINER_HARNESS) --mode idempotency --timeout 590

quality: lint test syntax check idempotency tuning-idempotency
