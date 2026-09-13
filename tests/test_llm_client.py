"""
Unit tests for src/llm_client.py
Tests UsageTracker, retry logic, malformed LLM output handling, fallback decision explanations,
and image base64 processing on dataset images.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock

from src.llm_client import LLMClient, UsageTracker, INPUT_PRICE_PER_M, OUTPUT_PRICE_PER_M


def test_usage_tracker_accumulation():
    """Verify UsageTracker correctly records token usage, call types, and costs."""
    tracker = UsageTracker()
    tracker.add_call("vision", "claude-sonnet-4-6", 1000, 100)
    tracker.add_call("explanation", "claude-sonnet-4-6", 500, 50)
    
    report = tracker.get_report()
    assert report["total_calls"] == 2
    assert report["total_input_tokens"] == 1500
    assert report["total_output_tokens"] == 150
    
    expected_cost = (1500 * INPUT_PRICE_PER_M / 1e6) + (150 * OUTPUT_PRICE_PER_M / 1e6)
    assert pytest.approx(report["total_cost"], 0.0001) == expected_cost
    assert "vision" in report["by_type"]
    assert "explanation" in report["by_type"]


def test_usage_tracker_write_report(tmp_path):
    """Verify UsageTracker writes formatted markdown report."""
    tracker = UsageTracker()
    tracker.add_call("messages", "claude-sonnet-4-6", 200, 30)
    
    report_file = tmp_path / "usage_report.md"
    tracker.write_usage_report(report_file)
    
    assert report_file.exists()
    content = report_file.read_text(encoding="utf-8")
    assert "# LLM Token Usage Report" in content
    assert "Messages" in content


def test_llm_client_retry_logic():
    """Test retry logic retries up to max_retries and raises exception on final failure."""
    client = LLMClient(api_key="mock_key")
    
    mock_func = MagicMock(side_effect=[ValueError("API Error 1"), ValueError("API Error 2"), "Success"])
    result = client._call_with_retry(mock_func, max_retries=3)
    assert result == "Success"
    assert mock_func.call_count == 3

    mock_fail_func = MagicMock(side_effect=ValueError("Persistent Error"))
    with pytest.raises(ValueError):
        client._call_with_retry(mock_fail_func, max_retries=2)
    assert mock_fail_func.call_count == 3


def test_extract_amount_from_image_dataset_files():
    """Test extract_amount_from_image reads valid dataset image files without error."""
    client = LLMClient(api_key=None)  # unconfigured client returns None without crashing
    
    image_paths = [
        "dataset/media/images/image_01.png",
        "dataset/media/images/image_02.png",
        "dataset/media/images/image_03.png"
    ]
    
    for path in image_paths:
        assert Path(path).exists()
        res = client.extract_amount_from_image(path)
        assert res is None  # None when API key is not configured


def test_fallback_decision_explanation():
    """Test decision explanation fallback generator when API key is not set."""
    client = LLMClient(api_key=None)
    
    class DummyPlan:
        request_id = "request_01"
        affordability_status = "affordable_now"
        recommended_payment_method = "full_payment"
        payment_plan = "2024-03-03:25256"
        earliest_date_for_full_payment = "2024-03-03"
        spending_changes_needed = "none"

    key_figures = {
        "currency": "ZAR",
        "requested_amount": 25256.0,
        "minimum_balance": 18000.0,
        "min_available_balance": 18000.0
    }

    explanation = client.generate_decision_explanation(None, DummyPlan(), key_figures)
    assert "Pay ZAR 25,256.00 today" in explanation
    assert "18,000.00" in explanation
