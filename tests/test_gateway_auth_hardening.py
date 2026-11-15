"""Auth-hardening contract for both gateway engines (ASGI production engine, sync server).

Covers: the monitoring token grants no admin access, no query-string token, constant-time digest comparison,
the local-origin refusal on admin routes, and the JWT rules (one algorithm family, exp required).
"""
from __future__ import annotations

import hmac
import json
import threading
import time
from http.client import HTTPConnection
from unittest import mock

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from starlette.testclient import TestClient

from orchestrator_gateway import GatewayServer, create_asgi_gateway, create_gateway
from orchestrator_runtime import CapabilityRegistry, EvidenceStore, InMemoryAdapter, OrchestratorRuntime
from orchestrator_runtime.clients import ClientRegistry, token_digest
from tests.test_orchestrator_runtime import worker

ADMIN_TOKEN = "test-admin-token-not-a-secret"
MONITORING_TOKEN = "test-monitoring-token-not-a-secret"
WORKLOAD_TOKEN = "test-workload-token-not-a-secret"
ENGINES = ("asgi", "sync")


def build_runtime(tmp_path) -> OrchestratorRuntime:
    return OrchestratorRuntime(
        CapabilityRegistry([worker("w1")]),
        {"w1": InMemoryAdapter("ok")},
        EvidenceStore(tmp_path / "evidence.jsonl"),
    )


def build_registry() -> ClientRegistry:
    registry = ClientRegistry.from_tokens([("admin-client", ADMIN_TOKEN)], scopes=("admin",))
    workload = ClientRegistry.from_tokens([("workload-client", WORKLOAD_TOKEN)], scopes=("workload",))
    return ClientRegistry(registry.clients() + workload.clients())


class Gateway:
    """One request interface over both engines."""

    def __init__(self, engine: str, tmp_path, *, listener: str = "any", local: bool = False) -> None:
        self.engine = engine
        runtime = build_runtime(tmp_path)
        kwargs = dict(
            clients=build_registry(), monitoring_token=MONITORING_TOKEN, require_monitoring_auth=True, listener=listener
        )
        if engine == "asgi":
            peer = ("127.0.0.1", 50000) if local else ("203.0.113.9", 50000)  # loopback vs a remote caller
            self.client = TestClient(create_asgi_gateway(runtime, **kwargs), client=peer)
        else:
            self.server = GatewayServer(("127.0.0.1", 0), create_gateway(runtime, **kwargs))
            threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def close(self) -> None:
        if self.engine == "sync":
            self.server.shutdown()
            self.server.server_close()

    def request(self, method: str, path: str, token: str | None = None) -> int:
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        if self.engine == "asgi":
            return self.client.request(method, path, headers=headers).status_code
        host, port = self.server.server_address
        connection = HTTPConnection(host, port)
        connection.request(method, path, headers=headers, body=b"{}" if method == "POST" else None)
        status = connection.getresponse().status
        connection.close()
        return status


@pytest.fixture(params=ENGINES)
def gateway(request, tmp_path):
    instance = Gateway(request.param, tmp_path)
    yield instance
    instance.close()


def test_monitoring_token_gets_no_admin_access(gateway):
    # /admin/workers exists on both engines; the monitoring token is not an admin client there either.
    assert gateway.request("GET", "/admin/workers", MONITORING_TOKEN) in (401, 403)
    assert gateway.request("GET", "/admin/workers", ADMIN_TOKEN) == 200
    if gateway.engine == "asgi":
        for method, path in (
            ("GET", "/v1/admin/status"),
            ("POST", "/v1/admin/reload"),
            ("GET", "/admin"),
            ("POST", "/v1/admin/workers/w1/recover"),
        ):
            assert gateway.request(method, path, MONITORING_TOKEN) in (401, 403), path
            assert gateway.request(method, path, WORKLOAD_TOKEN) in (401, 403), path
            assert gateway.request(method, path, ADMIN_TOKEN) == 200, path


def test_monitoring_token_still_serves_monitoring_routes(gateway):
    assert gateway.request("GET", "/health", MONITORING_TOKEN) in (200, 503)
    assert gateway.request("GET", "/health") == 401


def test_query_string_token_is_rejected(gateway):
    paths = ["/admin/workers"] + (["/admin", "/v1/admin/status"] if gateway.engine == "asgi" else [])
    for path in paths:
        for token in (ADMIN_TOKEN, MONITORING_TOKEN):
            assert gateway.request("GET", f"{path}?token={token}") == 401, path


@pytest.mark.parametrize("engine", ENGINES)
def test_admin_routes_refuse_local_origin_on_the_remote_listener(engine, tmp_path):
    gateway = Gateway(engine, tmp_path, listener="remote", local=True)
    try:
        assert gateway.request("GET", "/admin/workers", ADMIN_TOKEN) == 403
        if engine == "asgi":
            for method, path in (
                ("GET", "/v1/admin/status"),
                ("POST", "/v1/admin/reload"),
                ("GET", "/admin"),
                ("POST", "/v1/admin/workers/w1/recover"),
            ):
                assert gateway.request(method, path, ADMIN_TOKEN) == 403, path
    finally:
        gateway.close()


@pytest.mark.parametrize("engine", ENGINES)
def test_monitoring_token_is_compared_in_constant_time(engine, tmp_path):
    gateway = Gateway(engine, tmp_path)
    try:
        with mock.patch.object(hmac, "compare_digest", wraps=hmac.compare_digest) as compare:
            assert gateway.request("GET", "/health", MONITORING_TOKEN) in (200, 503)
            assert gateway.request("GET", "/health", "wrong-token") in (401, 403)
        expected = token_digest(MONITORING_TOKEN)
        assert any(call.args == (expected, expected) for call in compare.call_args_list)
    finally:
        gateway.close()


# ------------------------------------------------------------------ JWT
@pytest.fixture(scope="module")
def rsa_keys() -> tuple[str, str]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    private_pem = key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
    ).decode()
    public_pem = key.public_key().public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode()
    return private_pem, public_pem


def claims(**extra):
    return {"sub": "jwt-client", "scopes": ["workload"], "exp": time.time() + 600, **extra}


def test_jwt_default_algorithm_follows_the_configured_key(rsa_keys):
    _, public_pem = rsa_keys
    assert ClientRegistry([], jwt_public_key=public_pem).jwt_algorithms == ("RS256",)
    assert ClientRegistry([], jwt_secret="s" * 40).jwt_algorithms == ("HS256",)
    assert ClientRegistry([]).jwt_algorithms == ()


def test_jwt_rejects_configuring_both_a_public_key_and_a_secret(rsa_keys):
    with pytest.raises(ValueError):
        ClientRegistry([], jwt_public_key=rsa_keys[1], jwt_secret="s" * 40)


def test_jwt_rejects_algorithms_from_the_wrong_family(rsa_keys):
    with pytest.raises(ValueError):
        ClientRegistry([], jwt_public_key=rsa_keys[1], jwt_algorithms=("HS256",))
    with pytest.raises(ValueError):
        ClientRegistry([], jwt_secret="s" * 40, jwt_algorithms=("RS256",))
    with pytest.raises(ValueError):
        ClientRegistry([], jwt_secret="s" * 40, jwt_algorithms=("none",))


def test_hs256_token_signed_with_the_rsa_public_key_is_rejected(rsa_keys):
    _, public_pem = rsa_keys
    registry = ClientRegistry([], jwt_public_key=public_pem)
    # PyJWT refuses a PEM key as an HMAC secret, so forge the token by hand (the real attack).
    forged = _forge_hs256(public_pem)
    assert registry.authenticate(f"Bearer {forged}") is None


def _forge_hs256(secret: str) -> str:
    import base64
    import hashlib

    def b64(raw: bytes) -> str:
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()

    signing_input = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()) + "." + b64(json.dumps(claims()).encode())
    signature = hmac.new(secret.encode(), signing_input.encode(), hashlib.sha256).digest()
    return signing_input + "." + b64(signature)


def test_rs256_token_with_exp_is_accepted_and_without_exp_is_rejected(rsa_keys):
    private_pem, public_pem = rsa_keys
    registry = ClientRegistry([], jwt_public_key=public_pem)
    good = jwt.encode(claims(), private_pem, algorithm="RS256")
    assert registry.authenticate(f"Bearer {good}").client_id == "jwt-client"
    no_exp = {key: value for key, value in claims().items() if key != "exp"}
    assert registry.authenticate(f"Bearer {jwt.encode(no_exp, private_pem, algorithm='RS256')}") is None


def test_hs256_token_without_exp_is_rejected():
    secret = "s" * 40
    registry = ClientRegistry([], jwt_secret=secret)
    assert registry.authenticate(f"Bearer {jwt.encode(claims(), secret, algorithm='HS256')}") is not None
    no_exp = {key: value for key, value in claims().items() if key != "exp"}
    assert registry.authenticate(f"Bearer {jwt.encode(no_exp, secret, algorithm='HS256')}") is None


def test_jwt_decode_errors_other_than_pyjwt_errors_are_not_swallowed(rsa_keys):
    private_pem, public_pem = rsa_keys
    registry = ClientRegistry([], jwt_public_key=public_pem)
    good = jwt.encode(claims(), private_pem, algorithm="RS256")
    with mock.patch.object(jwt, "decode", side_effect=RuntimeError("boom")):
        with pytest.raises(RuntimeError):
            registry.authenticate(f"Bearer {good}")
