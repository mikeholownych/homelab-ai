"""Tax calculator module."""


def calculate_sales_tax(amount: float, state: str) -> float:
    """Calculates state sales tax on a given dollar amount.

    Rates:
    - CA: 8.25% (0.0825)
    - NY: 8.00% (0.08)
    - TX: 6.25% (0.0625)
    - All other states: 5.00% (0.05)

    Requirements:
    - If amount < 0: raise ValueError("amount must be non-negative")
    - Return tax rounded to 2 decimal places.
    """
    # Skeleton placeholder - unhandled rates and missing negative validation
    if amount < 0:
        raise ValueError("amount must be non-negative")
    return round(amount * 0.05, 2)
