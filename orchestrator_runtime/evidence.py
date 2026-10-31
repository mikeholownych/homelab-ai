"""Tamper-evident evidence chain (R11) and the prompt data policy.

Each record carries the previous record's hash; the chain continues across gateway restarts (the last persisted hash is
read and the chain verified at start). A break is never repaired in place: it is evidenced and the chain continues from
an explicit link record. Every ANCHOR_EVERY records the chain head is written to the journal, which the gateway user
cannot rewrite, so editing the file is detectable even if the attacker recomputes every hash.

Data policy (default ``hash``): evidence never stores prompt text unless explicitly configured to.

    python3 -m orchestrator_runtime.evidence_cli verify <file>     # exit 0 when the chain is intact
"""
from __future__ import annotations

from collections import deque
from typing import Iterable

import hashlib
import json
import os
import re
import socket
import sys
import threading
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ANCHOR_EVERY = 100
ANCHOR_SECONDS = 300.0
PROMPT_POLICIES = ("hash", "redact", "store")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{24,}")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def record_hash(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "record_hash"}
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def verify_lines(lines: Iterable[str]) -> tuple[bool, int, str | None, list[str]]:
    """(intact, records, head_hash, problems). A link record (event=chain_break_detected) legitimately restarts linkage."""
    previous: str | None = None
    problems = deque(maxlen=50)
    count = 0
    for number, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
        except ValueError:
            problems.append(f"line {number}: not JSON")
            previous = None
            continue
        if not isinstance(record, dict):
            problems.append(f"line {number}: record must be an object")
            previous = None
            continue
        count += 1
        if record.get("record_hash") != record_hash(record):
            problems.append(f"line {number}: record_hash mismatch")
        if record.get("event") == "chain_genesis" and (count != 1 or record.get("previous_hash") is not None):
            problems.append(f"line {number}: chain_genesis is only valid as the first record")
        if count == 1 and record.get("previous_hash") is not None:
            problems.append(f"line {number}: first record must not link to a missing predecessor")
        if count > 1 and record.get("previous_hash") != previous:
            problems.append(f"line {number}: previous_hash does not link to line before")
        previous = record.get("record_hash")
    return not problems, count, previous, list(problems)


def file_digest(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def verify_file(path: Path) -> tuple[bool, int, str | None, list[str]]:
    """Verify current and sealed predecessors with a bounded working set per segment."""
    current = path
    total, final_head = 0, None
    problems = deque(maxlen=50)
    visited = set()
    while current not in visited:
        visited.add(current)
        with current.open(encoding="utf-8") as stream:
            first_line = stream.readline()
            try:
                first = json.loads(first_line) if first_line.strip() else {}
            except ValueError:
                first = {}
            stream.seek(0)
            intact, count, head, faults = verify_lines(stream)
        if final_head is None:
            final_head = head
        total += count
        problems.extend(faults)
        previous = first.get("sealed_predecessor") if isinstance(first, dict) else None
        if not previous:
            return not problems, total, final_head, list(problems)
        name = previous.get("file", "")
        if not name or Path(name).name != name:
            problems.append("invalid sealed predecessor path")
            break
        predecessor = current.parent / name
        if not predecessor.is_file() or file_digest(predecessor) != previous.get("sha256"):
            problems.append("sealed predecessor missing or digest mismatch")
            break
        current = predecessor
    else:
        problems.append("sealed predecessor cycle")
    return False, total, final_head, list(problems)


def scrub(text: str, policy: str) -> str:
    """Apply the data policy to free text that may echo prompt content (e.g. a provider error body)."""
    if policy == "store":
        return text
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    if policy == "redact":
        return _LONG_TOKEN.sub("<redacted>", text[:120]) + f" [sha256:{digest}]"
    return f"[sha256:{digest} len:{len(text)}]"


class SyslogEvidenceStreamer:
    """Streams evidence records to a stream/file/socket in RFC 5424 structured syslog format."""

    def __init__(
        self,
        stream: Any = None,
        app_name: str = "aihost-gateway",
        facility: int = 16,
        *,
        host: str | None = None,
        port: int = 514,
        protocol: str = "udp",
    ) -> None:
        self.stream = stream if stream is not None else sys.stderr
        self.app_name = app_name
        self.facility = facility  # local0 by default
        self.host = host
        self.port = port
        self.protocol = protocol.lower()
        self._sock: socket.socket | None = None
        self._sock_lock = threading.Lock()

    @classmethod
    def from_env(cls) -> "SyslogEvidenceStreamer" | None:
        host = os.environ.get("ORCHESTRATOR_SYSLOG_HOST")
        if not host:
            if os.environ.get("ORCHESTRATOR_SYSLOG_ENABLED") == "true":
                return cls()
            return None
        port = int(os.environ.get("ORCHESTRATOR_SYSLOG_PORT", "514"))
        protocol = os.environ.get("ORCHESTRATOR_SYSLOG_PROTOCOL", "udp")
        app_name = os.environ.get("ORCHESTRATOR_SYSLOG_APP_NAME", "aihost-gateway")
        facility = int(os.environ.get("ORCHESTRATOR_SYSLOG_FACILITY", "16"))
        return cls(host=host, port=port, protocol=protocol, app_name=app_name, facility=facility)

    def _send_network(self, data: bytes) -> None:
        with self._sock_lock:
            try:
                if self.protocol == "tcp":
                    if self._sock is None:
                        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                        sock.settimeout(2.0)
                        sock.connect((self.host, self.port))
                        self._sock = sock
                    self._sock.sendall(data)
                else:
                    if self._sock is None:
                        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
                    self._sock.sendto(data, (self.host, self.port))
            except Exception:
                if self._sock:
                    try:
                        self._sock.close()
                    except Exception:
                        pass
                self._sock = None

    def __call__(self, record: dict[str, Any]) -> None:
        severity = 4 if ("failed" in record.get("event", "") or "rejected" in record.get("event", "")) else 6
        pri = (self.facility * 8) + severity
        ts = record.get("recorded_at") or datetime.now(timezone.utc).isoformat()
        event_name = record.get("event", "event")
        payload = canonical(record)
        msg = f"<{pri}>1 {ts} - {self.app_name} - {event_name} - {payload}\n"
        if self.host:
            self._send_network(msg.encode("utf-8"))
        else:
            try:
                self.stream.write(msg)
                self.stream.flush()
            except Exception:
                pass

    def close(self) -> None:
        with self._sock_lock:
            if self._sock:
                try:
                    self._sock.close()
                except Exception:
                    pass
                self._sock = None


class EvidenceStore:
    def __init__(self, path: str | Path | None = None, *, anchor_stream=None) -> None:
        self.path = Path(path) if path else None
        self._records = deque(maxlen=max(1, int(os.environ.get("ORCHESTRATOR_EVIDENCE_RING_SIZE", "1024"))))
        self._streamers: list[Callable[[dict[str, Any]], None]] = []
        self._lock = threading.Lock()
        self._anchor_stream = anchor_stream if anchor_stream is not None else sys.stderr
        self._head: str | None = None
        self._since_anchor = 0
        self._anchored_at = time.monotonic()
        self.chain_valid = True
        self.chain_problems: list[str] = []
        env_streamer = SyslogEvidenceStreamer.from_env()
        if env_streamer:
            self.add_streamer(env_streamer)
        if self.path and self.path.exists():
            self._resume()

    def add_streamer(self, streamer: Callable[[dict[str, Any]], None]) -> None:
        """Register an external streamer (e.g. SyslogEvidenceStreamer or SIEM forwarder)."""
        with self._lock:
            self._streamers.append(streamer)

    def genesis(self, **fields: Any) -> str:
        """Start a new chain explicitly (e.g. after sealing a legacy file); only valid on an empty store."""
        with self._lock:
            if self._head is not None:
                raise ValueError("chain_genesis is only valid at the start of an empty chain")
        return self.append("chain_genesis", **fields)

    def _resume(self) -> None:
        try:
            intact, count, head, problems = verify_file(self.path)
        except OSError as error:
            # Never append with a fresh head when an existing chain cannot be read. That would create a
            # disconnected suffix while making the gateway look healthy.
            raise OSError(f"cannot read existing evidence chain at {self.path}") from error
        self._head = head
        self.chain_valid = intact
        self.chain_problems = problems[:20]
        if not intact:
            self.append("chain_break_detected", problems=problems[:20], records=count, resumed_from=head)
        else:
            self._emit_anchor(count)

    def _emit_anchor(self, count: int) -> None:
        try:
            self._anchor_stream.write(f"evidence_anchor head={self._head} records={count} "
                                      f"at={datetime.now(timezone.utc).isoformat()}\n")
            self._anchor_stream.flush()
        except (OSError, ValueError):
            pass
        self._since_anchor = 0
        self._anchored_at = time.monotonic()

    def _rotate_if_needed(self) -> None:
        limit = max(1024, int(os.environ.get("ORCHESTRATOR_EVIDENCE_SEGMENT_BYTES", str(64 * 1024 * 1024))))
        if not self.path or not self._head or not self.path.exists() or self.path.stat().st_size < limit:
            return
        sealed = self.path.with_name(self.path.name + ".sealed-" + self._head)
        with self.path.open("rb") as previous:
            os.fsync(previous.fileno())
        digest = file_digest(self.path)
        if sealed.exists():
            if file_digest(sealed) != digest:
                raise OSError("sealed evidence identity collision")
        else:
            # Link the existing inode before atomic replacement: interruption never loses the active chain.
            os.link(self.path, sealed)
        genesis = {"evidence_id": str(uuid.uuid4()), "event": "chain_genesis",
                   "recorded_at": datetime.now(timezone.utc).isoformat(), "previous_hash": None,
                   "sealed_predecessor": {"file": sealed.name, "sha256": digest, "head": self._head}}
        genesis["record_hash"] = record_hash(genesis)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=self.path.parent,
                                             prefix=".evidence-", delete=False) as stream:
                temporary = Path(stream.name)
                os.chmod(temporary, self.path.stat().st_mode & 0o777)
                stream.write(canonical(genesis) + "\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            descriptor = os.open(self.path.parent, os.O_RDONLY | os.O_DIRECTORY)
            try:
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
        self._head = genesis["record_hash"]
        self._records.append(genesis)
        self._emit_anchor(1)

    def append(self, event: str, **fields: Any) -> str:
        with self._lock:
            self._rotate_if_needed()
            record = {
                "evidence_id": str(uuid.uuid4()),
                "event": event,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
                "previous_hash": self._head,
                **fields,
            }
            record["record_hash"] = record_hash(record)
            self._records.append(record)
            self._head = record["record_hash"]
            if self.path:
                self.path.parent.mkdir(parents=True, exist_ok=True)
                with self.path.open("a", encoding="utf-8") as stream:
                    stream.write(canonical(record) + "\n")
            for streamer in self._streamers:
                try:
                    streamer(record)
                except Exception:
                    pass
            self._since_anchor += 1
            if self._since_anchor >= ANCHOR_EVERY or time.monotonic() - self._anchored_at >= ANCHOR_SECONDS:
                self._emit_anchor(self._since_anchor)
            return record["evidence_id"]

    @property
    def head(self) -> str | None:
        with self._lock:
            return self._head

    def records(self) -> list[dict[str, Any]]:
        with self._lock:
            return [record.copy() for record in self._records]


def _main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[0] != "verify":
        print("usage: python3 -m orchestrator_runtime.evidence_cli verify <file>", file=sys.stderr)
        return 2
    intact, count, head, problems = verify_file(Path(argv[1]))
    print(json.dumps({"intact": intact, "records": count, "head": head, "problems": problems[:50]}, indent=1))
    return 0 if intact else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
