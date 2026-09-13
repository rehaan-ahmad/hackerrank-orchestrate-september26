"""
Output Formatter Module for Buy or Wait?
Formats and validates output predictions against HackerRank Orchestrate schema constraints.
"""

from typing import Dict, Any, List, Union
from pathlib import Path
import pandas as pd

ALLOWED_AFFORDABILITY = {
    "affordable_now",
    "affordable_with_plan",
    "affordable_later",
    "not_affordable"
}

ALLOWED_METHODS = {
    "full_payment",
    "partial_payment",
    "installments",
    "wait",
    "not_recommended"
}

OUTPUT_COLUMNS = [
    "request_id",
    "amount_safe_to_pay",
    "affordability_status",
    "recommended_payment_method",
    "payment_plan",
    "earliest_date_for_full_payment",
    "spending_changes_needed",
    "decision_explanation"
]


def build_output_row(request_id: str, selected_plan: Any, context: Any) -> Dict[str, Any]:
    """
    Build and validate a single output CSV row dictionary.
    
    Args:
        request_id: Unique request identifier.
        selected_plan: SelectedPlan instance from financial_engine.
        context: RequestContext instance for request data.
        
    Returns:
        Dict matching exact output.csv column schema.
        
    Raises:
        ValueError: If any field violates constraints.
    """
    req = context.request
    requested_amount = float(req["requested_amount"])
    
    safe_amount = float(getattr(selected_plan, "amount_safe_to_pay", 0.0))
    if safe_amount < 0.0 or safe_amount > requested_amount + 1e-4:
        raise ValueError(f"Constraint failure for {request_id}: amount_safe_to_pay {safe_amount} out of bounds [0, {requested_amount}]")
        
    status = str(getattr(selected_plan, "affordability_status", "not_affordable"))
    if status not in ALLOWED_AFFORDABILITY:
        raise ValueError(f"Constraint failure for {request_id}: invalid affordability_status '{status}'")
        
    method = str(getattr(selected_plan, "recommended_payment_method", "not_recommended"))
    if method not in ALLOWED_METHODS:
        raise ValueError(f"Constraint failure for {request_id}: invalid recommended_payment_method '{method}'")
        
    plan_str = str(getattr(selected_plan, "payment_plan", "none")) or "none"
    earliest_date_str = str(getattr(selected_plan, "earliest_date_for_full_payment", "")) if getattr(selected_plan, "earliest_date_for_full_payment", None) else ""
    changes_str = str(getattr(selected_plan, "spending_changes_needed", "none")) or "none"
    explanation = str(getattr(selected_plan, "decision_explanation", "")) or "Decision rendered based on balance and forecast."

    # Format numeric amounts to clean float/string
    row = {
        "request_id": str(request_id),
        "amount_safe_to_pay": round(safe_amount, 2),
        "affordability_status": status,
        "recommended_payment_method": method,
        "payment_plan": plan_str,
        "earliest_date_for_full_payment": earliest_date_str,
        "spending_changes_needed": changes_str,
        "decision_explanation": explanation
    }
    
    return row


def validate_output(results: List[Dict[str, Any]]) -> bool:
    """
    Validate an entire list of 250 prediction dictionaries.
    
    Raises:
        ValueError: If validation fails for any row or column.
    """
    if len(results) != 250:
        raise ValueError(f"Output count mismatch: expected 250 rows, got {len(results)}")
        
    seen_ids = set()
    for idx, row in enumerate(results):
        for col in OUTPUT_COLUMNS:
            if col not in row:
                raise ValueError(f"Row {idx} missing column '{col}'")
                
        req_id = row["request_id"]
        if req_id in seen_ids:
            raise ValueError(f"Duplicate request_id found: '{req_id}'")
        seen_ids.add(req_id)
        
        status = row["affordability_status"]
        if status not in ALLOWED_AFFORDABILITY:
            raise ValueError(f"Invalid status '{status}' in row {req_id}")
            
        method = row["recommended_payment_method"]
        if method not in ALLOWED_METHODS:
            raise ValueError(f"Invalid method '{method}' in row {req_id}")
            
    return True


def write_output_csv(results: List[Dict[str, Any]], output_path: Union[str, Path] = "output.csv"):
    """
    Write validated predictions list to CSV file.
    """
    validate_output(results)
    
    out_path = Path(output_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    
    df = pd.DataFrame(results)[OUTPUT_COLUMNS]
    df.to_csv(out_path, index=False, encoding="utf-8")
