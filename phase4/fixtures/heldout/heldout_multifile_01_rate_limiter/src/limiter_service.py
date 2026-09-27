"""Rate Limiter Service managing per-client buckets."""
from typing import Dict
from src.token_bucket import TokenBucket

class RateLimiterService:
    def __init__(self, default_capacity: float = 10.0, default_refill_rate: float = 2.0) -> None:
        self.default_capacity = default_capacity
        self.default_refill_rate = default_refill_rate
        self.buckets: Dict[str, TokenBucket] = {}

    def allow_request(self, client_id: str, cost: float = 1.0, current_time: float | None = None) -> bool:
        if client_id not in self.buckets:
            self.buckets[client_id] = TokenBucket.create(
                self.default_capacity, self.default_refill_rate
            )
        return self.buckets[client_id].consume(cost, current_time)

    def get_remaining_tokens(self, client_id: str) -> float:
        if client_id not in self.buckets:
            return self.default_capacity
        return self.buckets[client_id].tokens
