"""Repository Onboarding, Contract Specification, and Scope Authority for Phase 8."""
from dataclasses import dataclass, field, asdict
import json
import logging
from pathlib import Path
import re
import sqlite3
from typing import Dict, List, Optional, Set, Tuple, Any

logger = logging.getLogger(__name__)


class RepositoryError(Exception):
    """Base error for repository authority and onboarding."""


class RepositoryNotOnboardedError(RepositoryError):
    """Raised when an operation targets an un-onboarded repository."""


class RepositoryValidationError(RepositoryError):
    """Raised when repository contract validation fails."""


class ProtectedPathViolationError(RepositoryError):
    """Raised when an operation attempts to modify a protected repository path."""


class ScopeBoundaryError(RepositoryError):
    """Raised when an operation attempts to modify files outside authorized mutation paths."""


@dataclass(frozen=True)
class RepositoryContract:
    """Canonical immutable engineering contract for an onboarded repository."""
    repository_id: str
    remote_url: str
    baseline_commit: str
    permitted_branches: Tuple[str, ...] = ("main",)
    authorized_mutation_paths: Tuple[str, ...] = field(default_factory=tuple)
    protected_paths: Tuple[str, ...] = (
        ".github",
        ".git",
        "ci",
        "security",
        "validators",
    )
    required_test_commands: Tuple[str, ...] = ("pytest",)
    independent_validation_requirements: Dict[str, Any] = field(default_factory=dict)
    build_constraints: Dict[str, Any] = field(default_factory=dict)
    permitted_capabilities: Tuple[str, ...] = ("read", "edit", "test")
    resource_budgets: Dict[str, Any] = field(
        default_factory=lambda: {
            "max_task_duration_sec": 600,
            "max_diff_bytes": 1048576,
            "max_concurrent_workers": 2,
        }
    )
    credential_scope: str = "read_only"
    deliverable_destination: str = "pull_request"
    integration_authority: str = "human_gate"
    designated_approver: str = "repository_owner"

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RepositoryContract":
        return cls(
            repository_id=data["repository_id"],
            remote_url=data["remote_url"],
            baseline_commit=data["baseline_commit"],
            permitted_branches=tuple(data.get("permitted_branches", ("main",))),
            authorized_mutation_paths=tuple(data.get("authorized_mutation_paths", ())),
            protected_paths=tuple(data.get("protected_paths", (".github", ".git"))),
            required_test_commands=tuple(data.get("required_test_commands", ("pytest",))),
            independent_validation_requirements=data.get("independent_validation_requirements", {}),
            build_constraints=data.get("build_constraints", {}),
            permitted_capabilities=tuple(data.get("permitted_capabilities", ("read", "edit", "test"))),
            resource_budgets=data.get("resource_budgets", {}),
            credential_scope=data.get("credential_scope", "read_only"),
            deliverable_destination=data.get("deliverable_destination", "pull_request"),
            integration_authority=data.get("integration_authority", "human_gate"),
            designated_approver=data.get("designated_approver", "repository_owner"),
        )


class RepositoryOnboardingManager:
    """Manages repository onboarding lifecycle, contracts, and scope validation."""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path = db_path
        self._memory_registry: Dict[str, RepositoryContract] = {}
        if self.db_path:
            self._init_db()
        else:
            self._conn = None

    def _init_db(self) -> None:
        assert self.db_path is not None
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS repository_contracts (
                    repository_id TEXT PRIMARY KEY,
                    remote_url TEXT NOT NULL,
                    baseline_commit TEXT NOT NULL,
                    contract_json TEXT NOT NULL,
                    is_active INTEGER NOT NULL DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
                """
            )
            conn.commit()

    def onboard_repository(self, contract: RepositoryContract) -> None:
        """Onboards a repository after strict validation of its contract."""
        self._validate_contract(contract)

        if self.db_path:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    """
                    INSERT INTO repository_contracts (repository_id, remote_url, baseline_commit, contract_json, is_active)
                    VALUES (?, ?, ?, ?, 1)
                    ON CONFLICT(repository_id) DO UPDATE SET
                        remote_url=excluded.remote_url,
                        baseline_commit=excluded.baseline_commit,
                        contract_json=excluded.contract_json,
                        is_active=1,
                        updated_at=CURRENT_TIMESTAMP
                    """,
                    (
                        contract.repository_id,
                        contract.remote_url,
                        contract.baseline_commit,
                        json.dumps(contract.to_dict()),
                    ),
                )
                conn.commit()
        else:
            self._memory_registry[contract.repository_id] = contract

        logger.info(f"Repository {contract.repository_id} successfully onboarded.")

    def get_contract(self, repository_id: str) -> RepositoryContract:
        """Retrieves active contract for an onboarded repository."""
        if self.db_path:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT contract_json, is_active FROM repository_contracts WHERE repository_id = ?",
                    (repository_id,),
                )
                row = cursor.fetchone()
                if not row or row[1] != 1:
                    raise RepositoryNotOnboardedError(
                        f"Repository '{repository_id}' is not onboarded or has been offboarded."
                    )
                return RepositoryContract.from_dict(json.loads(row[0]))
        else:
            if repository_id not in self._memory_registry:
                raise RepositoryNotOnboardedError(
                    f"Repository '{repository_id}' is not onboarded or has been offboarded."
                )
            return self._memory_registry[repository_id]

    def is_onboarded(self, repository_id: str) -> bool:
        """Checks if a repository is actively onboarded."""
        try:
            self.get_contract(repository_id)
            return True
        except RepositoryNotOnboardedError:
            return False

    def offboard_repository(self, repository_id: str) -> None:
        """Revokes a repository's onboarding status while preserving audit history."""
        if not self.is_onboarded(repository_id):
            raise RepositoryNotOnboardedError(f"Cannot offboard un-onboarded repository '{repository_id}'.")

        if self.db_path:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute(
                    "UPDATE repository_contracts SET is_active = 0, updated_at = CURRENT_TIMESTAMP WHERE repository_id = ?",
                    (repository_id,),
                )
                conn.commit()
        else:
            del self._memory_registry[repository_id]

        logger.info(f"Repository {repository_id} offboarded.")

    def validate_work_order_scope(
        self, repository_id: str, proposed_paths: List[str]
    ) -> None:
        """Validates that proposed mutation paths strictly satisfy repository contract boundaries."""
        contract = self.get_contract(repository_id)

        # 1. Reject path traversal and symlink escapism
        for p in proposed_paths:
            p_str = str(p).strip()
            if ".." in p_str or p_str.startswith("/") or p_str.startswith("~"):
                raise ScopeBoundaryError(
                    f"Path '{p}' contains prohibited path traversal, root, or home reference."
                )

        normalized_proposed = [str(p).lstrip("./").strip() for p in proposed_paths]

        # 2. Enforce Protected Paths: NO proposed path may start with or equal any protected prefix
        for p in normalized_proposed:
            for prot in contract.protected_paths:
                prot_norm = str(prot).strip().strip("./").rstrip("/")
                if p == prot_norm or p.startswith(prot_norm + "/"):
                    raise ProtectedPathViolationError(
                        f"Proposed mutation path '{p}' violates protected repository path rule '{prot}'."
                    )

        # 3. Enforce Authorized Mutation Paths (if specified)
        if contract.authorized_mutation_paths:
            for p in normalized_proposed:
                allowed = False
                for auth in contract.authorized_mutation_paths:
                    auth_norm = str(auth).strip().strip("./").rstrip("/")
                    if p == auth_norm or p.startswith(auth_norm + "/"):
                        allowed = True
                        break
                if not allowed:
                    raise ScopeBoundaryError(
                        f"Path '{p}' is outside authorized mutation paths: {contract.authorized_mutation_paths}"
                    )

    def _validate_contract(self, contract: RepositoryContract) -> None:
        """Ensures contract definitions are structurally and semantically valid."""
        if not contract.repository_id or not re.match(r"^[a-zA-Z0-9_-]+$", contract.repository_id):
            raise RepositoryValidationError(
                f"Invalid repository ID '{contract.repository_id}'. Must be alphanumeric with '-' or '_'."
            )

        if not contract.remote_url or ".." in contract.remote_url:
            raise RepositoryValidationError(f"Invalid remote URL '{contract.remote_url}'.")

        if not contract.baseline_commit or not re.match(r"^[a-fA-F0-9]{7,64}$", contract.baseline_commit):
            raise RepositoryValidationError(
                f"Invalid baseline commit '{contract.baseline_commit}'. Must be valid git hex hash."
            )

        # Check protected paths do not contain path traversal
        for p in contract.protected_paths:
            if ".." in str(p) or str(p).startswith("/"):
                raise RepositoryValidationError(f"Protected path '{p}' cannot contain path traversal.")

        # Check authorized mutation paths
        for p in contract.authorized_mutation_paths:
            if ".." in str(p) or str(p).startswith("/"):
                raise RepositoryValidationError(f"Authorized mutation path '{p}' cannot contain path traversal.")
