# Decision Rules Inferred from sample_requests.csv

## Executive Summary

Analysis of 25 labeled samples reveals a deterministic, rule-based affordability engine. The decision flow follows a strict priority order with explicit financial constraints.

---

## Core Decision Algorithm (Pseudocode)

```
FUNCTION decide_affordability(request, profile, events, payment_options, messages, images):
    
    # 1. RECONSTRUCT FINANCIAL POSITION AS OF request_date
    available_balance = compute_available_balance(profile, events, request_date, messages)
    minimum_balance = profile.minimum_balance_to_keep
    
    # 2. FORECAST 90-DAY CASH FLOW (request_date to request_date + 90 days)
    forecast = build_cash_flow_forecast(profile, events, request_date, messages)
    
    # 3. CONVERT REQUEST TO HOME CURRENCY
    request_amount_home = convert_to_home_currency(request.requested_amount, 
                                                    request.currency, 
                                                    profile.home_currency,
                                                    request.request_date)
    
    # 4. CHECK AFFORDABILITY TIER 1: AFFORDABLE_NOW
    IF can_pay_full_today(available_balance, minimum_balance, request_amount_home, forecast):
        RETURN {
            amount_safe_to_pay: request_amount_home,
            affordability_status: "affordable_now",
            recommended_payment_method: "full_payment",
            payment_plan: f"{request_date}:{request_amount_home}",
            earliest_date_for_full_payment: request_date,
            spending_changes_needed: "none",
            explanation: f"Pay {format_amount(request_amount_home)} today. " +
                         f"This leaves at least {format_amount(min_balance_after)} available over 90 days."
        }
    
    # 5. CHECK AFFORDABILITY TIER 2: AFFORDABLE_WITH_PLAN
    # Try options in priority order:
    
    # 5a. Installments (if user accepts AND request allows AND options exist)
    IF "installments" IN profile.payment_methods_user_will_consider:
        best_installment = find_best_installment_option(payment_options, profile, forecast)
        IF best_installment EXISTS:
            RETURN build_installment_response(best_installment, forecast)
    
    # 5b. Partial Payment (if user accepts AND request.allows_partial_payment)
    IF "partial_payment" IN profile.payment_methods_user_will_consider AND request.allows_partial_payment:
        partial = find_max_partial_payment(available_balance, minimum_balance, forecast)
        IF partial > 0 AND partial < request_amount_home:
            completion_date = find_earliest_full_payment_date(forecast, request_amount_home - partial)
            IF completion_date <= request.desired_completion_date:
                RETURN build_partial_payment_response(partial, completion_date, forecast)
    
    # 5c. Full Payment with Spending Changes
    changes = find_minimal_spending_changes(profile, events, forecast, request_amount_home)
    IF changes IS NOT NULL AND len(changes) <= 3:
        # After changes, can we pay full today?
        new_balance = available_balance + savings_from_changes(changes)
        IF can_pay_full_today(new_balance, minimum_balance, request_amount_home, forecast):
            RETURN build_full_payment_with_changes_response(changes, forecast)
    
    # 6. CHECK AFFORDABILITY TIER 3: AFFORDABLE_LATER
    # Can we pay full by desired_completion_date without changes?
    earliest_full = find_earliest_full_payment_date(forecast, request_amount_home)
    IF earliest_full EXISTS AND earliest_full <= request.desired_completion_date:
        RETURN {
            amount_safe_to_pay: max_safe_partial_today(available_balance, minimum_balance, forecast),
            affordability_status: "affordable_later",
            recommended_payment_method: "wait",
            payment_plan: f"{earliest_full}:{request_amount_home}",
            earliest_date_for_full_payment: earliest_full,
            spending_changes_needed: "none",
            explanation: f"Pay {format_amount(request_amount_home)} in full on {earliest_full}. " +
                         f"Paying earlier would take balance below {format_amount(minimum_balance)} minimum."
        }
    
    # 7. NOT AFFORDABLE
    # Calculate max safe partial today (may be small)
    max_safe = max_safe_partial_today(available_balance, minimum_balance, forecast)
    RETURN {
        amount_safe_to_pay: max_safe,
        affordability_status: "not_affordable",
        recommended_payment_method: "not_recommended",
        payment_plan: "none",
        earliest_date_for_full_payment: "",
        spending_changes_needed: "none",
        explanation: f"Do not make this payment by {request.desired_completion_date}. " +
                     f"None of the available options keeps the {format_amount(minimum_balance)} minimum protected."
    }
```

---

## Detailed Rules by Affordability Status

### 1. AFFORDABLE_NOW (3 samples: request_01, request_09, request_16)

**Conditions:**
- `available_balance - request_amount_home >= minimum_balance` TODAY
- Projected balance stays >= minimum_balance for 90 days after payment
- No pending debits that would breach minimum

**Output Pattern:**
- `amount_safe_to_pay = requested_amount` (full amount)
- `affordability_status = "affordable_now"`
- `recommended_payment_method = "full_payment"`
- `payment_plan = "YYYY-MM-DD:amount"` (single entry on request_date)
- `earliest_date_for_full_payment = request_date`
- `spending_changes_needed = "none"`

**Explanation Template:** "Pay {CURRENCY} {AMOUNT} today. This leaves at least {CURRENCY} {MIN_AVAILABLE} available over the next 90 days."

---

### 2. AFFORDABLE_LATER (6 samples: request_03, request_04, request_08, request_13, request_18, request_23)

**Conditions:**
- Cannot pay full today without breaching minimum
- But confirmed incoming cash (salary) will arrive before desired_completion_date
- Waiting for that income makes full payment safe
- `allows_partial_payment` may be True or False — but partial NOT used; instead WAIT

**Output Pattern:**
- `amount_safe_to_pay < requested_amount` (often small or 0)
- `affordability_status = "affordable_later"`
- `recommended_payment_method = "wait"`
- `payment_plan = "YYYY-MM-DD:requested_amount"` (single entry on earliest_full_date)
- `earliest_date_for_full_payment = earliest_full_date` (== desired_completion_date or salary date)
- `spending_changes_needed = "none"`

**Explanation Template:** "Pay {CURRENCY} {AMOUNT} in full on {DATE}. Paying earlier would take the balance below the {CURRENCY} {MINIMUM} minimum."

**Key Insight:** Even when `allows_partial_payment=True` (request_04, request_13), the decision is WAIT, not partial_payment. Partial payment is only used when it completes the request BY the deadline (see affordable_with_plan).

---

### 3. AFFORDABLE_WITH_PLAN (9 samples)

#### 3a. Installments (5 samples: request_02, request_07, request_12, request_17, request_22)

**Conditions:**
- User accepts installments (`"installments"` in payment_methods_user_will_consider)
- Request has installment options in request_payment_options
- Installment months <= profile.max_installment_months
- Each installment payment keeps balance >= minimum
- Total cost (with financing_fee) is accepted

**Output Pattern:**
- `amount_safe_to_pay = requested_amount` (full request completed via plan)
- `affordability_status = "affordable_with_plan"`
- `recommended_payment_method = "installments"`
- `payment_plan = "DATE1:AMT1|DATE2:AMT2|DATE3:AMT3"` (matches chosen option exactly)
- `earliest_date_for_full_payment = date when full would be safe without installments` (typically 1-2 months out)
- `spending_changes_needed = "none"`

**Explanation Template:** "Use {N} installments of {CURRENCY} {AMOUNT}, starting {START_DATE}. This leaves at least {CURRENCY} {MIN_AVAILABLE} available."

**Selection Logic:** Choose option that:
1. Completes by desired_completion_date
2. Minimizes total_payable_amount
3. Starts earliest
4. Fewest payments

#### 3b. Full Payment with Spending Changes (3 samples: request_06, request_11, request_21)

**Conditions:**
- User has flexible expenses in willing-to-reduce/stop categories
- Changes are NOT in protected categories
- After changes, full payment today is safe
- Max 3 changes (stop or reduce_to)

**Output Pattern:**
- `amount_safe_to_pay = requested_amount`
- `affordability_status = "affordable_with_plan"`
- `recommended_payment_method = "full_payment"`
- `payment_plan = "request_date:requested_amount"`
- `earliest_date_for_full_payment = date when full would be safe WITHOUT changes`
- `spending_changes_needed = "stop:event_X|reduce_to:event_Y:new_amount"`

**Explanation Template:** "{Action} the {category}, then pay {CURRENCY} {AMOUNT} today. This leaves at least {CURRENCY} {MIN_AVAILABLE} available."

**Change Format:**
- `stop:event_XXX` — cancel subscription/recurring entirely
- `reduce_to:event_XXX:NEW_AMOUNT` — reduce to minimum_allowed_amount or specified

#### 3c. Partial Payment (1 sample: request_19)

**Conditions:**
- `allows_partial_payment = True`
- `"partial_payment"` in profile.payment_methods_user_will_consider
- `0 < amount_safe_to_pay < requested_amount`
- Second payment on `earliest_date_for_full_payment` <= desired_completion_date
- Two payments sum to requested_amount

**Output Pattern:**
- `amount_safe_to_pay = partial_amount`
- `affordability_status = "affordable_with_plan"`
- `recommended_payment_method = "partial_payment"`
- `payment_plan = "request_date:partial|earliest_date:remainder"`
- `earliest_date_for_full_payment = second_payment_date`
- `spending_changes_needed = "none"`

**Explanation Template:** "Pay {CURRENCY} {PARTIAL} today and the remaining {CURRENCY} {REMAINDER} on {DATE}. This completes the full request and keeps the {CURRENCY} {MINIMUM} minimum protected."

---

### 4. NOT_AFFORDABLE (7 samples: request_05, request_10, request_14, request_15, request_20, request_24, request_25)

**Conditions:**
- Cannot pay full today (breaches minimum)
- No installment option fits (user doesn't accept, or exceeds max_months, or breaches minimum)
- No spending changes can bridge gap (protected categories block it)
- Even waiting until desired_completion_date won't accumulate enough (confirmed income insufficient)
- Partial payment (if allowed) would leave remainder unpayable by deadline

**Output Pattern:**
- `amount_safe_to_pay = max_safe_partial_today` (small, often << requested)
- `affordability_status = "not_affordable"`
- `recommended_payment_method = "not_recommended"`
- `payment_plan = "none"`
- `earliest_date_for_full_payment = ""` (empty)
- `spending_changes_needed = "none"`

**Explanation Templates:**
- If some amount safe today: "Do not proceed with the {CURRENCY} {AMOUNT} request. Although {CURRENCY} {SAFE} is available today, the full amount cannot be completed safely within 90 days."
- If nothing safe: "Do not make this payment by {DEADLINE}. None of the available options keeps the {CURRENCY} {MINIMUM} minimum protected."

---

## Critical Implementation Rules

### Balance Computation
1. Start with `profile.current_available_balance`
2. Add all **settled** credits (income, refunds) with settlement_date <= request_date
3. Subtract all **settled** debits (expenses, debt_payments) with settlement_date <= request_date
4. **Reserve** all **pending** debits (treat as already spent)
5. **Do NOT count** pending credits, scheduled income, unrealized gains
6. Add **scheduled** confirmed income on their settlement_date in forecast

### Forecast Horizon
- 90 days from request_date (per problem statement "forecast period")
- Include all scheduled/pending events with settlement_date in window
- Detect recurrence from historical patterns (monthly salary, weekly groceries, etc.)
- Variable essential spending: forecast conservatively (use recent average or max)

### Currency Conversion
- All amounts must be in user's `home_currency`
- Use `exchange_rates` on event `settlement_date` (or nearest prior 15th)
- Chain via USD if direct pair missing
- Request amount: convert using request_date rate

### Spending Change Eligibility
| Category in Profile Field | Can Stop? | Can Reduce? |
|---------------------------|-----------|-------------|
| expense_categories_to_protect | NO | NO |
| expense_categories_user_is_willing_to_stop | YES | YES |
| expense_categories_user_is_willing_to_reduce | NO | YES |
| Not listed | NO | NO |

Event must have `flexibility` = "stoppable", "reducible", or "reducible_or_stoppable"
Reduction cannot go below `minimum_allowed_amount`

### Payment Method Preference Order (when multiple viable)
1. Fewest spending changes (prefer 0)
2. Lowest total payment cost (avoid financing fees)
3. Earliest start date
4. Fewest number of payments
5. complete by deadline (desired_completion_date)

### Conflict Resolution (per §6.3)
1. Explicit cancellation/settlement/amendment first
2. Newer records from same source
3. Settled event over pending/scheduled
4. Financially safer interpretation

---

## Sample-to-Rule Mapping Table

| Sample | Status | Method | Key Trigger |
|--------|--------|--------|-------------|
| 01 | affordable_now | full_payment | Balance - request >= min, 90-day safe |
| 02 | affordable_with_plan | installments | User accepts installments, 3-month option fits |
| 03 | affordable_later | wait | Salary arrives Nov 15, can pay full then |
| 04 | affordable_later | wait | Salary arrives Jun 15, can pay full then |
| 05 | not_affordable | not_recommended | Even with changes, can't complete in 90 days |
| 06 | affordable_with_plan | full_payment | Stop streaming subscription → frees enough |
| 07 | affordable_with_plan | installments | 3-installment option fits budget |
| 08 | affordable_later | wait | Salary arrives Apr 15, can pay full then |
| 09 | affordable_now | full_payment | Small amount, balance sufficient |
| 10 | not_affordable | not_recommended | Request >> balance, no viable plan |
| 11 | affordable_with_plan | full_payment | Reduce food delivery → frees enough |
| 12 | affordable_with_plan | installments | 3-installment option fits budget |
| 13 | affordable_later | wait | Salary arrives May 15, can pay full then |
| 14 | not_affordable | not_recommended | Partial safe but can't complete in 90 days |
| 15 | not_affordable | not_recommended | Request > balance, no plan works |
| 16 | affordable_now | full_payment | Balance sufficient |
| 17 | affordable_with_plan | installments | 3-installment option fits budget |
| 18 | affordable_later | wait | Salary arrives Sep 15, can pay full then |
| 19 | affordable_with_plan | partial_payment | Allows partial, 2-payment plan completes by deadline |
| 20 | not_affordable | not_recommended | Request >> balance |
| 21 | affordable_with_plan | full_payment | Stop backup + reduce streaming → frees enough |
| 22 | affordable_with_plan | installments | 3-installment option fits budget |
| 23 | affordable_later | wait | Salary arrives Jul 15, can pay full then |
| 24 | not_affordable | not_recommended | Partial safe but can't complete in 90 days |
| 25 | not_affordable | not_recommended | Request >> balance |

---

## Edge Case Behaviors Observed

1. **amount_safe_to_pay for not_affordable**: Not zero — computes max safe partial today
2. **earliest_date_for_full_payment for affordable_now**: = request_date
3. **earliest_date_for_full_payment for affordable_later**: = date when confirmed income makes it safe
4. **earliest_date_for_full_payment for affordable_with_plan (installments)**: = projected date when full would be safe WITHOUT installments (typically later than last installment)
5. **earliest_date_for_full_payment for not_affordable**: Empty string
6. **payment_plan for wait**: Single entry on earliest_full_date with FULL amount (not partial)
7. **spending_changes_needed**: Max 3 actions, only on non-protected flexible events
8. **Installment selection**: Must match a supplied payment_option exactly (dates, amounts)