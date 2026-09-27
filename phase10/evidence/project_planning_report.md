# Workstream C: Engineering Project Planning and Decomposition Report
## Autonomous Engineering System — Phase 10

### 1. Overview and Invariants

The `EngineeringProjectPlanner` translates complex, multi-module engineering objectives into structured `EngineeringProjectPlan` artifacts consisting of bounded, dependency-ordered `ProjectWorkOrder` records.

Two non-negotiable architectural invariants are enforced at the planning layer:
1. **Scope Non-Expansion**:
   $$\forall w \in \text{work\_orders}, \; \forall p \in w.\text{authorized\_mutation\_paths}, \; \exists s \in \text{plan}.\text{authorized\_project\_scope} \text{ s.t. } p \subseteq s$$
   A decomposed work order cannot possess authority to modify paths outside the overall authorized project scope.
2. **Planner Self-Authorization Prohibition**:
   $$\text{authorizer\_identity} \notin \text{AutomatedRoles} \land \text{authorizer\_role} \notin \{\text{agent}, \text{planner}\}$$
   Autonomous planning agents and model workers are strictly prohibited from approving their own execution plans. Human authorization by an identified operator or engineering lead is mandatory before execution admission.

### 2. Implementation Architecture

1. **Cycle Detection via Tarjan's Algorithm**:
   - `_detect_cycles()` runs strongly connected component (SCC) analysis over dependency edges. Any cycle or self-dependency raises `ProjectDependencyCycleError` with the exact circular path.
2. **Deterministic Plan Hashing**:
   - Computes canonical SHA-256 digest `plan_digest` over project ID, objective, authorized scope, work order IDs, target files, and dependency edges.
3. **Explicit Handoff Signatures**:
   - Each work order specifies required agent profile specialization (`implementation-engineer`, `test-engineer`, `security-reviewer`, etc.), token budgets, acceptance criteria, and failure policies (`ABORT_PROJECT`, `RETRY`, `CONTINUE_BEST_EFFORT`).

### 3. Empirical Qualification Results

| Test Case | Metric Evaluated | Observed Result | Qualification Status |
|---|---|---|---|
| `test_valid_project_plan_creation` | Multi-stage plan synthesis and validation | Clean DAG created; canonical digest generated; human authorization attached | **PASS** |
| `test_cyclic_dependency_rejected` | Cycle detection on cyclic edges | Circular dependencies immediately raise `ProjectDependencyCycleError` | **PASS** |
| `test_unauthorized_scope_expansion_rejected` | Boundary containment | Work order targeting out-of-scope file raises `UnauthorizedScopeExpansionError` | **PASS** |
| `test_planner_self_authorization_prohibited` | Agent self-authorization prevention | Planner attempting self-authorization raises `SelfAuthorizationProhibitedError` | **PASS** |

### 4. Summary Disposition

Workstream C (`EngineeringProjectPlanner`) is verified, strictly enforced by fail-closed invariants, and qualified for production project orchestration.
