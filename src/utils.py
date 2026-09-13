"""
Utils Module for Buy or Wait?
Provides helper functions for date parsing, Decimal math, and string formatting.
"""
from decimal import Decimal

def to_decimal(val) -> Decimal:
    """Safely convert value to Decimal."""
    return Decimal(str(val))
