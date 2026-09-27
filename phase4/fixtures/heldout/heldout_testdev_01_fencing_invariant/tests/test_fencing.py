import pytest
from src.fencing_token import FencingManager, FencingToken

def test_fencing_monotonic_increment():
    mgr = FencingManager()
    t1 = mgr.acquire_fence("res-1", "worker-A")
    t2 = mgr.acquire_fence("res-1", "worker-B")
    assert t1.token_number == 1
    assert t2.token_number == 2
    assert mgr.validate_fence(t2) is True
    # Stale token must be rejected
    assert mgr.validate_fence(t1) is False

def test_fencing_independent_resources():
    mgr = FencingManager()
    t_a = mgr.acquire_fence("res-A", "worker-1")
    t_b = mgr.acquire_fence("res-B", "worker-2")
    assert t_a.token_number == 1
    assert t_b.token_number == 1
    assert mgr.validate_fence(t_a) is True
    assert mgr.validate_fence(t_b) is True
