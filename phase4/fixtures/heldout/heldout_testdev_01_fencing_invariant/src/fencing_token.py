"""Fencing token generator for distributed concurrency control."""
from dataclasses import dataclass
from typing import Dict

@dataclass(frozen=True)
class FencingToken:
    resource_id: str
    token_number: int
    holder: str

class FencingManager:
    def __init__(self) -> None:
        self._current_tokens: Dict[str, int] = {}
        self._holders: Dict[str, str] = {}

    def acquire_fence(self, resource_id: str, holder: str) -> FencingToken:
        current = self._current_tokens.get(resource_id, 0)
        next_token = current + 1
        self._current_tokens[resource_id] = next_token
        self._holders[resource_id] = holder
        return FencingToken(resource_id=resource_id, token_number=next_token, holder=holder)

    def validate_fence(self, token: FencingToken) -> bool:
        """Validates that the token is strictly equal to the active token."""
        active_num = self._current_tokens.get(token.resource_id)
        if active_num is None or token.token_number != active_num:
            return False
        return self._holders.get(token.resource_id) == token.holder
