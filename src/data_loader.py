"""
Data Loader Module for Buy or Wait?
Handles loading, joining, indexing CSV dataset files, context extraction,
FX conversion lookup, missing amount resolution, and financial event classification.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Any, Union, Optional
from datetime import date
from collections import deque
import pandas as pd
import numpy as np


@dataclass
class RequestContext:
    """Dataclass containing all context relevant to a single affordability request."""
    request: pd.Series
    profile: pd.Series
    events: pd.DataFrame
    payment_options: pd.DataFrame
    messages: pd.DataFrame
    images: pd.DataFrame
    exchange_rates: pd.DataFrame


def load_all_datasets(dataset_dir: Union[str, Path] = "dataset", debug: bool = True) -> Dict[str, pd.DataFrame]:
    """
    Load all 8 CSV datasets with correct dtypes, date parsing, and UTF-8 encoding.
    
    Args:
        dataset_dir: Directory containing CSV files.
        debug: If True, prints shape and first row preview for each dataset.
        
    Returns:
        Dict mapping dataset keys to loaded pandas DataFrames.
    """
    base_path = Path(dataset_dir)
    
    files_config = {
        "requests": {
            "filename": "requests.csv",
            "parse_dates": ["request_date", "desired_completion_date"],
            "floats": ["requested_amount"]
        },
        "sample_requests": {
            "filename": "sample_requests.csv",
            "parse_dates": ["request_date", "desired_completion_date", "earliest_date_for_full_payment"],
            "floats": ["requested_amount", "amount_safe_to_pay"]
        },
        "financial_profiles": {
            "filename": "financial_profiles.csv",
            "parse_dates": [],
            "floats": ["current_available_balance", "minimum_balance_to_keep"]
        },
        "financial_events": {
            "filename": "financial_events.csv",
            "parse_dates": ["event_date", "settlement_date"],
            "floats": ["amount", "minimum_allowed_amount"]
        },
        "exchange_rates": {
            "filename": "exchange_rates.csv",
            "parse_dates": ["rate_date"],
            "floats": ["rate"]
        },
        "request_payment_options": {
            "filename": "request_payment_options.csv",
            "parse_dates": ["first_payment_date"],
            "floats": ["payment_amount", "financing_fee", "total_payable_amount"]
        },
        "messages": {
            "filename": "messages.csv",
            "parse_dates": ["sent_at"],
            "floats": []
        },
        "images": {
            "filename": "images.csv",
            "parse_dates": [],
            "floats": []
        }
    }
    
    datasets: Dict[str, pd.DataFrame] = {}
    
    for key, cfg in files_config.items():
        filepath = base_path / cfg["filename"]
        if not filepath.exists():
            raise FileNotFoundError(f"Required dataset file missing: {filepath}")
            
        df = pd.read_csv(filepath, encoding="utf-8")
        
        # Parse date columns
        for date_col in cfg["parse_dates"]:
            if date_col in df.columns:
                df[date_col] = pd.to_datetime(df[date_col], errors="coerce")
                
        # Ensure float columns are float64
        for float_col in cfg["floats"]:
            if float_col in df.columns:
                df[float_col] = pd.to_numeric(df[float_col], errors="coerce")
                
        datasets[key] = df
        
        if debug:
            print(f"[LOAD] {key}: shape={df.shape}")
            if not df.empty:
                print(f"  Preview 1st row: {df.iloc[0].to_dict()}")
                
    return datasets


def get_request_context(request_id: str, data: Dict[str, pd.DataFrame]) -> RequestContext:
    """
    Extract full context for a specific request_id.
    
    Args:
        request_id: Unique request identifier (e.g. 'request_01', 'request_26').
        data: Dict of loaded DataFrames from load_all_datasets().
        
    Returns:
        RequestContext object.
    """
    requests_df = data.get("requests", pd.DataFrame())
    sample_df = data.get("sample_requests", pd.DataFrame())
    
    req_match = requests_df[requests_df["request_id"] == request_id]
    if req_match.empty and not sample_df.empty:
        req_match = sample_df[sample_df["request_id"] == request_id]
        
    if req_match.empty:
        raise KeyError(f"request_id '{request_id}' not found in requests or sample_requests")
        
    request_row = req_match.iloc[0]
    user_id = request_row["user_id"]
    
    profiles_df = data.get("financial_profiles", pd.DataFrame())
    profile_match = profiles_df[profiles_df["user_id"] == user_id]
    if profile_match.empty:
        raise KeyError(f"user_id '{user_id}' not found in financial_profiles")
    profile_row = profile_match.iloc[0]
    
    events_df = data.get("financial_events", pd.DataFrame())
    user_events = events_df[events_df["user_id"] == user_id].copy() if not events_df.empty else pd.DataFrame()
    
    payment_opts_df = data.get("request_payment_options", pd.DataFrame())
    req_opts = payment_opts_df[payment_opts_df["request_id"] == request_id].copy() if not payment_opts_df.empty else pd.DataFrame()
    
    messages_df = data.get("messages", pd.DataFrame())
    event_ids = set(user_events["event_id"]) if not user_events.empty else set()
    
    if not messages_df.empty:
        msg_mask = (
            (messages_df["user_id"] == user_id) |
            (messages_df["request_id"] == request_id) |
            (messages_df["related_event_id"].isin(event_ids))
        )
        user_messages = messages_df[msg_mask].copy()
    else:
        user_messages = pd.DataFrame()
        
    images_df = data.get("images", pd.DataFrame())
    if not images_df.empty:
        img_mask = (
            (images_df["user_id"] == user_id) |
            (images_df["request_id"] == request_id) |
            (images_df["related_event_id"].isin(event_ids))
        )
        user_images = images_df[img_mask].copy()
    else:
        user_images = pd.DataFrame()
        
    exchange_rates_df = data.get("exchange_rates", pd.DataFrame())
    
    return RequestContext(
        request=request_row,
        profile=profile_row,
        events=user_events,
        payment_options=req_opts,
        messages=user_messages,
        images=user_images,
        exchange_rates=exchange_rates_df
    )


def resolve_event_amounts(events: pd.DataFrame, images_df: pd.DataFrame) -> pd.DataFrame:
    """
    Locate linked image_id for events with missing (NaN) amount via images.csv.
    Adds image_id and has_missing_amount flag without modifying existing valid amounts.
    
    Args:
        events: DataFrame of financial events.
        images_df: DataFrame of images linking image_id to related_event_id.
        
    Returns:
        DataFrame copy with image_id and has_missing_amount columns added.
    """
    df = events.copy()
    
    if "event_id" not in df.columns or images_df.empty or "related_event_id" not in images_df.columns:
        df["image_id"] = None
        df["has_missing_amount"] = df["amount"].isna()
        return df

    # Map related_event_id -> image_id
    img_map = dict(zip(images_df["related_event_id"], images_df["image_id"]))
    
    df["image_id"] = df["event_id"].map(img_map)
    df["has_missing_amount"] = df["amount"].isna()
    
    return df


def apply_exchange_rate(
    amount: float,
    from_currency: str,
    to_currency: str,
    rate_date: Union[str, date, pd.Timestamp],
    exchange_rates: pd.DataFrame
) -> float:
    """
    Look up exchange rate by date and currency pair (supporting graph traversal / USD chaining).
    
    Args:
        amount: Numeric amount to convert.
        from_currency: Source 3-letter currency code (e.g. 'EUR').
        to_currency: Target 3-letter currency code (e.g. 'ZAR').
        rate_date: Date for exchange rate lookup.
        exchange_rates: DataFrame of exchange_rates.csv.
        
    Returns:
        Converted amount as a float.
        
    Raises:
        ValueError: If no valid exchange rate path exists.
    """
    if amount is None or np.isnan(amount):
        return amount
        
    if from_currency == to_currency:
        return float(amount)
        
    if exchange_rates.empty:
        raise ValueError("exchange_rates DataFrame is empty")
        
    df = exchange_rates.copy()
    if not pd.api.types.is_datetime64_any_dtype(df["rate_date"]):
        df["rate_date"] = pd.to_datetime(df["rate_date"])
        
    dt = pd.to_datetime(rate_date)
    
    # Select available rates on or before target date
    sub = df[df["rate_date"] <= dt]
    if sub.empty:
        sub = df  # fallback to earliest available rates
    
    effective_dt = sub["rate_date"].max()
    sub_dt = df[df["rate_date"] == effective_dt]
    
    # Build bidirectional adjacency graph for FX pairs
    adj: Dict[str, list] = {}
    for _, row in sub_dt.iterrows():
        fc, tc, r = str(row["from_currency"]), str(row["to_currency"]), float(row["rate"])
        adj.setdefault(fc, []).append((tc, r))
        adj.setdefault(tc, []).append((fc, 1.0 / r))
        
    # BFS to find conversion multiplier
    queue = deque([(from_currency, 1.0)])
    visited = {from_currency}
    
    while queue:
        curr, r_acc = queue.popleft()
        if curr == to_currency:
            return float(amount * r_acc)
            
        for nxt, r_edge in adj.get(curr, []):
            if nxt not in visited:
                visited.add(nxt)
                queue.append((nxt, r_acc * r_edge))
                
    raise ValueError(f"No exchange rate path found from {from_currency} to {to_currency} for date {dt.strftime('%Y-%m-%d')}")


def classify_events(events: pd.DataFrame) -> pd.DataFrame:
    """
    Classify financial events into boolean flag columns.
    
    Adds:
        is_recurring, is_income, is_expense, is_cancelled, is_failed,
        is_pending, is_settled, is_flexible
    
    Args:
        events: DataFrame of financial events.
        
    Returns:
        DataFrame copy with added classification boolean columns.
    """
    df = events.copy()
    if df.empty:
        for col in ["is_recurring", "is_income", "is_expense", "is_cancelled", "is_failed", "is_pending", "is_settled", "is_flexible"]:
            df[col] = pd.Series(dtype=bool)
        return df

    # Direction flags
    df["is_income"] = df["direction"] == "credit"
    df["is_expense"] = df["direction"] == "debit"
    
    # Status flags
    df["is_cancelled"] = df["status"] == "cancelled"
    df["is_failed"] = df["status"] == "failed"
    df["is_pending"] = df["status"] == "pending"
    df["is_settled"] = df["status"] == "settled"
    
    # Flexibility flag
    df["is_flexible"] = df["flexibility"] != "fixed"
    
    # Recurrence detection
    recurring_categories = {
        "rent", "utilities", "salary", "cloud_storage", "streaming",
        "music_subscription", "delivery_membership", "gym", "debt_repayment",
        "insurance", "groceries"
    }
    
    # Category / event_type based recurrence
    cat_rec = df["category"].isin(recurring_categories) | (df["event_type"] == "subscription")
    
    # Frequency based recurrence (3 or more historical occurrences for user + category)
    if "user_id" in df.columns and "category" in df.columns:
        counts = df.groupby(["user_id", "category"])["event_id"].transform("count")
        freq_rec = counts >= 3
    else:
        freq_rec = pd.Series(False, index=df.index)
        
    df["is_recurring"] = cat_rec | freq_rec
    
    return df
