"""Token Bucket Rate Limiter Implementation."""
import time
from dataclasses import dataclass

@dataclass
class TokenBucket:
    capacity: float
    refill_rate: float  # tokens per second
    tokens: float
    last_update: float

    @classmethod
    def create(cls, capacity: float, refill_rate: float) -> "TokenBucket":
        return cls(
            capacity=capacity,
            refill_rate=refill_rate,
            tokens=capacity,
            last_update=time.time(),
        )

    def consume(self, amount: float = 1.0, current_time: float | None = None) -> bool:
        """Consumes tokens from the bucket if available."""
        now = current_time if current_time is not None else time.time()
        elapsed = max(0.0, now - self.last_update)
        self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
        self.last_update = now

        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False
