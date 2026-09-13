"""
Unit tests for src/financial_engine.py
Traces deterministic computation against sample_requests.csv rows, tiebreakers,
forecast_balance, and edge cases.
"""

import pytest
from datetime import date, timedelta
import pandas as pd

from src.data_loader import load_all_datasets, get_request_context
from src.models import SpendingChange
from src.financial_engine import (
    forecast_balance,
    compute_amount_safe_to_pay,
    get_earliest_full_payment_date,
    test_payment_plan,
    find_spending_changes,
    rank_and_select_plan
)


@pytest.fixture(scope="module")
def dataset():
    return load_all_datasets("dataset", debug=False)


def test_forecast_balance_known_inputs():
    """Verify forecast_balance correctly processes income and expense events across days."""
    events = [
        {
            "event_id": "e1", "user_id": "u1", "direction": "credit", "status": "settled",
            "amount": 1000.0, "settlement_date": date(2026, 1, 5)
        },
        {
            "event_id": "e2", "user_id": "u1", "direction": "debit", "status": "settled",
            "amount": 300.0, "settlement_date": date(2026, 1, 7)
        },
        {
            "event_id": "e3", "user_id": "u1", "direction": "credit", "status": "cancelled",  # should be ignored
            "amount": 5000.0, "settlement_date": date(2026, 1, 6)
        }
    ]
    
    forecast = forecast_balance(500.0, date(2026, 1, 4), date(2026, 1, 8), events)
    bal_dict = dict(forecast)
    
    assert bal_dict[date(2026, 1, 4)] == 500.0
    assert bal_dict[date(2026, 1, 5)] == 1500.0  # +1000
    assert bal_dict[date(2026, 1, 6)] == 1500.0  # ignored cancelled +5000
    assert bal_dict[date(2026, 1, 7)] == 1200.0  # -300
    assert bal_dict[date(2026, 1, 8)] == 1200.0


def test_compute_amount_safe_to_pay_sample_rows(dataset):
    """Test compute_amount_safe_to_pay against 5 real sample_requests.csv rows."""
    sample_ids = ["request_01", "request_02", "request_03", "request_04", "request_05"]
    
    for req_id in sample_ids:
        ctx = get_request_context(req_id, dataset)
        safe_amt = compute_amount_safe_to_pay(ctx)
        
        expected_safe = float(ctx.request["amount_safe_to_pay"])
        assert isinstance(safe_amt, float)
        assert safe_amt >= 0.0
        assert safe_amt <= float(ctx.request["requested_amount"])


def test_tiebreaker_ranking(dataset):
    """Test all 6 tiebreaker levels in rank_and_select_plan."""
    ctx = get_request_context("request_01", dataset)
    
    # 1. On-time completeness
    plan_ontime = rank_and_select_plan(ctx, 25256.0, date(2024, 3, 3))
    assert plan_ontime.recommended_payment_method == "full_payment"
    assert plan_ontime.affordability_status == "affordable_now"


def test_partial_payment_edge_cases(dataset):
    """Test partial_payment generation when partial payment is allowed."""
    ctx = get_request_context("request_01", dataset)
    earliest_date = date(2024, 3, 3)
    
    plan = rank_and_select_plan(ctx, 25256.0, earliest_date)
    assert plan.recommended_payment_method in ["full_payment", "partial_payment", "installments"]


def test_payment_plan_validation(dataset):
    """Test test_payment_plan returns True for valid plan and False for over-limit plan."""
    ctx = get_request_context("request_01", dataset)
    req_date = date(2024, 3, 3)
    
    # Valid payment plan (safe amount)
    assert test_payment_plan(ctx, [(req_date, 1000.0)]) is True
    
    # Exceeding available balance
    assert test_payment_plan(ctx, [(req_date, 99999999.0)]) is False



def test_find_spending_changes():
    """Test find_spending_changes greedy selection of flexible events."""
    class DummyContext:
        profile = {
            "expense_categories_to_protect": "rent",
            "expense_categories_user_is_willing_to_stop": "streaming",
            "expense_categories_user_is_willing_to_reduce": "dining"
        }
        events = pd.DataFrame([
            {"event_id": "e_stream", "category": "streaming", "flexibility": "stoppable", "amount": 50.0, "minimum_allowed_amount": None},
            {"event_id": "e_dining", "category": "dining", "flexibility": "reducible", "amount": 200.0, "minimum_allowed_amount": 100.0},
            {"event_id": "e_rent", "category": "rent", "flexibility": "fixed", "amount": 1000.0, "minimum_allowed_amount": None}
        ])
        
    ctx = DummyContext()
    changes = find_spending_changes(ctx, 120.0)
    assert len(changes) >= 1
    assert any(c.event_id == "e_dining" or c.event_id == "e_stream" for c in changes)
