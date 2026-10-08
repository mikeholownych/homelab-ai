from __future__ import annotations

import pathlib
import subprocess
import sys


SCRIPT = pathlib.Path("roles/orchestrator_gateway/files/generate-gateway-pki.py")


def _generate(tmp_path: pathlib.Path, *, rotate: bool = False) -> subprocess.CompletedProcess[str]:
    pki = tmp_path / "private"
    args = [
        sys.executable,
        str(SCRIPT),
        "--pki-dir", str(pki),
        "--ca-key", str(pki / "ca.key"),
        "--ca-cert", str(pki / "ca.crt"),
        "--server-key", str(pki / "server.key"),
        "--server-cert", str(pki / "server.crt"),
        "--subject", "ai-5820-01",
        "--sans", "IP:10.0.8.5,DNS:ai-5820-01",
    ]
    if rotate:
        args.append("--rotate-server")
    return subprocess.run(args, check=True, text=True, capture_output=True)


def _openssl(*args: str) -> str:
    return subprocess.run(["openssl", *args], check=True, text=True, capture_output=True).stdout


def test_gateway_pki_creates_private_ca_and_constrained_leaf(tmp_path):
    result = _generate(tmp_path)
    pki = tmp_path / "private"
    ca_key, ca_cert = pki / "ca.key", pki / "ca.crt"
    leaf_key, leaf_cert = pki / "server.key", pki / "server.crt"

    assert "PKI_CHANGED=1" in result.stdout
    assert (pki.stat().st_mode & 0o777) == 0o700
    assert (ca_key.stat().st_mode & 0o777) == 0o600
    assert (leaf_key.stat().st_mode & 0o777) == 0o600
    assert "CA:TRUE" in _openssl("x509", "-in", str(ca_cert), "-noout", "-ext", "basicConstraints")
    assert "Certificate Sign" in _openssl("x509", "-in", str(ca_cert), "-noout", "-ext", "keyUsage")
    assert "CA:FALSE" in _openssl("x509", "-in", str(leaf_cert), "-noout", "-ext", "basicConstraints")
    assert "TLS Web Server Authentication" in _openssl("x509", "-in", str(leaf_cert), "-noout", "-ext", "extendedKeyUsage")
    assert "10.0.8.5" in _openssl("x509", "-in", str(leaf_cert), "-noout", "-ext", "subjectAltName")
    assert "ai-5820-01" in _openssl("x509", "-in", str(leaf_cert), "-noout", "-ext", "subjectAltName")
    assert "server.crt: OK" in _openssl(
        "verify", "-CAfile", str(ca_cert), "-purpose", "sslserver",
        "-verify_ip", "10.0.8.5", "-verify_hostname", "ai-5820-01", str(leaf_cert),
    )


def test_gateway_server_leaf_rotation_keeps_ca_trust_anchor(tmp_path):
    first = _generate(tmp_path)
    pki = tmp_path / "private"
    leaf_cert = pki / "server.crt"
    old_fingerprint = _openssl("x509", "-in", str(leaf_cert), "-noout", "-fingerprint", "-sha256")
    ca_fingerprint = _openssl("x509", "-in", str(pki / "ca.crt"), "-noout", "-fingerprint", "-sha256")

    rotated = _generate(tmp_path, rotate=True)

    new_fingerprint = _openssl("x509", "-in", str(leaf_cert), "-noout", "-fingerprint", "-sha256")
    assert "PKI_CHANGED=1" in first.stdout and "PKI_CHANGED=1" in rotated.stdout
    assert old_fingerprint != new_fingerprint
    assert ca_fingerprint == _openssl("x509", "-in", str(pki / "ca.crt"), "-noout", "-fingerprint", "-sha256")
    assert "server.crt: OK" in _openssl("verify", "-CAfile", str(pki / "ca.crt"), str(leaf_cert))


def test_gateway_pki_is_idempotent_without_rotation(tmp_path):
    _generate(tmp_path)
    result = _generate(tmp_path)
    assert "PKI_CHANGED=0" in result.stdout
