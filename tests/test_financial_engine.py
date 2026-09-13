"""Unit tests for Financial Engine."""
import pytest
from src.financial_engine import FinancialEngine

def test_financial_engine_init():
    engine = FinancialEngine()
    assert engine is not None
