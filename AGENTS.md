# Project Guidelines & Agent Instructions

## Commands
- Environment Setup: `make bootstrap-tools` (manages `.venv`, pip hashes, galaxy requirements)
- Test: `.venv/bin/pytest -q` or `make test`
  - Target specific tests during development: `.venv/bin/pytest tests/unit/ -v` or `.venv/bin/pytest tests/test_observability_as_code.py`
  - Avoid running unbounded full-suite tests without specifying targets, as container baseline harnesses can take >15 minutes.
- Lint: `make lint` (`yamllint .` and `ansible-lint .`)
- Syntax Check: `make syntax` (validates all Ansible playbooks)
- Observability Verification:
  - Validate rules & alerts: `tests/test_observability_as_code.py` and `promtool check rules` / `promtool test rules`
  - Rebuild & sync dashboard templates: `python3 observability/tools/build_dashboards.py`

## Observability & Dashboard Conventions
- **Template Synchronization**: When modifying Grafana dashboards, NEVER edit only the static JSON or only the Jinja2 template. Always run `python3 observability/tools/build_dashboards.py` to ensure `observability/grafana/dashboards/*.json` and `roles/observability/templates/*.json.j2` stay strictly synchronized.
- **Zero/Idle Fallbacks**: Metrics for inference, workers, and gateway telemetry can be sparse when idle. PromQL queries must provide fallbacks (e.g. `or vector(0)` or `or (0 * sum by (...) (aihost_worker_info))` or `label_replace(...)`) and specify meaningful `noDataText` to avoid displaying "No data" panels.

## Deployment & Verification Guardrails
- **Service Verification**: When deploying or restarting services (e.g., `aihost-orchestrator-gateway`, `grafana`, `vllm`), verify the service status and recent journal logs via `systemctl status <service>` / `journalctl -u <service> -n 30` on the target host before concluding the task.
- **Inventory & Release Bumps**: When deploying gateway updates, ensure release identifiers in `inventory/production/hosts.yml` or host variables match the deployed artifacts.

## Code Conventions
- Maintain documentation integrity and keep existing comments.
- Always run targeted tests after making changes to verify correctness.
- Keep functions modular and clearly typed.

