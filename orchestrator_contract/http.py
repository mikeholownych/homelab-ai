"""Shared verified HTTPS setup for clients talking to the remote AIHost gateway."""
from __future__ import annotations

import os
from pathlib import Path
import ssl
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def gateway_base_url() -> str:
    """Return the configured API root without a trailing slash."""
    return os.environ.get("AIHOST_GATEWAY_BASE_URL", "https://10.0.8.5:8443/v1").rstrip("/")


def gateway_ssl_context(url: str, ca_path: str | Path | None = None) -> ssl.SSLContext | None:
    """Build a normal verifying TLS context, trusting the fetched gateway CA when configured."""
    if urlsplit(url).scheme != "https":
        return None
    configured = ca_path or os.environ.get("AIHOST_GATEWAY_CA_BUNDLE")
    if configured is None:
        default_path = Path.home() / ".config/opencode/t5820-gateway-ca.crt"
        configured = str(default_path) if default_path.is_file() else None
    if configured:
        return ssl.create_default_context(cafile=str(configured))
    return ssl.create_default_context()


def gateway_urlopen(request: Request, timeout: float):
    """Open an HTTP request, verifying HTTPS with the fetched gateway certificate."""
    return urlopen(request, timeout=timeout, context=gateway_ssl_context(request.full_url))
