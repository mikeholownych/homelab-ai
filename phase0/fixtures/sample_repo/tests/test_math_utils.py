"""Independent test suite for calculator math utils."""
import pytest
from src.calculator.math_utils import calculate_ratio


def test_calculate_ratio_normal():
    assert calculate_ratio(10, 2) == 5.0
    assert calculate_ratio(9, 3) == 3.0


def test_calculate_ratio_zero_denominator():
    with pytest.raises(ValueError, match="Denominator cannot be zero"):
        calculate_ratio(10, 0)
