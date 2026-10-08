#!/usr/bin/env python3
"""Create a private gateway CA and a correctly constrained TLS server leaf."""

from __future__ import annotations

import argparse
import os
import pathlib
import subprocess
import tempfile


def run(*argv: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(argv, check=check, text=True, capture_output=True)


def output(*argv: str) -> str:
    return run(*argv).stdout.strip()


def key_matches(cert: pathlib.Path, key: pathlib.Path) -> bool:
    cert_pub = output("openssl", "x509", "-in", str(cert), "-pubkey", "-noout")
    key_pub = output("openssl", "pkey", "-in", str(key), "-pubout")
    return cert_pub == key_pub


def valid_ca(cert: pathlib.Path, key: pathlib.Path) -> bool:
    if not cert.is_file() or not key.is_file() or not key_matches(cert, key):
        return False
    constraints = output("openssl", "x509", "-in", str(cert), "-noout", "-ext", "basicConstraints")
    usage = output("openssl", "x509", "-in", str(cert), "-noout", "-ext", "keyUsage")
    return "CA:TRUE" in constraints and "Certificate Sign" in usage


def valid_leaf(
    cert: pathlib.Path,
    key: pathlib.Path,
    ca_cert: pathlib.Path,
    sans: list[str],
) -> bool:
    if not cert.is_file() or not key.is_file() or not key_matches(cert, key):
        return False
    verify = ["openssl", "verify", "-CAfile", str(ca_cert), "-purpose", "sslserver"]
    for san in sans:
        kind, value = san.split(":", 1)
        verify.extend(["-verify_ip" if kind == "IP" else "-verify_hostname", value])
    verify.append(str(cert))
    if run(*verify, check=False).returncode != 0:
        return False
    if run("openssl", "x509", "-in", str(cert), "-noout", "-checkend", "2592000", check=False).returncode:
        return False
    constraints = output("openssl", "x509", "-in", str(cert), "-noout", "-ext", "basicConstraints")
    usage = output("openssl", "x509", "-in", str(cert), "-noout", "-ext", "keyUsage")
    extended = output("openssl", "x509", "-in", str(cert), "-noout", "-ext", "extendedKeyUsage")
    actual_sans = output("openssl", "x509", "-in", str(cert), "-noout", "-ext", "subjectAltName")
    return (
        "CA:FALSE" in constraints
        and "Digital Signature" in usage
        and "TLS Web Server Authentication" in extended
        and all(value in actual_sans for value in (san.split(":", 1)[1] for san in sans))
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pki-dir", type=pathlib.Path, required=True)
    parser.add_argument("--ca-key", type=pathlib.Path, required=True)
    parser.add_argument("--ca-cert", type=pathlib.Path, required=True)
    parser.add_argument("--server-key", type=pathlib.Path, required=True)
    parser.add_argument("--server-cert", type=pathlib.Path, required=True)
    parser.add_argument("--subject", required=True)
    parser.add_argument("--sans", required=True, help="comma-separated OpenSSL SAN entries")
    parser.add_argument("--rotate-server", action="store_true")
    args = parser.parse_args()
    args.san = args.sans.split(",")

    for san in args.san:
        if ":" not in san or san.split(":", 1)[0] not in {"IP", "DNS"}:
            parser.error(f"unsupported SAN form: {san!r}")
    args.pki_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(args.pki_dir, 0o700)
    for path in (args.ca_key, args.ca_cert, args.server_key, args.server_cert):
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)

    changed = False
    if not args.ca_key.exists():
        run("openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(args.ca_key))
        os.chmod(args.ca_key, 0o600)
        changed = True
    elif args.ca_key.stat().st_mode & 0o077:
        os.chmod(args.ca_key, 0o600)

    if not args.ca_cert.exists():
        run(
            "openssl", "req", "-new", "-x509", "-sha256", "-days", "3650", "-key", str(args.ca_key),
            "-out", str(args.ca_cert), "-subj", "/CN=AIHost T5820 Gateway Root CA",
            "-addext", "basicConstraints=critical,CA:TRUE,pathlen:0",
            "-addext", "keyUsage=critical,keyCertSign,cRLSign",
            "-addext", "subjectKeyIdentifier=hash",
        )
        os.chmod(args.ca_cert, 0o644)
        changed = True
    if not valid_ca(args.ca_cert, args.ca_key):
        raise SystemExit("configured gateway CA certificate/key is invalid or not a signing CA")

    rotate = args.rotate_server or not valid_leaf(args.server_cert, args.server_key, args.ca_cert, args.san)
    if rotate:
        with tempfile.TemporaryDirectory(prefix="aihost-gateway-pki-", dir=args.pki_dir) as tmp:
            tmpdir = pathlib.Path(tmp)
            new_key = tmpdir / "server.key"
            csr = tmpdir / "server.csr"
            new_cert = tmpdir / "server.crt"
            extensions = tmpdir / "server-extensions.cnf"
            run("openssl", "genpkey", "-algorithm", "RSA", "-pkeyopt", "rsa_keygen_bits:3072", "-out", str(new_key))
            san_text = ",".join(args.san)
            run(
                "openssl", "req", "-new", "-sha256", "-key", str(new_key), "-out", str(csr),
                "-subj", f"/CN={args.subject}", "-addext", f"subjectAltName={san_text}",
            )
            extensions.write_text(
                "[server_cert]\n"
                "basicConstraints=critical,CA:FALSE\n"
                "keyUsage=critical,digitalSignature,keyEncipherment\n"
                "extendedKeyUsage=serverAuth\n"
                f"subjectAltName={san_text}\n"
                "subjectKeyIdentifier=hash\n"
                "authorityKeyIdentifier=keyid,issuer\n",
                encoding="ascii",
            )
            os.chmod(extensions, 0o600)
            serial = args.ca_cert.with_suffix(".srl")
            serial_args = ["-CAserial", str(serial)] if serial.exists() else ["-CAcreateserial"]
            run(
                "openssl", "x509", "-req", "-sha256", "-days", "825", "-in", str(csr),
                "-CA", str(args.ca_cert), "-CAkey", str(args.ca_key), *serial_args,
                "-extfile", str(extensions), "-extensions", "server_cert", "-out", str(new_cert),
            )
            os.replace(new_key, args.server_key)
            os.replace(new_cert, args.server_cert)
        os.chmod(args.server_key, 0o600)
        os.chmod(args.server_cert, 0o644)
        if not valid_leaf(args.server_cert, args.server_key, args.ca_cert, args.san):
            raise SystemExit("generated gateway server certificate failed chain, SAN, EKU or key validation")
        changed = True

    ca_fp = output("openssl", "x509", "-in", str(args.ca_cert), "-noout", "-fingerprint", "-sha256")
    leaf_fp = output("openssl", "x509", "-in", str(args.server_cert), "-noout", "-fingerprint", "-sha256")
    print(f"PKI_CHANGED={int(changed)}")
    print(ca_fp)
    print(leaf_fp)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
