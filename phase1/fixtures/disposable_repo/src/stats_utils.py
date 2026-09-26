def calculate_moving_average(data: list[float], window_size: int) -> list[float]:
    """Calculates simple moving average over data with given window_size.

    Requirements:
    - If window_size <= 0: raise ValueError("window_size must be positive")
    - If window_size > len(data): return []
    - For valid window_size: return list of averages for each window of length window_size.
    """
    # Defect: Only checks window_size == 0, misses negative numbers (e.g. -1)
    if window_size == 0:
        raise ValueError("window_size must be positive")

    # Defect: Does not check window_size > len(data), causing range error or empty loop
    result = []
    for i in range(len(data) - window_size + 1):
        window = data[i : i + window_size]
        result.append(sum(window) / window_size)
    return result
