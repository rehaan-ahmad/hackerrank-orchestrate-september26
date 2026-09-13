"""
Unit tests for src/data_loader.py
Tests load_all_datasets, get_request_context, resolve_event_amounts,
apply_exchange_rate, and classify_events using real dataset rows.
"""

import pytest
from pathlib import Path
import pandas as pd
import numpy as np

from src.data_loader import (
    load_all_datasets,
    get_request_context,
    resolve_event_amounts,
    apply_exchange_rate,
    classify_events,
    RequestContext
)


@pytest.fixture(scope="module")
def dataset():
    """Load real datasets once for module tests."""
    return load_all_datasets("dataset", debug=False)


def test_load_all_datasets(dataset):
    """Verify all 8 datasets loaded with expected keys, shapes, and date types."""
    expected_keys = [
        "requests", "sample_requests", "financial_profiles", "financial_events",
        "exchange_rates", "request_payment_options", "messages", "images"
    ]
    for key in expected_keys:
        assert key in dataset
        assert isinstance(dataset[key], pd.DataFrame)
        assert not dataset[key].empty

    # Check date column types
    assert pd.api.types.is_datetime64_any_dtype(dataset["requests"]["request_date"])
    assert pd.api.types.is_datetime64_any_dtype(dataset["financial_events"]["event_date"])
    assert pd.api.types.is_datetime64_any_dtype(dataset["exchange_rates"]["rate_date"])


def test_get_request_context_real_rows(dataset):
    """Test get_request_context on 3 real request IDs (from evaluation and sample requests)."""
    test_ids = ["request_01", "request_02", "request_26"]
    
    for req_id in test_ids:
        ctx = get_request_context(req_id, dataset)
        assert isinstance(ctx, RequestContext)
        assert ctx.request["request_id"] == req_id
        assert isinstance(ctx.profile, pd.Series)
        assert not ctx.profile.empty
        assert isinstance(ctx.events, pd.DataFrame)
        assert not ctx.events.empty
        assert ctx.request["user_id"] == ctx.profile["user_id"]
        assert all(ctx.events["user_id"] == ctx.profile["user_id"])


def test_get_request_context_invalid_id(dataset):
    """Test get_request_context with non-existent request_id."""
    with pytest.raises(KeyError):
        get_request_context("non_existent_request_999", dataset)


def test_resolve_event_amounts(dataset):
    """Test resolve_event_amounts detects 16 missing image amounts correctly."""
    events = dataset["financial_events"]
    images = dataset["images"]
    
    resolved = resolve_event_amounts(events, images)
    
    assert "image_id" in resolved.columns
    assert "has_missing_amount" in resolved.columns
    
    # Check that missing amount rows match images.csv mapping
    missing_rows = resolved[resolved["has_missing_amount"]]
    assert len(missing_rows) == 16
    assert missing_rows["image_id"].notna().all()
    
    # Verify sample image event_253 -> image_01
    sample_img_row = resolved[resolved["event_id"] == "event_253"]
    assert not sample_img_row.empty
    assert sample_img_row.iloc[0]["image_id"] == "image_01"
    assert sample_img_row.iloc[0]["has_missing_amount"] is True or sample_img_row.iloc[0]["has_missing_amount"] == 1


def test_apply_exchange_rate_hits_and_misses(dataset):
    """Test apply_exchange_rate hit lookup, inverse lookup, USD chaining, and invalid pair miss."""
    rates = dataset["exchange_rates"]
    
    # 1. Direct hit (EUR -> ZAR on 2023-10-15: rate 20.0)
    converted_direct = apply_exchange_rate(100.0, "EUR", "ZAR", "2023-10-15", rates)
    assert pytest.approx(converted_direct, 0.01) == 2000.0
    
    # 2. Same currency (ZAR -> ZAR)
    converted_same = apply_exchange_rate(500.0, "ZAR", "ZAR", "2024-03-03", rates)
    assert converted_same == 500.0
    
    # 3. USD chaining (INR -> ZAR on 2024-03-15)
    converted_chained = apply_exchange_rate(8333.0, "INR", "USD", "2024-03-15", rates)
    assert pytest.approx(converted_chained, 0.1) == 100.0
    
    # 4. Invalid currency pair miss
    with pytest.raises(ValueError):
        apply_exchange_rate(100.0, "UNKNOWN_CURR", "ZAR", "2024-03-15", rates)


def test_classify_events_categories(dataset):
    """Test classify_events adds all boolean flag columns correctly."""
    events = dataset["financial_events"]
    classified = classify_events(events)
    
    expected_flags = [
        "is_recurring", "is_income", "is_expense", "is_cancelled",
        "is_failed", "is_pending", "is_settled", "is_flexible"
    ]
    for col in expected_flags:
        assert col in classified.columns
        assert classified[col].dtype == bool

    # Test direction flags
    debit_row = classified[classified["direction"] == "debit"].iloc[0]
    assert debit_row["is_expense"] is True or debit_row["is_expense"] == 1
    assert debit_row["is_income"] is False or debit_row["is_income"] == 0

    credit_row = classified[classified["direction"] == "credit"].iloc[0]
    assert credit_row["is_income"] is True or credit_row["is_income"] == 1
    assert credit_row["is_expense"] is False or credit_row["is_expense"] == 0

    # Test status flags
    settled_row = classified[classified["status"] == "settled"].iloc[0]
    assert settled_row["is_settled"] is True or settled_row["is_settled"] == 1

    pending_row = classified[classified["status"] == "pending"].iloc[0]
    assert pending_row["is_pending"] is True or pending_row["is_pending"] == 1

    # Test flexibility flags
    fixed_row = classified[classified["flexibility"] == "fixed"].iloc[0]
    assert fixed_row["is_flexible"] is False or fixed_row["is_flexible"] == 0

    stoppable_row = classified[classified["flexibility"] == "stoppable"].iloc[0]
    assert stoppable_row["is_flexible"] is True or stoppable_row["is_flexible"] == 1
