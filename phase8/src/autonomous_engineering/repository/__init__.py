"""Repository management package for Phase 8."""
from autonomous_engineering.repository.onboarding import (
    RepositoryContract,
    RepositoryOnboardingManager,
    RepositoryError,
    RepositoryNotOnboardedError,
    RepositoryValidationError,
    ProtectedPathViolationError,
    ScopeBoundaryError,
)

__all__ = [
    "RepositoryContract",
    "RepositoryOnboardingManager",
    "RepositoryError",
    "RepositoryNotOnboardedError",
    "RepositoryValidationError",
    "ProtectedPathViolationError",
    "ScopeBoundaryError",
]
