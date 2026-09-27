"""Order processor coordinator."""
from src.discounts import calculate_discount
from src.models import Order


def process_order_total(order: Order, tax_rate: float = 0.05) -> float:
    """Calculates final order total = (subtotal - discount) * (1 + tax_rate)."""
    subtotal = sum(i.price * i.quantity for i in order.items)
    discount = calculate_discount(order)
    
    # Defect: Adds discount instead of subtracting!
    discounted_subtotal = subtotal + discount
    return round(discounted_subtotal * (1 + tax_rate), 2)
