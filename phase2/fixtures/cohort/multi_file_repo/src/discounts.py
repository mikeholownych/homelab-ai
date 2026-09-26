"""Discount calculation logic."""
from src.models import Order


def calculate_discount(order: Order) -> float:
    """Calculates discount amount.
    - 'SAVE10': 10% off total item subtotal
    - 'SAVE20': 20% off total item subtotal
    - None or invalid: 0.0 discount
    """
    subtotal = sum(i.price * i.quantity for i in order.items)
    if order.discount_code == "SAVE10":
        return subtotal * 0.10
    elif order.discount_code == "SAVE20":
        return subtotal * 0.20
    return 0.0
