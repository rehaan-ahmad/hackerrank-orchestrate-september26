# Edge Cases Inventory

## 1. Zero/Near-Zero Balance Scenarios
| Case | Description | Handling |
|------|-------------|----------|
| 1.1 | `current_available_balance` = 0 or < minimum_balance_to_keep | amount_safe_to_pay = 0; not_affordable unless confirmed income arrives same day |
| 1.2 | Balance exactly equals minimum_balance_to_keep | No payment possible today; check forecast for incoming funds |
| 1.3 | Negative available balance (overdraft not in data but possible via pending) | Treat as 0 available; reserve pending debits |

## 2. Multi-Currency Complexity
| Case | Description | Handling |
|------|-------------|----------|
| 2.1 | Request currency ≠ user home_currency (e.g., request in EUR, user in ZAR) | Convert request_amount using exchange_rates on request_date |
| 2.2 | Financial events in multiple currencies | Convert ALL events to home_currency using settlement_date rates |
| 2.3 | Missing direct FX pair (e.g., EUR→INR not in table) | Chain via USD: EUR→USD × USD→INR (both pairs exist from 2024-04) |
| 2.4 | Settlement date not on 15th (exchange_rates only on 15th) | Use nearest PRIOR 15th rate (e.g., settlement 2024-03-11 → use 2024-02-15 rate) |
| 2.5 | Event settlement_date before first exchange rate (2023-10-15) | No events before 2023-10 in data; but if so, use earliest available rate |
| 2.6 | Request currency not explicitly stated in request_text | Infer from requested_amount magnitude and user home_currency; check request_text for currency mentions (ZAR, IDR, EUR, USD, INR) |

## 3. Image-Only Amounts (16 Events)
| Case | Description | Handling |
|------|-------------|----------|
| 3.1 | Event.amount is NaN, linked image exists | **Must OCR extract** — 16 events across 16 images |
| 3.2 | Image contains handwritten/receipt amounts | Use OCR (Tesseract/Vision API) to parse amount and currency |
| 3.3 | Image quality poor / amount ambiguous | Flag for manual review; use conservative (lower) estimate |
| 3.4 | Image shows different currency than event.currency | Trust image content over event.currency field |
| 3.5 | Multiple amounts in image (e.g., invoice with tax) | Extract total payable amount; match to event description |

**Event-Image Mapping (ALL require extraction):**
- event_253 (user_03): August 2019 net salary — INR
- event_1442 (user_16): Outstanding rent balance — INR
- event_1545 (user_17): Bulk groceries purchase — INR
- event_1700 (user_19): Delivered grocery order — INR
- event_1786 (user_20): Outstanding telecom bill — INR
- event_3051 (user_33): Grocery tax invoice — INR
- event_3231 (user_35): Restaurant tax invoice — INR
- event_4535 (user_48): Property maintenance invoice — INR
- event_5170 (user_55): Water bill due — INR
- event_6033 (user_64): Large grocery tax invoice — INR
- event_6859 (user_73): Hospital bill payable — INR
- event_7307 (user_78): Taxi fare — USD
- event_7941 (user_84): Tote bag order — INR
- event_9421 (user_101): Pharmacy purchase — INR
- event_9806 (user_105): Airline ticket purchase — INR
- event_10521 (user_113): EV charging wallet payment — INR

## 4. Conflicting/Untrusted Messages
| Case | Description | Handling |
|------|-------------|----------|
| 4.1 | Employer message says "salary increased" but no settled event yet | Do NOT count until settled event appears; treat as unconfirmed |
| 4.2 | Message says "bonus pending" but amount/date unknown | Ignore — per rules: "Do not count pending credits, bonuses, commissions" |
| 4.3 | Merchant says "refund processed" but event status=pending | Reserve the refund; only count when status=settled |
| 4.4 | Service provider says "payout pending" with variable amount | Ignore until settled; gig income is uncertain |
| 4.5 | Bank alert shows transaction but no matching event | Cross-reference with financial_events; if new, add as pending |
| 4.6 | Message in Indonesian vs English | Parse both; use regex for amounts (IDR/EUR/USD/ZAR/INR patterns) |
| 4.7 | Message contradicts settled event (e.g., "payment failed" but event=settled) | Trust settled event; message is untrusted evidence |
| 4.8 | Message references event_id not in financial_events | Ignore — only 39 messages have valid related_event_id |

## 5. Recurring Event Detection
| Case | Description | Handling |
|------|-------------|----------|
| 5.1 | Monthly salary (most users) | Detect: same category=salary, monthly interval, same user → project forward |
| 5.2 | Weekly/biweekly groceries/transport | Detect frequency from history; forecast conservatively (use recent average) |
| 5.3 | Subscriptions (streaming, cloud, gym) | Fixed amount, monthly; event_type=subscription; project unless cancelled |
| 5.4 | Debt repayments (monthly installments) | Fixed schedule; linked_event_id chains may show pattern |
| 5.5 | Irregular income (windfall, freelance) | Do NOT project forward — only count confirmed/scheduled |
| 5.6 | Seasonal expenses (annual insurance, quarterly tax) | Detect from history if ≥2 occurrences; else treat as one-time |

## 6. Linked Event Chains
| Case | Description | Handling |
|------|-------------|----------|
| 6.1 | Refund ↔ Original expense (card reversal) | Pair them; net effect = 0 if both settled; if refund pending, reserve original |
| 6.2 | Debt payment retry (failed → scheduled) | Only count the retry if scheduled/settled; ignore failed |
| 6.3 | Investment valuation ↔ Purchase | Valuation is non_cash/unrealized — **never count as available cash** |
| 6.4 | Investment sale ↔ Purchase | Sale proceeds are credit; count when settled |
| 6.5 | Employer reimbursement ↔ Work expense | Reimbursement is credit; net against expense when both settled |

## 7. Pending/Scheduled Event Handling
| Case | Description | Handling |
|------|-------------|----------|
| 7.1 | Pending debit (expense) | **Reserve** — reduce available balance immediately |
| 7.2 | Pending credit (refund, salary) | **Do NOT count** — wait for settled |
| 7.3 | Scheduled income (salary) | Include in forecast ON settlement_date only |
| 7.4 | Scheduled expense | Include in forecast ON settlement_date |
| 7.5 | Cancelled event | Ignore completely |
| 7.6 | Failed event | Ignore completely |
| 7.7 | Unrealized investment gain | **Never count as available cash** |

## 8. Spending Change Constraints
| Case | Description | Handling |
|------|-------------|----------|
| 8.1 | User willing to reduce category but event is "fixed" | Cannot change — flexibility field overrides preference |
| 8.2 | User willing to stop category but event has no minimum_allowed_amount | Can stop entirely (stoppable) |
| 8.3 | Reduce would go below minimum_allowed_amount | Cap at minimum_allowed_amount |
| 8.4 | Protected category appears in willing_to_reduce/stop | Protected takes precedence — cannot change |
| 8.5 | More than 3 eligible changes needed | Only pick top 3 by savings impact |
| 8.6 | Event is one-time (not recurring) but flexible | Can still reduce/stop if in willing categories |
| 8.7 | Subscription in willing_to_stop but user needs it | Preference is user-stated — honor it even if seems essential |

## 9. Payment Option Constraints
| Case | Description | Handling |
|------|-------------|----------|
| 9.1 | Installment option exceeds user's max_installment_months | Reject option |
| 9.2 | User doesn't accept installments but only installments available | Cannot recommend installments → not_affordable or wait |
| 9.3 | Installment first_payment_date < request_date | Invalid — option not usable |
| 9.4 | Installment total_payable_amount > requested_amount significantly | Financing fee makes it expensive; still valid if user accepts |
| 9.5 | Partial payment allowed but user doesn't accept partial_payment | Cannot recommend partial_payment |
| 9.6 | No full_payment option in payment_options (only installments) | Full payment still possible at requested_amount if user accepts |
| 9.7 | Multiple installment options — which to choose? | Per rules: minimize total cost, then earliest start, then fewest payments |

## 10. Date Edge Cases
| Case | Description | Handling |
|------|-------------|----------|
| 10.1 | request_date > desired_completion_date | Not in data; if so, treat as invalid |
| 10.2 | desired_completion_date > 90 days out | Forecast only 90 days; if earliest_full > 90 days → not_affordable |
| 10.3 | Settlement date in future but before request_date | Impossible; data should be consistent |
| 10.4 | Events with settlement_date = NaN (10 events) | Use event_date as fallback; if both NaN, ignore |
| 10.5 | Historical events before 2023 (earliest exchange rate) | No events before 2023-10 in data |

## 11. Profile Field Missing Values
| Case | Description | Handling |
|------|-------------|----------|
| 11.1 | expense_categories_user_is_willing_to_reduce = NaN (39 users) | Treat as empty — no categories eligible for reduction |
| 11.2 | expense_categories_user_is_willing_to_stop = NaN (62 users) | Treat as empty — no categories eligible for stopping |
| 11.3 | max_installment_months = NaN (119 users) | User will NOT consider installments (even if installments in payment_methods) |
| 11.4 | payment_methods_user_will_consider missing | Not in data — 0 missing |

## 12. Investment Event Handling
| Case | Description | Handling |
|------|-------------|----------|
| 12.1 | investment_valuation (non_cash, unrealized) | **Exclude from cash flow** — not available for spending |
| 12.2 | investment_purchase (debit) | Count as expense when settled |
| 12.3 | investment_sale (credit) | Count as income when settled |
| 12.4 | Request type = "investment" | Treat as purchase — user wants to allocate cash to investment |

## 13. Request Type Specific Logic
| Type | Special Consideration |
|------|----------------------|
| family_transfer | Often allows_partial_payment; treat as expense (debit) |
| purchase | Standard expense; check if allows_partial |
| investment | User allocating savings; may be more flexible on timing |
| debt_repayment | Reduces liability; may have priority in financial_priorities |
| travel | Often large amount, allows_partial_payment varies |
| housing | Deposit/rent; often essential (protected category) |
| education | May be in financial_priorities; protected category often |
| emergency_expense | Time-sensitive; may not allow wait |
| other | Generic; no special rules |

## 14. Amount Precision & Rounding
| Case | Description | Handling |
|------|-------------|----------|
| 14.1 | Installment amounts don't divide evenly (e.g., 46,018,000 / 3) | Use exact payment_amount from payment_options (already computed) |
| 14.2 | FX conversion produces long decimals | Keep full precision in computation; round to 2 decimals for output |
| 14.3 | payment_plan amounts must sum to requested_amount (for partial) | Verify: partial + remainder == requested_amount exactly |
| 14.4 | amount_safe_to_pay > requested_amount | Cap at requested_amount |

## 15. Output Format Edge Cases
| Case | Description | Required Format |
|------|-------------|-----------------|
| 15.1 | earliest_date_for_full_payment empty | Empty string (not "none", not NaN) |
| 15.2 | payment_plan = none | Literal string "none" |
| 15.3 | spending_changes_needed = none | Literal string "none" |
| 15.4 | payment_plan multiple entries | "YYYY-MM-DD:amount\|YYYY-MM-DD:amount" (pipe separator) |
| 15.5 | spending_changes multiple | "stop:event_XXX\|reduce_to:event_YYY:amount" (pipe separator) |
| 15.6 | affordability_status values | EXACTLY: affordable_now, affordable_with_plan, affordable_later, not_affordable |
| 15.7 | recommended_payment_method values | EXACTLY: full_payment, partial_payment, installments, wait, not_recommended |

## 16. Complex Interaction Cases (Highest Risk)
| Case | Description | Why Hard |
|------|-------------|----------|
| 16.1 | Foreign currency request + multi-currency events + missing FX pair + image amounts | Requires correct chaining, OCR, and forecast all in sync |
| 16.2 | User has max_installment_months=2 but only 12-month installment option | Must reject installments; fall back to wait/partial/not_affordable |
| 16.3 | Pending salary + pending large expense both in forecast window | Net effect uncertain; must reserve debit, ignore credit |
| 16.4 | Spending change on subscription affects 90-day forecast recurring | Must project savings for each future occurrence |
| 16.5 | Message confirms salary increase but effective date after request_date | Only include in forecast from effective date |
| 16.6 | Multiple messages for same request contradict | Use conflict resolution: explicit cancellation > newer > settled > safer |
| 16.7 | Request allows_partial but user doesn't accept partial_payment | Cannot use partial_payment even if mathematically optimal |

## 17. Data Quality Issues Found
| Issue | Count | Impact |
|-------|-------|--------|
| financial_events.amount NaN | 16 | Requires OCR |
| financial_events.settlement_date NaN | 10 | Use event_date |
| financial_events.minimum_allowed_amount NaN | 22,435 | Only for flexible events |
| financial_profiles.willing_to_reduce NaN | 39 | No reductions allowed |
| financial_profiles.willing_to_stop NaN | 62 | No stops allowed |
| financial_profiles.max_installment_months NaN | 119 | No installments allowed |
| exchange_rates missing pairs for some months | Variable | Must chain via USD |

## 18. Decision Boundary Tests (from samples)
| Boundary | Test Case | Expected |
|----------|-----------|----------|
| Balance == minimum after payment | request_01: 58,481 - 25,256 = 33,225 > 18,000 | affordable_now |
| Balance < minimum if pay today, but salary arrives before deadline | request_03: wait until Nov 15 | affordable_later |
| Partial safe today but can't complete in 90 days | request_14, 24 | not_affordable |
| Installment months > user max_months | Check per user | Reject installment |
| Spending change on protected category | Never allowed | Skip |

---

## Summary: Top 5 Most Critical Edge Cases to Handle

1. **16 image-dependent events** — OCR pipeline must work reliably
2. **FX chaining (EUR→USD→INR/ZAR)** — Missing direct pairs common
3. **Pending debit vs pending credit asymmetry** — Reserve debits, ignore credits
4. **Spending changes limited to 3, non-protected, flexible only** — Complex eligibility
5. **90-day forecast horizon with recurrence detection** — Must not over-project income