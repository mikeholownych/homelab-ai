import pytest
from src.limiter_service import RateLimiterService

def test_rate_limiter_burst_and_refill():
    service = RateLimiterService(default_capacity=5.0, default_refill_rate=1.0)
    client = "client-alpha"
    t0 = 1000.0

    # Consume 5 tokens immediately
    for _ in range(5):
        assert service.allow_request(client, cost=1.0, current_time=t0) is True

    # 6th request should fail
    assert service.allow_request(client, cost=1.0, current_time=t0) is False

    # After 2 seconds, 2 tokens refilled
    t1 = t0 + 2.0
    assert service.allow_request(client, cost=2.0, current_time=t1) is True
    assert service.allow_request(client, cost=1.0, current_time=t1) is False

def test_rate_limiter_independent_clients():
    service = RateLimiterService(default_capacity=3.0, default_refill_rate=1.0)
    t0 = 1000.0
    for _ in range(3):
        assert service.allow_request("client-1", cost=1.0, current_time=t0) is True
    assert service.allow_request("client-1", cost=1.0, current_time=t0) is False

    # Client-2 should be unaffected
    assert service.allow_request("client-2", cost=1.0, current_time=t0) is True
