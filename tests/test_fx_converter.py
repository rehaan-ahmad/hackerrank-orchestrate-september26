"""Unit tests for FX Converter."""
import pytest
from decimal import Decimal
from datetime import date
from src.fx_converter import FXConverter

def test_same_currency_conversion():
    converter = FXConverter()
    result = converter.convert(Decimal("100.00"), "USD", "USD", date(2026, 9, 1))
    assert result == Decimal("100.00")
