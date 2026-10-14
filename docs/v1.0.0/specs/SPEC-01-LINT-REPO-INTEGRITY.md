# Technical Specification: SPEC-01 - Repository Hygiene & CI Linter Compliance

- **Specification ID**: `SPEC-01`
- **Related Finding**: `F-02` (`make lint` fatal violations in rules, gateway defaults, and tasks)
- **Related Requirements**: `REQ-SEC-05` (Clean Linter Gate Compliance), `REQ-VAL-01`
- **Target Milestone**: `M0` (Repository Hygiene & CI Integrity Containment)
- **Status**: Ready for Implementation

---

## 1. Problem Statement & Evidence
Running the standard repository quality check `make lint` fails with 3 fatal errors:
1. `observability/prometheus/rules/aihost.rules.yml:186`: `yaml[empty-lines]: Too many blank lines (1 > 0)`
2. `roles/orchestrator_gateway/defaults/main.yml:89`: `yaml[line-length]: Line too long (157 > 120 characters)`
3. `roles/orchestrator_gateway/tasks/main.yml:350:13`: `var-naming[no-role-prefix]: Variables names from within roles should use orchestrator_gateway_ as a prefix. (register: _historical_gateway_releases)`

Because `make quality` invokes `make lint` as its first target, automated repository CI is completely blocked on clean checkouts.

---

## 2. Desired Behavior & Scope
- **Scope**:
  - Reformat `observability/prometheus/rules/aihost.rules.yml` to remove excessive blank lines between alert rule blocks.
  - Wrap long comment/default variable assignment in `roles/orchestrator_gateway/defaults/main.yml` to adhere to the 120-character line length limit.
  - Rename the task-registered variable `_historical_gateway_releases` to `_orchestrator_gateway_historical_releases` in `roles/orchestrator_gateway/tasks/main.yml` (and update any subsequent task references in that file).
  - Verify that `yamllint .` and `ansible-lint .` exit with code 0.
- **Non-Goals**:
  - Refactoring other rule definitions or alerting logic.
  - Modifying linter rule configuration files (`.yamllint`, `.ansible-lint`).

---

## 3. Interfaces & State Transitions
- **File Changes**:
  - `observability/prometheus/rules/aihost.rules.yml`
  - `roles/orchestrator_gateway/defaults/main.yml`
  - `roles/orchestrator_gateway/tasks/main.yml`
- **Variable Contract**:
  - Old: `register: _historical_gateway_releases`
  - New: `register: _orchestrator_gateway_historical_releases`
  - Reference updates: In pruning tasks, update `_historical_gateway_releases.files` to `_orchestrator_gateway_historical_releases.files`.

---

## 4. Security & Operational Implications
- No change to runtime behavior or production security controls.
- Restores fail-closed enforcement of CI lint gates on pull requests and commits.

---

## 5. Acceptance Criteria
1. `yamllint .` returns exit code 0.
2. `ansible-lint .` returns exit code 0 with 0 violations.
3. `promtool check rules observability/prometheus/rules/aihost.rules.yml` succeeds.
4. `make syntax` passes across all playbooks.
