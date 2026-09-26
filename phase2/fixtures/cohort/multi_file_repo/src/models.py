"""Order processing data models."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Item:
    name: str
    price: float
    quantity: int


@dataclass(frozen=True)
class Order:
    order_id: str
    items: list[Item]
    discount_code: str | None = None
