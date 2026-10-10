VENV_DIR ?= .venv
PYTHON_BIN ?= python3
export PATH := $(CURDIR)/$(VENV_DIR)/bin:$(PATH)
VENV_PYTHON := $(VENV_DIR)/bin/python
PIP := $(VENV_PYTHON) -m pip
ANSIBLE_PLAYBOOK := $(VENV_DIR)/bin/ansible-playbook
ANSIBLE_LINT := $(VENV_DIR)/bin/ansible-lint
ANSIBLE_GALAXY := $(VENV_DIR)/bin/ansible-galaxy
# Sealed phase baselines (evidence manifests checksum their sources) derive synthetic outcomes from built-in str
# hash(), which Python randomizes per process, and some match plain pytest text from a subprocess. A fixed seed and no
# forced colour (an inherited FORCE_COLOR adds ANSI codes) make the verdict independent of the caller's environment.
PYTEST := PYTHONHASHSEED=0 PY_COLORS=0 $(VENV_DIR)/bin/pytest
YAMLLINT := $(VENV_DIR)/bin/yamllint
# Harness budget (--timeout 900: a cold image build plus four convergence runs, measured 444 s with a cached image)
# plus its two 120 s cleanup calls and a margin, so the harness always cleans up first.
DOCKER_HARNESS_TIMEOUT := timeout -k 10s 1170s
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
	playbooks/reboot-verify.yml \
	playbooks/commission.yml \
	playbooks/inference.yml \
	playbooks/candidate.yml \
	playbooks/vault-backup-controller.yml \
	playbooks/vault-platform-credentials.yml \
	playbooks/vault-post-init.yml \
	playbooks/vault-server.yml

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
	@echo "Running localhost-safe Ubuntu 24.04 contract check mode; this validates baseline and observability wiring and does not assert host convergence."
	ANSIBLE_CONFIG=ansible.cfg $(ANSIBLE_PLAYBOOK) -i tests/fixtures/inventory/healthy.yml --check tests/integration/baseline_os.yml
	ANSIBLE_CONFIG=ansible.cfg $(ANSIBLE_PLAYBOOK) -i tests/fixtures/inventory/healthy.yml --check tests/integration/observability_gate_check.yml

tuning-smoke: bootstrap-tools
	@echo "Running read-write OS tuning convergence against this machine (installs helpers under /usr/local/libexec, writes state under /var/lib/aihost)."
	$(ANSIBLE_PLAYBOOK) -i tests/fixtures/inventory/healthy.yml tests/integration/os_tuning_smoke.yml

tuning-idempotency: tuning-smoke
	@echo "Re-running tuning convergence and requiring a byte-stable second pass."
	scripts/check-tuning-idempotency

idempotency: bootstrap-tools
	$(DOCKER_HARNESS_TIMEOUT) $(VENV_PYTHON) $(BASELINE_CONTAINER_HARNESS) --release noble --mode idempotency --timeout 900
	$(DOCKER_HARNESS_TIMEOUT) $(VENV_PYTHON) $(BASELINE_CONTAINER_HARNESS) --release resolute --mode idempotency --timeout 900

quality: lint test syntax check idempotency tuning-idempotency
