"""Unit tests for Plan Selector."""
import pytest
from src.plan_selector import PlanSelector

def test_plan_selector_init():
    selector = PlanSelector()
    assert selector is not None
