"""
Financial Engine Module for Buy or Wait?
Pure deterministic quantitative financial computation module.
No LLM dependencies — computes exact 90-day cash flow forecasts, affordability limits,
earliest safe full payment dates, spending change identification, and 6-rule plan ranking.
"""

from datetime import date, timedelta
from typing import List, Tuple, Optional, Dict, Any, Union
import pandas as pd
import numpy as np

from src.models import SpendingChange, SelectedPlan, RequestContext


def forecast_balance(
    start_balance: float,
    start_date: Union[date, pd.Timestamp],
    end_date: Union[date, pd.Timestamp],
    events: Union[pd.DataFrame, List[Any]],
    min_balance: float = 0.0,
    spending_changes: Optional[List[SpendingChange]] = None
) -> List[Tuple[date, float]]:
    """
    Generate daily balance forecast from start_date to end_date (inclusive).
    
    Rules:
    - Uses settled/confirmed recurring income (direction='credit', status in ['settled', 'scheduled'])
    - Uses recurring and scheduled expenses (direction='debit', status in ['settled', 'pending', 'scheduled'])
    - Ignores pending credits, failed/cancelled events, unrealized investments.
    - Applies spending_changes savings if provided.
    
    Returns:
        List of (date, balance) tuples for each day.
    """
    s_date = pd.to_datetime(start_date).date() if isinstance(start_date, (pd.Timestamp, str)) else start_date
    e_date = pd.to_datetime(end_date).date() if isinstance(end_date, (pd.Timestamp, str)) else end_date
    
    # Process events into DataFrame
    if isinstance(events, list):
        if len(events) > 0 and hasattr(events[0], "dict"):
            events_df = pd.DataFrame([e.dict() for e in events])
        else:
            events_df = pd.DataFrame(events)
    else:
        events_df = events.copy() if events is not None else pd.DataFrame()

    # Track stopped events and reduced event amounts
    stopped_event_ids = set()
    reduced_amounts = {}
    if spending_changes:
        for change in spending_changes:
            if change.action == "stop":
                stopped_event_ids.add(change.event_id)
            elif change.action == "reduce_to" and change.new_amount is not None:
                reduced_amounts[change.event_id] = change.new_amount

    # Build daily net cash flow map: date -> float
    daily_cash_flow: Dict[date, float] = {}
    
    if not events_df.empty:
        for _, row in events_df.iterrows():
            status = str(row.get("status", "")).lower()
            direction = str(row.get("direction", "")).lower()
            event_id = str(row.get("event_id", ""))
            
            # Skip invalid/ignored statuses
            if status in ["cancelled", "failed", "unrealized"]:
                continue
                
            # Date determination
            settlement_dt = row.get("settlement_date")
            event_dt = row.get("event_date")
            eff_dt = settlement_dt if pd.notna(settlement_dt) else event_dt
            
            if pd.isna(eff_dt):
                continue
                
            eff_date = pd.to_datetime(eff_dt).date() if isinstance(eff_dt, (pd.Timestamp, str)) else eff_dt
            
            # Skip events outside forecast window
            if eff_date < s_date or eff_date > e_date:
                continue
                
            # Amount determination
            raw_amt = row.get("amount")
            if pd.isna(raw_amt) or raw_amt is None:
                continue
            amt = float(raw_amt)
            
            # Check spending change modifications
            if event_id in stopped_event_ids:
                continue
            if event_id in reduced_amounts:
                amt = reduced_amounts[event_id]

            # Income vs Expense Cashflow rules
            if direction == "credit":
                # Only count settled or scheduled income (never pending credits)
                if status in ["settled", "scheduled"]:
                    daily_cash_flow[eff_date] = daily_cash_flow.get(eff_date, 0.0) + amt
            elif direction == "debit":
                # Count settled, pending, or scheduled debits
                if status in ["settled", "pending", "scheduled"]:
                    daily_cash_flow[eff_date] = daily_cash_flow.get(eff_date, 0.0) - amt

    # Daily simulation loop
    current_bal = float(start_balance)
    forecast: List[Tuple[date, float]] = []
    curr_date = s_date
    
    while curr_date <= e_date:
        if curr_date in daily_cash_flow:
            current_bal += daily_cash_flow[curr_date]
        forecast.append((curr_date, current_bal))
        curr_date += timedelta(days=1)
        
    return forecast


def compute_amount_safe_to_pay(
    context: Any,
    request_date: Optional[date] = None,
    payment_date: Optional[date] = None
) -> float:
    """
    Compute maximum amount safe to pay without dipping below min_balance over 90-day window.
    Capped at requested_amount.
    """
    req = context.request
    prof = context.profile
    events = context.events
    
    req_date = request_date or (req["request_date"].date() if isinstance(req["request_date"], (pd.Timestamp, str)) else req["request_date"])
    pay_date = payment_date or req_date
    
    start_balance = float(prof["current_available_balance"])
    min_balance = float(prof["minimum_balance_to_keep"])
    requested_amount = float(req["requested_amount"])
    
    # Edge case: current_balance <= min_balance
    if start_balance <= min_balance:
        return 0.0
        
    end_date = req_date + timedelta(days=90)
    forecast = forecast_balance(start_balance, req_date, end_date, events, min_balance)
    
    # Lowest projected balance over forecast period
    min_projected = min(bal for _, bal in forecast)
    
    safe_amount = max(0.0, min_projected - min_balance)
    return float(min(safe_amount, requested_amount))


def test_payment_plan(
    context: Any,
    payments: List[Tuple[date, float]],
    spending_changes: Optional[List[SpendingChange]] = None
) -> bool:
    """
    Test whether a scheduled payment plan maintains daily balance >= min_balance
    across the entire 90-day forecast period.
    """
    req = context.request
    prof = context.profile
    events = context.events
    
    req_date = req["request_date"].date() if isinstance(req["request_date"], (pd.Timestamp, str)) else req["request_date"]
    start_balance = float(prof["current_available_balance"])
    min_balance = float(prof["minimum_balance_to_keep"])
    end_date = req_date + timedelta(days=90)
    
    forecast = forecast_balance(start_balance, req_date, end_date, events, min_balance, spending_changes)
    daily_dict = dict(forecast)
    
    # Deduct scheduled plan payments on payment dates
    payment_map: Dict[date, float] = {}
    for p_date, p_amt in payments:
        p_dt = pd.to_datetime(p_date).date() if isinstance(p_date, (pd.Timestamp, str)) else p_date
        payment_map[p_dt] = payment_map.get(p_dt, 0.0) + float(p_amt)
        
    running_deduction = 0.0
    curr_date = req_date
    
    while curr_date <= end_date:
        if curr_date in payment_map:
            running_deduction += payment_map[curr_date]
        bal = daily_dict.get(curr_date, start_balance) - running_deduction
        if bal < min_balance:
            return False
        curr_date += timedelta(days=1)
        
    return True

test_payment_plan.__test__ = False



def get_earliest_full_payment_date(
    context: Any,
    requested_amount: float
) -> Optional[date]:
    """
    Scan day-by-day from request_date to request_date + 90 days.
    Returns the first date where paying requested_amount in full maintains balance >= min_balance.
    """
    req = context.request
    req_date = req["request_date"].date() if isinstance(req["request_date"], (pd.Timestamp, str)) else req["request_date"]
    
    for offset in range(91):
        candidate_date = req_date + timedelta(days=offset)
        if test_payment_plan(context, [(candidate_date, requested_amount)]):
            return candidate_date
            
    return None


def find_spending_changes(
    context: Any,
    shortfall: float
) -> List[SpendingChange]:
    """
    Identify up to 3 flexible recurring expense changes that cover the shortfall.
    Only considers categories explicitly permitted by user profile and not protected.
    """
    if shortfall <= 0:
        return []
        
    prof = context.profile
    events = context.events
    
    def parse_cats(val):
        if pd.isna(val) or val is None:
            return set()
        if isinstance(val, set):
            return val
        return set(str(val).split("|")) if str(val) else set()
        
    protected = parse_cats(prof.get("expense_categories_to_protect", ""))
    stoppable = parse_cats(prof.get("expense_categories_user_is_willing_to_stop", ""))
    reducible = parse_cats(prof.get("expense_categories_user_is_willing_to_reduce", ""))
    
    stoppable = stoppable - protected
    reducible = reducible - protected
    
    if events.empty:
        return []
        
    candidates: List[SpendingChange] = []
    
    # Filter recurring / flexible debit events
    for _, row in events.iterrows():
        cat = str(row.get("category", ""))
        event_id = str(row.get("event_id", ""))
        flex = str(row.get("flexibility", "")).lower()
        amt_val = row.get("amount")
        min_allowed_val = row.get("minimum_allowed_amount")
        
        if pd.isna(amt_val) or flex == "fixed":
            continue
            
        amt = float(amt_val)
        
        # Check stoppable
        if cat in stoppable and flex in ["stoppable", "reducible_or_stoppable"]:
            candidates.append(SpendingChange(
                event_id=event_id,
                action="stop",
                savings=amt
            ))
        # Check reducible
        elif cat in reducible and flex in ["reducible", "reducible_or_stoppable"] and pd.notna(min_allowed_val):
            min_allowed = float(min_allowed_val)
            savings = amt - min_allowed
            if savings > 0:
                candidates.append(SpendingChange(
                    event_id=event_id,
                    action="reduce_to",
                    savings=savings,
                    new_amount=min_allowed
                ))
                
    # Sort candidates by savings descending
    candidates.sort(key=lambda c: c.savings, reverse=True)
    
    # Select up to 3 changes to cover shortfall
    selected: List[SpendingChange] = []
    current_savings = 0.0
    
    for change in candidates:
        selected.append(change)
        current_savings += change.savings
        if current_savings >= shortfall or len(selected) == 3:
            break
            
    return selected if current_savings >= shortfall else selected


def rank_and_select_plan(
    context: Any,
    safe_amount: float,
    earliest_full_date: Optional[date],
    payment_options: Optional[pd.DataFrame] = None,
    spending_changes: Optional[List[SpendingChange]] = None
) -> SelectedPlan:
    """
    Select and rank the optimal payment plan using 6 tiebreaker rules:
    1. Complete by desired_completion_date
    2. No spending changes required
    3. Minimize total paid
    4. Start earlier
    5. Fewer payments
    6. Lowest payment_option_id
    """
    req = context.request
    prof = context.profile
    
    req_id = str(req["request_id"])
    req_date = req["request_date"].date() if isinstance(req["request_date"], (pd.Timestamp, str)) else req["request_date"]
    desired_date = req["desired_completion_date"].date() if isinstance(req["desired_completion_date"], (pd.Timestamp, str)) else req["desired_completion_date"]
    requested_amount = float(req["requested_amount"])
    allows_partial = bool(req["allows_partial_payment"])
    
    accepted_methods = str(prof.get("payment_methods_user_will_consider", "")).split("|")
    accepted_methods = [m.strip() for m in accepted_methods if m.strip()]
    
    max_inst_months = prof.get("max_installment_months")
    max_inst_months = int(max_inst_months) if pd.notna(max_inst_months) and max_inst_months is not None else None
    
    candidates = []

    # Candidate 1: Full Payment Today
    if "full_payment" in accepted_methods and safe_amount >= requested_amount:
        plan_str = f"{req_date.strftime('%Y-%m-%d')}:{requested_amount:.2f}".rstrip('0').rstrip('.')
        candidates.append({
            "status": "affordable_now",
            "method": "full_payment",
            "plan_str": plan_str,
            "earliest_full": req_date.strftime("%Y-%m-%d"),
            "changes_str": "none",
            "completes_on_time": req_date <= desired_date,
            "no_changes": True,
            "total_paid": requested_amount,
            "start_date": req_date,
            "num_payments": 1,
            "option_id": "0_full_payment",
            "explanation": f"Pay {requested_amount} today. Balance remains above minimum."
        })

    # Candidate 2: Supplier Installment Options
    opts_df = context.payment_options if payment_options is None else payment_options
    if "installments" in accepted_methods and not opts_df.empty:
        for _, opt in opts_df.iterrows():
            method = str(opt["payment_method"]).lower()
            if method != "installments":
                continue
                
            num_payments = int(opt["number_of_payments"])
            freq_days = int(opt["payment_frequency_days"]) if pd.notna(opt.get("payment_frequency_days")) else 30
            first_pay_dt = opt["first_payment_date"].date() if isinstance(opt["first_payment_date"], (pd.Timestamp, str)) else opt["first_payment_date"]
            pmt_amount = float(opt["payment_amount"])
            total_payable = float(opt["total_payable_amount"])
            opt_id = str(opt["payment_option_id"])
            
            # Check max_installment_months constraint
            approx_months = int(np.ceil((num_payments * freq_days) / 30.0))
            if max_inst_months is not None and approx_months > max_inst_months:
                continue
                
            # Build installment payment schedule
            schedule = []
            for i in range(num_payments):
                p_dt = first_pay_dt + timedelta(days=i * freq_days)
                schedule.append((p_dt, pmt_amount))
                
            last_pay_dt = schedule[-1][0]
            
            if test_payment_plan(context, schedule):
                plan_parts = [f"{d.strftime('%Y-%m-%d')}:{amt:.2f}".rstrip('0').rstrip('.') for d, amt in schedule]
                plan_str = "|".join(plan_parts)
                earliest_str = earliest_full_date.strftime("%Y-%m-%d") if earliest_full_date else ""
                
                candidates.append({
                    "status": "affordable_with_plan",
                    "method": "installments",
                    "plan_str": plan_str,
                    "earliest_full": earliest_str,
                    "changes_str": "none",
                    "completes_on_time": last_pay_dt <= desired_date,
                    "no_changes": True,
                    "total_paid": total_payable,
                    "start_date": first_pay_dt,
                    "num_payments": num_payments,
                    "option_id": opt_id,
                    "explanation": f"Use {num_payments} installments starting {first_pay_dt.strftime('%Y-%m-%d')}."
                })

    # Candidate 3: Partial Payment
    if "partial_payment" in accepted_methods and allows_partial and 0 < safe_amount < requested_amount:
        if earliest_full_date is not None and earliest_full_date <= desired_date:
            second_amount = requested_amount - safe_amount
            schedule = [(req_date, safe_amount), (earliest_full_date, second_amount)]
            if test_payment_plan(context, schedule):
                plan_parts = [
                    f"{req_date.strftime('%Y-%m-%d')}:{safe_amount:.2f}".rstrip('0').rstrip('.'),
                    f"{earliest_full_date.strftime('%Y-%m-%d')}:{second_amount:.2f}".rstrip('0').rstrip('.')
                ]
                plan_str = "|".join(plan_parts)
                
                candidates.append({
                    "status": "affordable_with_plan",
                    "method": "partial_payment",
                    "plan_str": plan_str,
                    "earliest_full": earliest_full_date.strftime("%Y-%m-%d"),
                    "changes_str": "none",
                    "completes_on_time": earliest_full_date <= desired_date,
                    "no_changes": True,
                    "total_paid": requested_amount,
                    "start_date": req_date,
                    "num_payments": 2,
                    "option_id": "1_partial_payment",
                    "explanation": f"Pay safe amount today and remaining on {earliest_full_date.strftime('%Y-%m-%d')}."
                })

    # Candidate 4: Wait
    if "wait" in accepted_methods or len(candidates) == 0:
        if earliest_full_date is not None:
            plan_str = f"{earliest_full_date.strftime('%Y-%m-%d')}:{requested_amount:.2f}".rstrip('0').rstrip('.')
            candidates.append({
                "status": "affordable_later" if earliest_full_date <= desired_date else "not_affordable",
                "method": "wait",
                "plan_str": plan_str,
                "earliest_full": earliest_full_date.strftime("%Y-%m-%d"),
                "changes_str": "none",
                "completes_on_time": earliest_full_date <= desired_date,
                "no_changes": True,
                "total_paid": requested_amount,
                "start_date": earliest_full_date,
                "num_payments": 1,
                "option_id": "2_wait",
                "explanation": f"Wait until {earliest_full_date.strftime('%Y-%m-%d')} to pay in full."
            })

    # Candidate 5: Spending Changes + Full Payment Today
    if "full_payment" in accepted_methods and spending_changes and len(spending_changes) > 0:
        changes_str = "|".join([c.to_str() for c in spending_changes])
        if test_payment_plan(context, [(req_date, requested_amount)], spending_changes):
            plan_str = f"{req_date.strftime('%Y-%m-%d')}:{requested_amount:.2f}".rstrip('0').rstrip('.')
            earliest_str = earliest_full_date.strftime("%Y-%m-%d") if earliest_full_date else ""
            
            candidates.append({
                "status": "affordable_with_plan",
                "method": "full_payment",
                "plan_str": plan_str,
                "earliest_full": earliest_str,
                "changes_str": changes_str,
                "completes_on_time": req_date <= desired_date,
                "no_changes": False,
                "total_paid": requested_amount,
                "start_date": req_date,
                "num_payments": 1,
                "option_id": "3_spending_changes",
                "explanation": f"Apply spending changes ({changes_str}) to pay in full today."
            })

    # Filter candidates completing on time if available
    if not candidates:
        return SelectedPlan(
            request_id=req_id,
            amount_safe_to_pay=safe_amount,
            affordability_status="not_affordable",
            recommended_payment_method="not_recommended",
            payment_plan="none",
            earliest_date_for_full_payment="",
            spending_changes_needed="none",
            decision_explanation="No viable payment plan satisfies minimum balance constraints."
        )

    # Sort candidates using 6 tiebreaker rules
    def rank_key(c):
        return (
            not c["completes_on_time"],       # 1. On time first
            not c["no_changes"],              # 2. No changes first
            c["total_paid"],                  # 3. Minimize total paid
            c["start_date"],                  # 4. Start earlier
            c["num_payments"],                # 5. Fewer payments
            c["option_id"]                    # 6. Lowest option ID
        )

    candidates.sort(key=rank_key)
    best = candidates[0]

    return SelectedPlan(
        request_id=req_id,
        amount_safe_to_pay=safe_amount,
        affordability_status=best["status"],
        recommended_payment_method=best["method"],
        payment_plan=best["plan_str"],
        earliest_date_for_full_payment=best["earliest_full"],
        spending_changes_needed=best["changes_str"],
        decision_explanation=best["explanation"]
    )
