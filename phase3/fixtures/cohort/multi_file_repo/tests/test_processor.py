"""Test suite for order processing and discounts."""
import pytest
from src.models import Item, Order
from src.processor import process_order_total


def test_order_without_discount():
    items = [Item("Widget", 10.0, 2), Item("Gadget", 20.0, 1)]  # subtotal = 40.0
    order = Order("ord-1", items, discount_code=None)
    # total = 40.0 * 1.05 = 42.0
    assert process_order_total(order, tax_rate=0.05) == 42.0


def test_order_with_save10_discount():
    items = [Item("Widget", 100.0, 1)]  # subtotal = 100.0, discount = 10.0
    order = Order("ord-2", items, discount_code="SAVE10")
    # discounted = 90.0, total = 90.0 * 1.05 = 94.5
    # Defect causes discounted = 110.0, total = 115.5!
    assert process_order_total(order, tax_rate=0.05) == 94.5


def test_order_with_save20_discount():
    items = [Item("Widget", 50.0, 2)]  # subtotal = 100.0, discount = 20.0
    order = Order("ord-3", items, discount_code="SAVE20")
    # discounted = 80.0, total = 80.0 * 1.05 = 84.0
    assert process_order_total(order, tax_rate=0.05) == 84.0
