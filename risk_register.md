# Risk Register: Top 10 Technical Risks with Mitigations

| # | Risk | Likelihood | Impact | Severity | Mitigation Strategy |
|---|------|------------|--------|----------|---------------------|
| 1 | **OCR Extraction Failure on 16 Critical Images** | High | Critical | 🔴 **CRITICAL** | • Use multiple OCR engines (Tesseract + cloud Vision API as fallback)<br>• Build regex patterns for each known document type (salary slip, invoice, bill)<br>• Manual verification for 16 images — pre-extract and hardcode as fallback<br>• Validate extracted amounts against event context (description, category, currency) |
| 2 | **FX Rate Chaining Errors (Missing Direct Pairs)** | High | Critical | 🔴 **CRITICAL** | • Implement explicit chaining logic: EUR→USD→INR, EUR→USD→IDR, EUR→USD→ZAR<br>• Unit test every currency pair conversion with known sample values<br>• Use Decimal for precision; avoid float rounding errors<br>• Log all conversions for audit; flag any rate_date mismatches |
| 3 | **Incorrect Pending/Scheduled Event Cash Treatment** | High | Critical | 🔴 **CRITICAL** | • Codify rules as constants: RESERVE pending debits, IGNORE pending credits<br>• Build forecast engine with explicit event status handling<br>• Test against samples: request_03, 04, 08, 13, 18, 23 (affordable_later depend on scheduled salary)<br>• Add assertion: no pending credit ever increases available_balance |
| 4 | **Spending Change Eligibility Logic Bugs** | Medium | High | 🟠 **HIGH** | • Build decision matrix: (profile field) × (event flexibility) × (protection status)<br>• Unit test each sample with changes: request_06, 11, 21<br>• Enforce max 3 changes; validate protected categories are NEVER touched<br>• Verify reduction respects minimum_allowed_amount |
| 5 | **Recurrence Detection Over/Under-Forecasting** | Medium | High | 🟠 **HIGH** | • Conservative approach: only project if ≥3 historical occurrences at regular interval<br>• Salary: detect monthly on same day; project forward<br>• Variable expenses (groceries): use 90th percentile of last 6 months<br>• Never project windfall, bonus, gig income, investment gains |
| 6 | **Installment Option Selection Logic Errors** | Medium | High | 🟠 **HIGH** | • Must exactly match a supplied payment_option (dates, amounts, frequency)<br>• Filter: user accepts installments AND months <= max_installment_months<br>• Score: (1) total_payable_amount ASC, (2) first_payment_date ASC, (3) number_of_payments ASC<br>• Test against request_02, 07, 12, 17, 22 |
| 7 | **90-Day Forecast Horizon Boundary Errors** | Medium | High | 🟠 **HIGH** | • Define forecast_end = request_date + 90 days (inclusive)<br>• earliest_date_for_full_payment must be ≤ forecast_end for affordable_later<br>• For not_affordable: if earliest_full > forecast_end → empty string<br>• Test boundary: request_14 (partial safe but completion > 90 days = not_affordable) |
| 8 | **Currency Detection from Request Text** | Medium | Medium | 🟡 **MEDIUM** | • Parse request_text for currency keywords: ZAR, IDR, EUR, USD, INR, Rands, Rupiah, Euros, Dollars, Rupees<br>• Cross-reference with user home_currency and requested_amount magnitude<br>• Default: assume request currency = user home_currency if ambiguous |
| 9 | **Message Parsing Reliability (Mixed Languages)** | Medium | Medium | 🟡 **MEDIUM** | • Build bilingual regex for amounts: \d{1,3}(?:[.,]\d{3})*(?:[.,]\d{2})?\s*(?:IDR|EUR|USD|ZAR|INR|Rp|€|\$|R)\b<br>• Extract: salary changes, bonus status, refund confirmations, payout dates<br>• Weight: employer > bank > financial_service > service_provider > merchant<br>• Never override settled events with message claims |
| 10 | **Output Format Non-Compliance** | Low | Critical | 🔴 **CRITICAL** | • Strict schema validation before write<br>• Enum checks: affordability_status ∈ {4 values}, recommended_payment_method ∈ {5 values}<br>• payment_plan: "none" or "DATE:AMT|DATE:AMT" (pipe, no spaces around pipe)<br>• spending_changes_needed: "none" or "stop:event_X|reduce_to:event_Y:AMT"<br>• earliest_date_for_full_payment: "" (empty) for not_affordable<br>• amount_safe_to_pay: 0 ≤ value ≤ requested_amount |

---

## Additional Risks (11-15)

| # | Risk | Likelihood | Impact | Severity | Mitigation |
|---|------|------------|--------|----------|------------|
| 11 | **Linked Event Chain Misinterpretation** | Medium | Medium | 🟡 | • Build explicit handlers for 5 chain types (refund-expense, retry, valuation, sale, reimbursement)<br>• Test on all 58 linked pairs |
| 12 | **Partial Payment Date Logic (request_19 pattern)** | Low | High | 🟠 | • Verify: partial today + remainder on earliest_full ≤ desired_completion_date<br>• Two payments MUST sum to requested_amount exactly |
| 13 | **Profile Missing Field Defaults** | High | Medium | 🟡 | • willing_to_reduce/stop NaN → empty list<br>• max_installment_months NaN → installments not allowed |
| 14 | **Performance: 250 Requests × 25K Events × Forecast** | Medium | Medium | 🟡 | • Pre-compute user cash positions and forecasts<br>• Index events by user_id and date<br>• Target < 30 seconds total runtime |
| 15 | **Determinism Across Runs** | Low | High | 🟠 | • Fix random seeds; avoid non-deterministic libraries<br>• Sort all collections before iteration<br>• Use Decimal not float for money |

---

## Risk Mitigation Priority Order

### Phase 1 (Must Fix Before Any Implementation)
1. **Risk 1** — Build OCR pipeline and pre-extract 16 images
2. **Risk 2** — Implement and unit-test FX conversion with chaining
3. **Risk 3** — Build cash flow engine with correct pending/scheduled logic

### Phase 2 (Core Algorithm)
4. **Risk 4** — Spending change eligibility engine
5. **Risk 5** — Conservative recurrence detection
6. **Risk 6** — Installment selection algorithm

### Phase 3 (Boundary & Format)
7. **Risk 7** — 90-day forecast boundary handling
8. **Risk 10** — Output schema validation

### Phase 4 (Quality)
9. **Risk 8** — Currency detection from text
10. **Risk 9** — Message parsing
11. **Risk 11** — Linked event chains
12. **Risk 12** — Partial payment logic
13. **Risk 13** — Profile defaults
14. **Risk 14** — Performance optimization
15. **Risk 15** — Determinism verification

---

## Validation Checklist (Pre-Submission)

- [ ] All 25 sample_requests reproduce exactly (amount_safe_to_pay, status, method, plan, date, changes, explanation)
- [ ] Output.csv has 250 rows, 8 columns, no NaN/None
- [ ] Every amount_safe_to_pay ∈ [0, requested_amount]
- [ ] Every affordability_status ∈ {affordable_now, affordable_with_plan, affordable_later, not_affordable}
- [ ] Every recommended_payment_method ∈ {full_payment, partial_payment, installments, wait, not_recommended}
- [ ] payment_plan = "none" or valid pipe-separated DATE:AMOUNT entries
- [ ] spending_changes_needed = "none" or valid pipe-separated actions
- [ ] earliest_date_for_full_payment = "" for not_affordable; valid date otherwise
- [ ] No balance ever drops below minimum_balance_to_keep in recommended plan
- [ ] Runtime < 60 seconds on full dataset
- [ ] Code is deterministic (same output on re-run)
- [ ] No hardcoded sample values used for evaluation requests
- [ ] All 16 image amounts extracted and validated
- [ ] FX conversions logged and auditable