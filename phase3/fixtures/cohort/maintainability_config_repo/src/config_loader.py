"""Duplicated configuration loader module for maintainability refactoring."""
import os
from typing import Any


def load_database_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Loads database settings from environment with type conversions and defaults."""
    source = env if env is not None else os.environ

    host = source.get("DB_HOST", "localhost")
    raw_port = source.get("DB_PORT", "5432")
    try:
        port = int(raw_port)
    except ValueError:
        raise ValueError(f"Invalid integer value for DB_PORT: {raw_port}")

    raw_timeout = source.get("DB_TIMEOUT", "30.0")
    try:
        timeout = float(raw_timeout)
    except ValueError:
        raise ValueError(f"Invalid float value for DB_TIMEOUT: {raw_timeout}")

    raw_ssl = source.get("DB_SSL", "false").lower()
    ssl = raw_ssl in ("true", "1", "yes")

    return {
        "host": host,
        "port": port,
        "timeout": timeout,
        "ssl": ssl,
    }


def load_cache_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Loads cache settings from environment with duplicate type conversions and defaults."""
    source = env if env is not None else os.environ

    host = source.get("CACHE_HOST", "localhost")
    raw_port = source.get("CACHE_PORT", "6379")
    try:
        port = int(raw_port)
    except ValueError:
        raise ValueError(f"Invalid integer value for CACHE_PORT: {raw_port}")

    raw_timeout = source.get("CACHE_TIMEOUT", "5.0")
    try:
        timeout = float(raw_timeout)
    except ValueError:
        raise ValueError(f"Invalid float value for CACHE_TIMEOUT: {raw_timeout}")

    raw_ssl = source.get("CACHE_SSL", "false").lower()
    ssl = raw_ssl in ("true", "1", "yes")

    return {
        "host": host,
        "port": port,
        "timeout": timeout,
        "ssl": ssl,
    }


def load_auth_config(env: dict[str, str] | None = None) -> dict[str, Any]:
    """Loads authentication settings from environment with duplicate type conversions."""
    source = env if env is not None else os.environ

    host = source.get("AUTH_HOST", "auth.local")
    raw_port = source.get("AUTH_PORT", "8080")
    try:
        port = int(raw_port)
    except ValueError:
        raise ValueError(f"Invalid integer value for AUTH_PORT: {raw_port}")

    raw_timeout = source.get("AUTH_TIMEOUT", "10.0")
    try:
        timeout = float(raw_timeout)
    except ValueError:
        raise ValueError(f"Invalid float value for AUTH_TIMEOUT: {raw_timeout}")

    raw_ssl = source.get("AUTH_SSL", "true").lower()
    ssl = raw_ssl in ("true", "1", "yes")

    return {
        "host": host,
        "port": port,
        "timeout": timeout,
        "ssl": ssl,
    }
