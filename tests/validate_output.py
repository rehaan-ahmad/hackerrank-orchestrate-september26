"""
Automated Output Validation Script for Buy or Wait?
Verifies all 250 rows in output.csv against all problem statement constraints.
"""

import sys
import re
from pathlib import Path
from datetime import datetime
import pandas as pd

# Add root directory to sys.path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_loader import load_all_datasets

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


def validate_output_file(output_csv_path: str = "output.csv", dataset_dir: str = "dataset"):
    """
    Comprehensive validation of output.csv against problem constraints.
    """
    out_path = Path(output_csv_path)
    if not out_path.exists():
        print(f"FAIL: {output_csv_path} does not exist.")
        return 1

    data = load_all_datasets(dataset_dir, debug=False)
    requests_df = data["requests"].set_index("request_id")
    options_df = data["request_payment_options"]
    events_df = data["financial_events"].set_index("event_id")

    output_df = pd.read_csv(out_path)
    
    print("=" * 60)
    print("VALIDATING OUTPUT.CSV AGAINST PROBLEM CONSTRAINTS")
    print("=" * 60)

    violations = []
    
    # 1. Total row count check
    if len(output_df) != 250:
        violations.append(f"Row count mismatch: expected 250, found {len(output_df)}")
    else:
        print("[PASS] Row count: 250/250 rows present.")

    # 2. Check each row
    for idx, row in output_df.iterrows():
        req_id = str(row["request_id"])
        
        if req_id not in requests_df.index:
            violations.append(f"Row {idx}: request_id '{req_id}' not found in requests.csv")
            continue
            
        req_row = requests_df.loc[req_id]
        requested_amt = float(req_row["requested_amount"])
        req_date = pd.to_datetime(req_row["request_date"]).strftime("%Y-%m-%d")
        
        safe_amt = float(row["amount_safe_to_pay"])
        status = str(row["affordability_status"])
        method = str(row["recommended_payment_method"])
        plan_str = str(row["payment_plan"])
        earliest_date_str = str(row["earliest_date_for_full_payment"]) if pd.notna(row["earliest_date_for_full_payment"]) else ""
        changes_str = str(row["spending_changes_needed"]) if pd.notna(row["spending_changes_needed"]) else "none"
        
        # Constraint a: 0 <= amount_safe_to_pay <= requested_amount
        if safe_amt < 0.0 or safe_amt > requested_amt + 1e-3:
            violations.append(f"[{req_id}] safe_amount {safe_amt} out of bounds [0, {requested_amt}]")

        # Constraint b: Allowed affordability status
        if status not in ALLOWED_AFFORDABILITY:
            violations.append(f"[{req_id}] Invalid affordability_status '{status}'")

        # Constraint c: Allowed payment method
        if method not in ALLOWED_METHODS:
            violations.append(f"[{req_id}] Invalid recommended_payment_method '{method}'")

        # Constraint d: For affordable_now -> earliest_date == request_date
        if status == "affordable_now":
            if earliest_date_str != req_date:
                violations.append(f"[{req_id}] affordable_now earliest_date '{earliest_date_str}' != request_date '{req_date}'")

        # Constraint e: For partial_payment -> exactly 2 payments, sum == requested_amount
        if method == "partial_payment":
            if plan_str == "none" or "|" not in plan_str:
                violations.append(f"[{req_id}] partial_payment plan invalid format: '{plan_str}'")
            else:
                parts = plan_str.split("|")
                if len(parts) != 2:
                    violations.append(f"[{req_id}] partial_payment expected 2 parts, got {len(parts)}")
                else:
                    sum_pmt = 0.0
                    for p in parts:
                        p_date, p_amt = p.split(":")
                        sum_pmt += float(p_amt)
                    if abs(sum_pmt - requested_amt) > 0.1:
                        violations.append(f"[{req_id}] partial_payment sum {sum_pmt} != requested {requested_amt}")

        # Constraint f: For installments -> payment_plan dates are chronological
        if "|" in plan_str and plan_str != "none":
            dates = []
            for p in plan_str.split("|"):
                if ":" in p:
                    d_str, _ = p.split(":", 1)
                    dates.append(pd.to_datetime(d_str))
            if dates != sorted(dates):
                violations.append(f"[{req_id}] payment_plan dates not in chronological order: '{plan_str}'")

        # Constraint g: spending_changes_needed flexible event check
        if changes_str != "none":
            for change in changes_str.split("|"):
                if ":" in change:
                    parts = change.split(":")
                    action = parts[0]
                    ev_id = parts[1]
                    if action not in ["stop", "reduce_to"]:
                        violations.append(f"[{req_id}] Invalid spending change action '{action}'")
                    if ev_id not in events_df.index:
                        violations.append(f"[{req_id}] Spending change refers to non-existent event_id '{ev_id}'")
                    else:
                        flex = str(events_df.loc[ev_id, "flexibility"]).lower()
                        if flex == "fixed":
                            violations.append(f"[{req_id}] Spending change refers to fixed event '{ev_id}'")

    print("-" * 60)
    if not violations:
        print("ALL CONSTRAINT VALIDATION CHECKS PASSED ✓")
        print("0 violations found across all 250 prediction rows.")
        return 0
    else:
        print(f"FAILED: Found {len(violations)} constraint violations:")
        for v in violations[:10]:
            print(f"  - {v}")
        if len(violations) > 10:
            print(f"  ... and {len(violations) - 10} more.")
        return 1


if __name__ == "__main__":
    sys.exit(validate_output_file())
