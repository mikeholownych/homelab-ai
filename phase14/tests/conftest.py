"""Phase 14 test configuration: the scheduler has no built-in token, so give it an obviously fake one."""

import pytest

TEST_GATEWAY_TOKEN = "test-gateway-token-not-a-secret"


@pytest.fixture(autouse=True)
def _fake_gateway_token(monkeypatch):
    monkeypatch.setenv("AIHOST_GATEWAY_API_KEY", TEST_GATEWAY_TOKEN)
