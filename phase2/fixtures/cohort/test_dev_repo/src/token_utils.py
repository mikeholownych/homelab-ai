"""Token validation utilities."""


def validate_bearer_token(auth_header: str | None) -> str | None:
    """Validates and extracts Bearer token from Authorization header.

    Rules:
    - Must start with 'Bearer ' (case-sensitive)
    - Token must not be empty or only whitespace
    - Token must not contain internal whitespace or newlines
    - Returns stripped token if valid, None otherwise.
    """
    if not auth_header or not isinstance(auth_header, str):
        return None
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:].strip()
    if not token:
        return None
    if any(c.isspace() for c in token):
        return None
    return token
