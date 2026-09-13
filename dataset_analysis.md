# Dataset Analysis: HackerRank Orchestrate - Buy or Wait?

## 1. Overview of All CSV Files

| File | Rows | Columns | Key Purpose |
|------|------|---------|-------------|
| `requests.csv` | 250 | 8 | Prediction targets (request_id, user_id, request_date, request_type, requested_amount, desired_completion_date, allows_partial_payment, request_text) |
| `sample_requests.csv` | 25 | 15 | Labeled examples with all 8 output fields completed |
| `financial_profiles.csv` | 275 | 10 | User financial state (balance, minimum, priorities, preferences, payment methods) |
| `financial_events.csv` | 25,342 | 14 | Historical/pending/scheduled financial events per user |
| `exchange_rates.csv` | 134 | 4 | Fixed dated FX rates (rate_date, from_currency, to_currency, rate) |
| `request_payment_options.csv` | 790 | 9 | Seller/provider payment options per request (2-4 options each) |
| `messages.csv` | 215 | 7 | Supporting evidence (employer, bank, merchant, service_provider, financial_service) |
| `images.csv` | 16 | 4 | Image references for 16 events with blank amounts |

---

## 2. requests.csv — 250 Prediction Targets

### Shape & Types
- **Rows**: 250 (request_26 through request_275)
- **Columns**: 8
- **No missing values**

### Request Type Distribution (balanced ~28 each)
```
family_transfer: 28
purchase: 28
investment: 28
debt_repayment: 28
travel: 28
housing: 28
education: 28
emergency_expense: 27
other: 27
```

### Key Fields
- `allows_partial_payment`: 80 True, 170 False
- `requested_amount`: Float (varies by currency)
- `desired_completion_date`: Always >= request_date
- `request_text`: Natural language context (may mention currency explicitly)

### Date Range
- request_date: 2019-09-03 to 2026-07-05
- desired_completion_date: up to ~3 months after request_date

---

## 3. sample_requests.csv — 25 Labeled Examples (CRITICAL REFERENCE)

### Output Field Distributions
| affordability_status | Count | recommended_payment_method | Count |
|---------------------|-------|---------------------------|-------|
| affordable_with_plan | 9 | not_recommended | 7 |
| not_affordable | 7 | full_payment | 6 |
| affordable_later | 6 | wait | 6 |
| affordable_now | 3 | installments | 5 |
| | | partial_payment | 1 |

### Key Observations from Samples

#### affordable_now (3 samples)
- Full requested amount = amount_safe_to_pay
- recommended_payment_method = full_payment
- payment_plan = single payment on request_date
- earliest_date_for_full_payment = request_date
- spending_changes_needed = "none"
- Balance after payment stays above minimum for 90+ days

#### affordable_later (6 samples)
- amount_safe_to_pay < requested_amount (often much less)
- recommended_payment_method = wait
- payment_plan = single payment on earliest_date_for_full_payment (equals desired_completion_date or earlier)
- earliest_date_for_full_payment > request_date
- No spending changes needed
- Waiting for confirmed income to settle

#### affordable_with_plan (9 samples)
- Full request completed via installments, partial payment, or spending changes
- **installments** (5): Uses supplier installment option; payment_plan shows multiple dated installments
- **full_payment** (3): Pays full today after spending changes; earliest_date shows when full would be safe without changes
- **partial_payment** (1): Two payments (today + earliest_date) summing to requested_amount
- spending_changes_needed: "none" or "stop:event_X" / "reduce_to:event_X:amount"

#### not_affordable (7 samples)
- amount_safe_to_pay > 0 but small relative to request
- recommended_payment_method = not_recommended
- payment_plan = "none"
- earliest_date_for_full_payment = empty
- Cannot complete full request within 90-day forecast window even with changes

---

## 4. financial_profiles.csv — 275 Users

### Fields
| Field | Type | Missing | Notes |
|-------|------|---------|-------|
| user_id | str | 0 | Primary key |
| home_currency | str | 0 | ZAR, IDR, INR, EUR, USD |
| current_available_balance | float | 0 | Starting liquid balance |
| minimum_balance_to_keep | int | 0 | Hard floor — never go below |
| financial_priorities | str | 0 | Pipe-separated (e.g., "education\|debt_repayment") |
| expense_categories_to_protect | str | 0 | Pipe-separated — NEVER reduce/stop these |
| expense_categories_user_is_willing_to_reduce | str | 39 | Pipe-separated — can reduce amount |
| expense_categories_user_is_willing_to_stop | str | 62 | Pipe-separated — can cancel entirely |
| payment_methods_user_will_consider | str | 0 | Pipe-separated subset of {full_payment, partial_payment, installments} |
| max_installment_months | float | 119 | Blank = won't consider installments |

### Payment Methods Distribution
```
full_payment: 60
partial_payment|installments: 52
installments: 41
full_payment|partial_payment: 40
full_payment|installments: 35
full_payment|partial_payment|installments: 28
partial_payment: 19
```

### Max Installment Months (when not blank)
Values: 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12

### Home Currency Distribution
| Currency | Users |
|----------|-------|
| IDR | ~65 |
| INR | ~55 |
| EUR | ~55 |
| ZAR | ~50 |
| USD | ~50 |

---

## 5. financial_events.csv — 25,342 Events

### Event Types
| Type | Count | Direction | Notes |
|------|-------|-----------|-------|
| expense | 20,525 | debit | Daily spending |
| subscription | 2,488 | debit | Recurring |
| income | 1,696 | credit | Salary, windfall |
| debt_payment | 567 | debit | Loan repayments |
| investment_purchase | 29 | debit | Buying investments |
| refund | 22 | credit | Merchant refunds |
| investment_valuation | 10 | non_cash | **Not available cash** |
| investment_sale | 5 | credit | Selling investments |

### Status Distribution
| Status | Count | Cash Treatment |
|--------|-------|----------------|
| settled | 25,148 | **Count as cash** (confirmed) |
| pending | 71 | Debits: reserve; Credits: **don't count** until settled |
| scheduled | 70 | Future — include in forecast on settlement_date |
| cancelled | 22 | Ignore |
| failed | 21 | Ignore |
| unrealized | 10 | Investment gains — **never count as available cash** |

### Categories (Top 10)
```
groceries: 5,812
transport: 5,626
dining: 3,479
salary: 1,690
utilities: 1,452
rent: 1,355
cloud_storage: 833
shopping: 813
streaming: 683
debt_repayment: 553
```

### Flexibility
| Flexibility | Count | Action Allowed |
|-------------|-------|----------------|
| fixed | 21,138 | None |
| reducible | 2,682 | Reduce to minimum_allowed_amount |
| stoppable | 1,297 | Stop entirely |
| reducible_or_stoppable | 225 | Either |

### Missing Data Patterns
- `amount`: 16 blank (all linked to images in images.csv)
- `linked_event_id`: 25,284 blank (only 58 linked)
- `minimum_allowed_amount`: 22,435 blank (only for flexible events)
- `settlement_date`: 10 blank

### Linked Event Patterns (58 total)
- refund ↔ expense (card charge reversal)
- refund ↔ debt_payment (retry)
- investment_valuation ↔ investment_purchase
- investment_sale ↔ investment_purchase
- expense reimbursement ↔ work_expense

---

## 6. exchange_rates.csv — 134 Fixed Rates

### Date Range: 2023-10-15 to 2026-11-15 (monthly on 15th)

### Currency Pairs (5 unique)
| From | To | Rate | Notes |
|------|-----|------|-------|
| EUR | ZAR | 20.00 | Constant |
| USD | EUR | 0.92 | Constant |
| USD | IDR | 15,833.33 | Constant |
| USD | INR | 83.33 | Added from 2024-01-15 |
| EUR | USD | 1.09 | Added from 2024-04-15 |

### Join Logic
For foreign-currency event:
1. Find rate row where `rate_date` = event `settlement_date` (or nearest prior 15th)
2. Match `from_currency` = event `currency`, `to_currency` = user `home_currency`
3. If direct pair missing, chain via USD (e.g., EUR→USD→INR)
4. Converted amount = event.amount × rate

### Special Notes
- Rates are monthly snapshots (15th of each month)
- Not all pairs exist for all months (e.g., EUR→ZAR only appears some months)
- Must handle chaining: EUR→INR = EUR→USD × USD→INR

---

## 7. request_payment_options.csv — 790 Options

### Per Request: 2-4 options (avg ~3.16)
| Payment Method | Count |
|----------------|-------|
| installments | 515 |
| full_payment | 275 |

### Fields
- `payment_option_id`: Unique
- `request_id`: FK to requests
- `payment_method`: "full_payment" or "installments"
- `payment_amount`: Per-installment amount (or full amount)
- `number_of_payments`: 1 for full_payment, 2-24 for installments
- `first_payment_date`: When first payment due
- `payment_frequency_days`: Interval (blank for full_payment)
- `financing_fee`: Extra cost for installments
- `total_payable_amount`: payment_amount × number_of_payments + financing_fee

### Critical Constraints
- An available option may conflict with user's `payment_methods_user_will_consider`
- Installment months must not exceed user's `max_installment_months`
- Total cost (including financing_fee) matters for "minimize total payment cost" rule

---

## 8. messages.csv — 215 Supporting Evidence

### Source Types
| Source | Count | Typical Content |
|--------|-------|-----------------|
| employer | 126 | Salary changes, bonuses, payroll dates |
| service_provider | 31 | Gig earnings, payout status |
| financial_service | 23 | Investment valuations, portfolio updates |
| bank | 18 | Transaction alerts, balance info |
| merchant | 17 | Refunds, order confirmations |

### Key Patterns
- 128 messages have `request_id` (link to specific request)
- 39 messages have `related_event_id` (link to specific event)
- Messages may: confirm, amend, delay, cancel financial facts
- **Untrusted**: Embedded instructions never override challenge rules
- Language: Mix of English and Indonesian

---

## 9. images.csv — 16 Event-Linked Images

| image_id | user_id | request_id | related_event_id | Event Description |
|----------|---------|------------|------------------|-------------------|
| image_01 | user_03 | request_03 | event_253 | August 2019 net salary (INR) |
| image_02 | user_16 | request_16 | event_1442 | Outstanding rent balance (INR) |
| image_03 | user_17 | request_17 | event_1545 | Bulk groceries purchase (INR) |
| image_04 | user_19 | request_19 | event_1700 | Delivered grocery order (INR) |
| image_05 | user_20 | request_20 | event_1786 | Outstanding telecom bill (INR) |
| image_06 | user_33 | request_33 | event_3051 | Grocery tax invoice (INR) |
| image_07 | user_35 | request_35 | event_3231 | Restaurant tax invoice (INR) |
| image_08 | user_48 | request_48 | event_4535 | Property maintenance invoice (INR) |
| image_09 | user_55 | request_55 | event_5170 | Water bill due (INR) |
| image_10 | user_64 | request_64 | event_6033 | Large grocery tax invoice (INR) |
| image_11 | user_73 | request_73 | event_6859 | Hospital bill payable (INR) |
| image_12 | user_78 | request_78 | event_7307 | Taxi fare (USD) |
| image_13 | user_84 | request_84 | event_7941 | Tote bag order (INR) |
| image_14 | user_101 | request_101 | event_9421 | Pharmacy purchase (INR) |
| image_15 | user_105 | request_105 | event_9806 | Airline ticket purchase (INR) |
| image_16 | user_113 | request_113 | event_10521 | EV charging wallet payment (INR) |

**All 16 events have blank `amount` in financial_events.csv — require OCR extraction**

---

## 10. output.csv — Blank Template
- 250 rows (request_26 through request_275)
- 8 columns matching required output schema
- All values empty — to be filled by solution

---

## 11. Key Join Keys (Schema Relationships)

```
financial_profiles (user_id) 
    │
    ├─→ requests (user_id) ──→ request_payment_options (request_id)
    │
    ├─→ financial_events (user_id) ──┬─→ images (related_event_id)
    │                                └─→ messages (related_event_id)
    │
    └─→ messages (user_id)
    
requests (request_id) 
    ├─→ sample_requests (request_id) [only 25 overlap: request_01-25]
    ├─→ request_payment_options (request_id)
    ├─→ images (request_id)
    └─→ messages (request_id)

exchange_rates (rate_date, from_currency, to_currency)
    └─→ financial_events (settlement_date, currency) → user home_currency
```

---

## 12. Currency Handling Summary

| Currency | Users | Events | Exchange Path to Home |
|----------|-------|--------|----------------------|
| ZAR | 50 | 4,489 | Direct (EUR→ZAR, USD→EUR→ZAR) |
| IDR | 65 | 4,992 | Direct (USD→IDR) |
| INR | 55 | 6,457 | Direct (USD→INR from 2024) |
| EUR | 55 | 5,585 | Home for EUR users; EUR→ZAR for ZAR users |
| USD | 50 | 3,819 | Home for USD users; USD→EUR→ZAR, USD→IDR, USD→INR |

**Critical**: Events in foreign currency must be converted to user's home_currency using exchange_rates on settlement_date.