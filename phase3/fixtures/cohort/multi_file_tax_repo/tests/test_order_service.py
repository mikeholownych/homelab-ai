import pytest
from src.order_service import compute_order_total
from src.tax_calculator import calculate_sales_tax


def test_calculate_sales_tax_states():
    assert calculate_sales_tax(100.0, "CA") == 8.25
    assert calculate_sales_tax(100.0, "NY") == 8.00
    assert calculate_sales_tax(100.0, "TX") == 6.25
    assert calculate_sales_tax(100.0, "FL") == 5.00


def test_calculate_sales_tax_negative():
    with pytest.raises(ValueError, match="amount must be non-negative"):
        calculate_sales_tax(-10.0, "CA")


def test_compute_order_total():
    items = [
        {"name": "Widget A", "price": 10.0, "quantity": 2},
        {"name": "Widget B", "price": 30.0, "quantity": 1},
    ]
    res = compute_order_total(items, "CA")
    assert res["subtotal"] == 50.0
    assert res["tax"] == 4.12  # 50 * 0.0825 = 4.125 -> 4.12 or round
    assert res["total"] == round(res["subtotal"] + res["tax"], 2)
