"""Test suite for moving average statistics utility."""
import pytest
from src.stats_utils import calculate_moving_average


def test_moving_average_standard():
    data = [1.0, 2.0, 3.0, 4.0, 5.0]
    expected = [2.0, 3.0, 4.0]
    assert calculate_moving_average(data, 3) == expected


def test_moving_average_negative_window():
    # Baseline defect: negative window does not raise ValueError
    with pytest.raises(ValueError, match="window_size must be positive"):
        calculate_moving_average([1.0, 2.0, 3.0], -2)


def test_moving_average_window_exceeds_data():
    # Baseline requirement: window_size > len(data) returns empty list
    assert calculate_moving_average([1.0, 2.0], 5) == []
