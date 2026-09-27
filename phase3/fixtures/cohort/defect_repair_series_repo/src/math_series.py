def compute_geometric_series(a: float, r: float, n: int) -> list[float]:
    """Computes first n terms of a geometric progression a, a*r, a*r^2, ...

    Requirements:
    - If n <= 0: raise ValueError("n must be positive")
    - If r == 0: raise ValueError("ratio r cannot be zero")
    - Returns list of float terms: [a * (r ** i) for i in range(n)]
    """
    # Defect: Only checks n == 0, misses negative n
    if n == 0:
        raise ValueError("n must be positive")

    # Defect: Missing check for r == 0
    terms = []
    current = float(a)
    for _ in range(n):
        terms.append(current)
        current *= r
    return terms
