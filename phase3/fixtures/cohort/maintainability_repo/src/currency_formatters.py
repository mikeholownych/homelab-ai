"""Currency formatting utilities with duplicate boilerplate."""


def format_usd(amount: float) -> str:
    """Format amount as USD."""
    if not isinstance(amount, (int, float)):
        raise TypeError("amount must be a numeric value")
    if amount < 0:
        raise ValueError("negative amount not supported")
    rounded = round(float(amount), 2)
    return f"${rounded:,.2f}"


def format_eur(amount: float) -> str:
    """Format amount as EUR."""
    if not isinstance(amount, (int, float)):
        raise TypeError("amount must be a numeric value")
    if amount < 0:
        raise ValueError("negative amount not supported")
    rounded = round(float(amount), 2)
    return f"€{rounded:,.2f}"


def format_gbp(amount: float) -> str:
    """Format amount as GBP."""
    if not isinstance(amount, (int, float)):
        raise TypeError("amount must be a numeric value")
    if amount < 0:
        raise ValueError("negative amount not supported")
    rounded = round(float(amount), 2)
    return f"£{rounded:,.2f}"
