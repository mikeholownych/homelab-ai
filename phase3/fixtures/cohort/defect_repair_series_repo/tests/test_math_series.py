import pytest
from src.math_series import compute_geometric_series


def test_positive_geometric_series():
    result = compute_geometric_series(2.0, 3.0, 4)
    assert result == [2.0, 6.0, 18.0, 54.0]


def test_zero_terms_raises():
    with pytest.raises(ValueError, match="n must be positive"):
        compute_geometric_series(2.0, 3.0, 0)


def test_negative_terms_raises():
    with pytest.raises(ValueError, match="n must be positive"):
        compute_geometric_series(2.0, 3.0, -3)


def test_zero_ratio_raises():
    with pytest.raises(ValueError, match="ratio r cannot be zero"):
        compute_geometric_series(2.0, 0.0, 3)
