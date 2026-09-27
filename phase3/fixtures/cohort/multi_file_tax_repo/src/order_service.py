"""Order processing and total service."""
from typing import Any
from src.tax_calculator import calculate_sales_tax


def compute_order_total(items: list[dict[str, Any]], state: str) -> dict[str, float]:
    """Calculates order subtotal, sales tax, and final total."""
    subtotal = sum(float(item["price"]) * int(item.get("quantity", 1)) for item in items)
    tax = calculate_sales_tax(subtotal, state)
    return {
        "subtotal": round(subtotal, 2),
        "tax": tax,
        "total": round(subtotal + tax, 2),
    }
