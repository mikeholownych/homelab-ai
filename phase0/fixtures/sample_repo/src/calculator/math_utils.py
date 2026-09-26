def calculate_ratio(a: float, b: float) -> float:
    """Calculates ratio of a to b.

    Expected behavior: raise ValueError if b == 0.
    """
    # Defect: missing zero check, causing unhandled ZeroDivisionError
    return a / b
