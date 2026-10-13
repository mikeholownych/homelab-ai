"""Tests for RFC 5424 Syslog evidence streaming and network transports."""
from __future__ import annotations

import io
import os
import socket
import threading
import time
from unittest import mock

import pytest

from orchestrator_runtime.evidence import EvidenceStore, SyslogEvidenceStreamer


def test_syslog_streamer_io_stream():
    buf = io.StringIO()
    streamer = SyslogEvidenceStreamer(stream=buf, app_name="test-gateway", facility=16)

    record = {
        "event": "request_admitted",
        "client_id": "nexus",
        "model": "qwen2.5",
        "recorded_at": "2026-10-13T12:00:00Z",
    }
    streamer(record)

    output = buf.getvalue()
    assert output.startswith("<134>1 2026-10-13T12:00:00Z - test-gateway - request_admitted - ")
    assert "client_id" in output
    assert "nexus" in output


def test_syslog_streamer_severity_mapping():
    buf = io.StringIO()
    streamer = SyslogEvidenceStreamer(stream=buf, facility=16)

    # Info event -> severity 6 -> (16*8)+6 = 134
    streamer({"event": "request_admitted"})
    assert buf.getvalue().startswith("<134>1 ")

    # Error event -> severity 4 -> (16*8)+4 = 132
    buf.seek(0)
    buf.truncate(0)
    streamer({"event": "routing_rejected", "failure_class": "scope"})
    assert buf.getvalue().startswith("<132>1 ")


def test_syslog_streamer_udp_transport():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    server_sock.bind(("127.0.0.1", 0))
    port = server_sock.getsockname()[1]

    received = []

    def udp_listener():
        server_sock.settimeout(2.0)
        try:
            data, _ = server_sock.recvfrom(4096)
            received.append(data.decode("utf-8"))
        except TimeoutError:
            pass
        finally:
            server_sock.close()

    listener_thread = threading.Thread(target=udp_listener, daemon=True)
    listener_thread.start()

    streamer = SyslogEvidenceStreamer(host="127.0.0.1", port=port, protocol="udp", app_name="aihost-udp")
    streamer({"event": "udp_test_event", "status": "ok"})
    streamer.close()

    listener_thread.join(timeout=3.0)
    assert len(received) == 1
    assert "udp_test_event" in received[0]
    assert "aihost-udp" in received[0]


def test_syslog_streamer_tcp_transport():
    server_sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server_sock.bind(("127.0.0.1", 0))
    server_sock.listen(1)
    port = server_sock.getsockname()[1]

    received = []

    def tcp_listener():
        server_sock.settimeout(2.0)
        try:
            client_conn, _ = server_sock.accept()
            client_conn.settimeout(2.0)
            data = client_conn.recv(4096)
            received.append(data.decode("utf-8"))
            client_conn.close()
        except TimeoutError:
            pass
        finally:
            server_sock.close()

    listener_thread = threading.Thread(target=tcp_listener, daemon=True)
    listener_thread.start()

    streamer = SyslogEvidenceStreamer(host="127.0.0.1", port=port, protocol="tcp", app_name="aihost-tcp")
    streamer({"event": "tcp_test_event", "status": "ok"})
    streamer.close()

    listener_thread.join(timeout=3.0)
    assert len(received) == 1
    assert "tcp_test_event" in received[0]
    assert "aihost-tcp" in received[0]


def test_syslog_streamer_from_env_and_evidence_store_integration(tmp_path):
    env = {
        "ORCHESTRATOR_SYSLOG_HOST": "127.0.0.1",
        "ORCHESTRATOR_SYSLOG_PORT": "5140",
        "ORCHESTRATOR_SYSLOG_PROTOCOL": "udp",
        "ORCHESTRATOR_SYSLOG_APP_NAME": "gateway-env-test",
    }
    with mock.patch.dict(os.environ, env):
        streamer = SyslogEvidenceStreamer.from_env()
        assert streamer is not None
        assert streamer.host == "127.0.0.1"
        assert streamer.port == 5140
        assert streamer.protocol == "udp"
        assert streamer.app_name == "gateway-env-test"

        # EvidenceStore auto-registers streamer from env
        store = EvidenceStore(tmp_path / "evidence.jsonl")
        assert len(store._streamers) >= 1
