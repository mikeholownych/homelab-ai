from __future__ import annotations

from tools.t5820_dual_worker_preflight import check_memory


def test_preflight_enforces_operational_reserve():
    assert check_memory(33 * 1024**3, 32 * 1024**3)[0] is True
    assert check_memory(31 * 1024**3, 32 * 1024**3)[0] is False
