"""Tamper-evident evidence chain (R11) and the prompt data policy.

Each record carries the previous record's hash; the chain continues across gateway restarts (the last persisted hash is
read and the chain verified at start). A break is never repaired in place: it is evidenced and the chain continues from
an explicit link record. Every ANCHOR_EVERY records the chain head is written to the journal, which the gateway user
cannot rewrite, so editing the file is detectable even if the attacker recomputes every hash.

Data policy (default ``hash``): evidence never stores prompt text unless explicitly configured to.

    python3 -m orchestrator_runtime.evidence verify <file>     # exit 0 when the chain is intact
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ANCHOR_EVERY = 100
ANCHOR_SECONDS = 300.0
PROMPT_POLICIES = ("hash", "redact", "store")
_LONG_TOKEN = re.compile(r"[A-Za-z0-9+/=_\-]{24,}")


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def record_hash(record: dict[str, Any]) -> str:
    body = {k: v for k, v in record.items() if k != "record_hash"}
    return hashlib.sha256(canonical(body).encode()).hexdigest()


def verify_lines(lines: list[str]) -> tuple[bool, int, str | None, list[str]]:
    """(intact, records, head_hash, problems). A link record (event=chain_break_detected) legitimately restarts linkage."""
    previous: str | None = None
    problems: list[str] = []
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
    return not problems, count, previous, problems


def scrub(text: str, policy: str) -> str:
    """Apply the data policy to free text that may echo prompt content (e.g. a provider error body)."""
    if policy == "store":
        return text
    digest = hashlib.sha256(text.encode()).hexdigest()[:16]
    if policy == "redact":
        return _LONG_TOKEN.sub("<redacted>", text[:120]) + f" [sha256:{digest}]"
    return f"[sha256:{digest} len:{len(text)}]"


class EvidenceStore:
    def __init__(self, path: str | Path | None = None, *, anchor_stream=None) -> None:
        self.path = Path(path) if path else None
        self._records: list[dict[str, Any]] = []
        self._lock = threading.Lock()
        self._anchor_stream = anchor_stream if anchor_stream is not None else sys.stderr
        self._head: str | None = None
        self._since_anchor = 0
        self._anchored_at = time.monotonic()
        self.chain_valid = True
        self.chain_problems: list[str] = []
        if self.path and self.path.exists():
            self._resume()

    def genesis(self, **fields: Any) -> str:
        """Start a new chain explicitly (e.g. after sealing a legacy file); only valid on an empty store."""
        with self._lock:
            if self._head is not None:
                raise ValueError("chain_genesis is only valid at the start of an empty chain")
        return self.append("chain_genesis", **fields)

    def _resume(self) -> None:
        try:
            lines = self.path.read_text(encoding="utf-8").splitlines()
        except OSError as error:
            # Never append with a fresh head when an existing chain cannot be read. That would create a
            # disconnected suffix while making the gateway look healthy.
            raise OSError(f"cannot read existing evidence chain at {self.path}") from error
        intact, count, head, problems = verify_lines(lines)
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

    def append(self, event: str, **fields: Any) -> str:
        with self._lock:
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
        print("usage: python3 -m orchestrator_runtime.evidence verify <file>", file=sys.stderr)
        return 2
    intact, count, head, problems = verify_lines(Path(argv[1]).read_text(encoding="utf-8").splitlines())
    print(json.dumps({"intact": intact, "records": count, "head": head, "problems": problems[:50]}, indent=1))
    return 0 if intact else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv[1:]))
