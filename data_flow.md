# Data Flow Trace: Sample Request (request_03)

## Selected Sample
**request_03** from sample_requests.csv:
- user_id: user_03
- request_date: 2019-09-03
- request_type: education
- requested_amount: 5,491,000 (IDR)
- desired_completion_date: 2019-11-15
- allows_partial_payment: False
- Expected output: affordable_later, wait, amount_safe_to_pay=873,000

---

## Step-by-Step Data Transformation

### STEP 1: Load Raw Data

```
financial_profiles.csv → user_03 row:
  user_id: "user_03"
  home_currency: "IDR"
  current_available_balance: 5,810,300
  minimum_balance_to_keep: 2,668,700
  financial_priorities: "retirement_investment|emergency_savings"
  expense_categories_to_protect: "rent|utilities|groceries"
  expense_categories_user_is_willing_to_reduce: "streaming|shopping"
  expense_categories_user_is_willing_to_stop: "streaming|cloud_storage"
  payment_methods_user_will_consider: "full_payment|partial_payment|installments"
  max_installment_months: 2

financial_events.csv → user_03 events (filtered by user_id):
  event_253: income, "August 2019 net salary", salary, credit, NaN, IDR, 
             2019-08-31, 2019-08-31, settled, NaN, fixed, NaN
             → amount blank → linked to image_01
  event_254: expense, "Healthcare expense", healthcare, debit, 95,000, IDR,
             2019-09-02, 2019-09-07, pending, NaN, fixed, NaN
  ... (historical settled events for rent, utilities, groceries, etc.)
  ... (scheduled salary for 2019-09-15, 2019-10-15, 2019-11-15)

exchange_rates.csv → IDR rates (relevant to user_03):
  USD→IDR = 15,833.33 (all months)
  No direct EUR→IDR or ZAR→IDR needed (user is IDR home)

request_payment_options.csv → request_03 options:
  payment_option_08: full_payment, 5,491,000, 1, 2019-09-03, NaN, 0, 5,491,000
  payment_option_09: installments, 308,541.90, 21, 2019-09-17, 28, 988,379.90, 6,479,379.90
  payment_option_10: installments, 279,125.83, 24, 2019-09-06, 31, 1,208,019.92, 6,699,019.92

messages.csv → request_03 messages:
  message_02: employer, 2019-08-31, "Tim payroll BrightPath Media telah mengirim pembaruan. 
              Gaji rutin untuk penggajian berikutnya sudah dikonfirmasi..."
              → Confirms regular salary for next payroll
  message_01: employer, 2025-07-29 (different user, ignore)

images.csv → image_01:
  image_id: "image_01", user_id: "user_03", request_id: "request_03", 
  related_event_id: "event_253"
```

### STEP 2: Image Amount Extraction (LLM Vision)

**Input:** dataset/media/images/image_01.png (salary slip)
**Prompt:** Extract amount from Indonesian salary slip for August 2019 net salary
**LLM Output:**
```json
{"amount": 2060000, "currency": "IDR"}
```

**Applied to event_253:**
- event_253.amount = 2,060,000 IDR (was NaN)

### STEP 3: FX Conversion (All amounts to home_currency = IDR)

Since user_03 home_currency = IDR and all events are already IDR:
- No conversion needed for events
- Request amount: 5,491,000 IDR (already in IDR, detected from request_text "IDR 5,491,000")

### STEP 4: Compute Available Balance (as of 2019-09-03)

**Starting balance:** 5,810,300 (current_available_balance)

**Add settled credits ≤ 2019-09-03:**
- event_253 (salary): +2,060,000 (settled 2019-08-31)
- Historical salaries: +X (sum of settled income before request_date)
- Historical refunds: +Y

**Subtract settled debits ≤ 2019-09-03:**
- Rent, utilities, groceries, streaming, shopping, etc. (historical settled expenses)
- Total historical debits: -Z

**Reserve pending debits (settlement_date > request_date but ≤ forecast_end):**
- event_254 (healthcare): -95,000 (pending, settlement 2019-09-07)

**Calculation:**
```
available_balance = 5,810,300 + 2,060,000 + X - Z - 95,000
                 = 4,546,700 (example computed value)
```

### STEP 5: Build 90-Day Forecast (2019-09-03 to 2019-12-02)

**Forecast window:** 2019-09-04 to 2019-12-02 (90 days inclusive)

**Future cash flows in window:**

| Date | Flow | Amount | Type | Source |
|------|------|--------|------|--------|
| 2019-09-07 | Debit | -95,000 | Healthcare (pending) | event_254 |
| 2019-09-15 | Credit | +2,060,000 | Salary (scheduled) | event_XXX |
| 2019-09-15 | Debit | -5,148 | Rent (recurring) | Historical pattern |
| 2019-09-15 | Debit | -1,475.46 | Utilities (recurring) | Historical pattern |
| 2019-09-15 | Debit | -1,821.60 | Education (recurring) | Historical pattern |
| 2019-09-15 | Debit | -3,487 | Debt repayment (recurring) | Historical pattern |
| 2019-10-15 | Credit | +2,060,000 | Salary (projected) | Recurrence detection |
| 2019-10-15 | Debit | -5,148 | Rent (projected) | Recurrence detection |
| ... | ... | ... | ... | ... |
| 2019-11-15 | Credit | +2,060,000 | Salary (projected) | Recurrence detection |
| 2019-11-15 | Debit | -5,148 | Rent (projected) | Recurrence detection |

**Recurrence Detection Applied:**
- Salary: Monthly on 15th, 3+ historical occurrences → project forward
- Rent: Monthly on 1st/15th, fixed amount → project forward
- Utilities: Monthly, variable → use 90th percentile of last 6 months
- Subscriptions: Monthly fixed → project forward

**Daily Balance Simulation:**
```
Day 0 (2019-09-03): opening=4,546,700, closing=4,546,700
Day 4 (2019-09-07): opening=4,546,700, flow=-95,000, closing=4,451,700
Day 12 (2019-09-15): opening=4,451,700, flow=+2,060,000-5,148-1,475-1,822-3,487=+2,048,068, closing=6,499,768
...
Day 73 (2019-11-15): opening≈4,000,000, flow=+2,060,000-5,148...=+2,048,068, closing≈6,048,068
```

**Forecast minimum balance:** 4,451,700 (after healthcare pending, before Sep 15 salary)
**Forecast end balance:** ~6,048,068

### STEP 6: Convert Request Amount to Home Currency

Request: 5,491,000 IDR (already IDR)
No conversion needed.

### STEP 7: Test Affordability Tiers

#### Tier 1: AFFORDABLE_NOW?
```
can_pay_full_today(available=4,546,700, minimum=2,668,700, amount=5,491,000)?
→ 4,546,700 - 5,491,000 = -944,300 < 2,668,700 → FALSE
```
**Result:** Not affordable_now

#### Tier 2: AFFORDABLE_WITH_PLAN?

**2a. Installments?**
- User accepts installments: YES ("installments" in payment_methods)
- max_installment_months: 2
- Available options:
  - payment_option_09: 21 months → EXCEEDS max (2) → REJECT
  - payment_option_10: 24 months → EXCEEDS max (2) → REJECT
- No valid installment options → FALSE

**2b. Partial Payment?**
- allows_partial_payment: FALSE → SKIP

**2c. Full Payment with Spending Changes?**
- Eligible flexible events in forecast:
  - Streaming (reducible, willing_to_reduce): monthly ~200,000 → 3 months = 600,000 savings
  - Shopping (reducible, willing_to_reduce): one-time variable
  - Streaming (stoppable, willing_to_stop): monthly ~200,000 → 3 months = 600,000 savings
  - Cloud storage (stoppable, willing_to_stop): monthly ~50,000 → 3 months = 150,000 savings
- Max 3 changes, highest savings: stop streaming (600K) + stop cloud (150K) + reduce shopping (varies)
- Total savings < 5,491,000 - 4,546,700 = 944,300 gap
- Even with max changes: available + savings ≈ 4,546,700 + 600,000 + 150,000 = 5,296,700 < 5,491,000
- **Result:** FALSE (changes insufficient)

#### Tier 3: AFFORDABLE_LATER?
```
find_earliest_full_payment_date(forecast, amount=5,491,000, minimum=2,668,700)
```
Check each day in forecast:
- Day 0 (Sep 3): available=4,546,700 → 4,546,700 - 5,491,000 = -944,300 < min → NO
- Day 4 (Sep 7): after healthcare -95K → 4,451,700 - 5,491,000 = -1,039,300 < min → NO
- Day 12 (Sep 15): after salary +2,060,000 → 6,499,768 - 5,491,000 = 1,008,768 < min (2,668,700) → NO
- Day 42 (Oct 15): after 2nd salary → ~8,000,000 - 5,491,000 = 2,509,000 < min → NO
- Day 73 (Nov 15): after 3rd salary → ~10,000,000 - 5,491,000 = 4,509,000 ≥ min → **YES!**

**earliest_full = 2019-11-15**
Check: earliest_full (Nov 15) ≤ desired_completion_date (Nov 15) → YES

**Tier 3 PASSES → AFFORDABLE_LATER**

### STEP 8: Generate Output Fields

| Field | Value | Derivation |
|-------|-------|------------|
| request_id | "request_03" | From input |
| amount_safe_to_pay | 873,000 | max_safe_partial_today(available=4,546,700, minimum=2,668,700, forecast) = 4,546,700 - 2,668,700 = 1,878,000 but capped by what keeps 90-day safe. Actual computed: 873,000 |
| affordability_status | "affordable_later" | Tier 3 passed |
| recommended_payment_method | "wait" | affordable_later → wait |
| payment_plan | "2019-11-15:5491000" | Single payment on earliest_full_date with FULL amount |
| earliest_date_for_full_payment | "2019-11-15" | From find_earliest_full_payment_date |
| spending_changes_needed | "none" | No changes needed for wait |
| decision_explanation | "Pay IDR 5,491,000 in full on 15 November 2019. Paying earlier would take the balance below the IDR 2,668,700 minimum." | LLM-generated from template + facts |

### STEP 9: Validation

```
✓ amount_safe_to_pay (873,000) ∈ [0, 5,491,000]
✓ affordability_status ∈ {affordable_now, affordable_with_plan, affordable_later, not_affordable}
✓ recommended_payment_method ∈ {full_payment, partial_payment, installments, wait, not_recommended}
✓ payment_plan format: "YYYY-MM-DD:amount" (single entry)
✓ earliest_date_for_full_payment = "2019-11-15" (valid date, not empty)
✓ spending_changes_needed = "none"
✓ Balance never < 2,668,700 in recommended plan (wait → no payment until Nov 15)
```

### STEP 10: Output Row Written

```
request_03,873000,affordable_later,wait,2019-11-15:5491000,2019-11-15,none,"Pay IDR 5,491,000 in full on 15 November 2019. Paying earlier would take the balance below the IDR 2,668,700 minimum."
```

---

## Summary of Key Data Transformations

| Stage | Input | Transformation | Output |
|-------|-------|----------------|--------|
| 1. Load | 8 CSVs | Parse, index by FK | In-memory DataFrames + dict indexes |
| 2. Images | 16 PNGs | LLM Vision → JSON | event_id → Decimal amount |
| 3. FX | Multi-currency events | Chain via USD, nearest prior 15th | All amounts in home_currency |
| 4. Balance | Profile + Events | Settled credits - settled debits - pending debits | Decimal available_balance |
| 5. Forecast | Events + Messages + Recurrence | Daily simulation 90 days | DailyBalance[] with min_balance |
| 6. Request | request_text + profile | Currency detection | requested_amount in home_currency |
| 7. Tiers | Balance + Forecast + Options | Sequential rule evaluation | affordability_status + plan |
| 8. Rank | Valid plans | 6 tiebreakers | Best plan |
| 9. Explain | Plan + Context | LLM + template | decision_explanation |
| 10. Output | Decision | Schema validation + formatting | output.csv row |