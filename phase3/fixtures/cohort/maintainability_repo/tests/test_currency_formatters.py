"""Behavioral preservation tests for currency formatters."""
import pytest
from src.currency_formatters import format_usd, format_eur, format_gbp


def test_format_usd_valid():
    assert format_usd(1234.567) == "$1,234.57"
    assert format_usd(0) == "$0.00"
    assert format_usd(5) == "$5.00"


def test_format_eur_valid():
    assert format_eur(99.9) == "€99.90"
    assert format_eur(1000000) == "€1,000,000.00"


def test_format_gbp_valid():
    assert format_gbp(45.56) == "£45.56"


def test_type_errors():
    with pytest.raises(TypeError, match="numeric value"):
        format_usd("100")  # type: ignore
    with pytest.raises(TypeError, match="numeric value"):
        format_eur(None)  # type: ignore


def test_value_errors_on_negative():
    with pytest.raises(ValueError, match="negative amount"):
        format_usd(-1.0)
    with pytest.raises(ValueError, match="negative amount"):
        format_gbp(-0.01)
