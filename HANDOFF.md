# HANDOFF: Phase 0 Dataset Analysis Complete

## Summary of Findings

### Dataset Scale
- **250 evaluation requests** (request_26 through request_275)
- **25 labeled samples** (request_01-25) — complete ground truth for all output fields
- **275 users** with financial profiles
- **25,342 financial events** across 7 event types, 6 statuses, 21 categories
- **134 exchange rate rows** — monthly snapshots, 5 currency pairs (requires USD chaining)
- **790 payment options** — 2-4 per request (full_payment + installments)
- **215 messages** — 128 linked to requests, 39 to events
- **16 images** — all linked to events with blank amounts (require OCR)

### Key Technical Insights

1. **Decision Logic is Deterministic**: 25 samples reveal clear tiered affordability logic (affordable_now → affordable_with_plan → affordable_later → not_affordable) with explicit rules for each output field.

2. **Cash Flow Rules are Asymmetric**: 
   - Pending debits: RESERVE (reduce available balance)
   - Pending credits: IGNORE (don't count until settled)
   - Scheduled income: COUNT on settlement_date in forecast
   - Unrealized gains: NEVER count

3. **Currency Handling Requires Chaining**: No direct EUR→INR or EUR→IDR rates. Must chain EUR→USD→INR/IDR/ZAR. Rates only on 15th of month — use nearest prior 15th for settlement dates.

4. **Spending Changes are Highly Constrained**: Max 3 changes, only on non-protected categories user explicitly allows, only on flexible events (reducible/stoppable), respect minimum_allowed_amount.

5. **16 Events Need OCR**: All blank amounts are INR (except 1 USD). These affect 16 users' cash positions. Pre-extraction recommended.

---

## Decisions Phase 1 (Architecture) Must Make

Based on these findings, the architecture phase must decide:

| Decision | Options | Recommendation |
|----------|---------|----------------|
| **OCR Strategy** | Tesseract local / Cloud Vision API / Manual pre-extraction | **Pre-extract all 16 manually** — highest reliability, one-time cost |
| **FX Engine** | Custom chaining logic / Library (forex-python) | **Custom** — only 5 pairs, fixed monthly rates, chaining is explicit |
| **Forecast Horizon** | Rolling 90-day / Calendar quarter / Request_date + 90 | **Request_date + 90 days inclusive** — matches problem statement |
| **Recurrence Detection** | Statistical (ARIMA) / Rule-based (interval detection) / Conservative (3+ occurrences) | **Conservative rule-based** — salary monthly, subscriptions fixed, variable = recent p90 |
| **Language** | Python / TypeScript / Other | **Python** — pandas for data, rich OCR/ML ecosystem, `code/main.py` entry point |
| **Architecture Pattern** | Single-pass per request / Pre-compute user states / Event-driven | **Pre-compute user cash positions + 90-day forecasts** — 250 requests × 275 users, reuse forecasts |
| **Validation** | Unit tests on samples / Integration test / Property-based | **Unit test all 25 samples exact match** — primary correctness gate |

---

## File Manifest

| File | Description | Status |
|------|-------------|--------|
| `dataset_analysis.md` | Complete dataset characterization (all 9 CSVs + images) | ✅ Created |
| `schema_diagram.txt` | ASCII join diagram with all FK relationships | ✅ Created |
| `decision_rules.md` | Inferred affordability algorithm + pseudocode + sample mapping | ✅ Created |
| `edge_cases.md` | 18 categories of edge cases with handling rules | ✅ Created |
| `risk_register.md` | Top 15 risks with severity, mitigation, priority order | ✅ Created |

---

## Resolved Questions (No Open Issues)

| Question | Resolution |
|----------|------------|
| How to handle missing exchange rate pairs? | Chain via USD (EUR→USD→INR/IDR/ZAR) using rates from same or prior month |
| How to treat pending credits? | Ignore — only count settled credits |
| How to treat pending debits? | Reserve immediately — reduce available balance |
| What forecast horizon? | request_date + 90 days inclusive |
| Can we use sample_requests for training? | NO — only for validation. Evaluation requests are request_26-275 (no overlap) |
| How many spending changes max? | 3 (per output spec) |
| What if user max_installment_months is blank? | Installments not allowed for that user |
| Are investment_valuations available cash? | NO — non_cash/unrealized, never count |
| How to parse mixed-language messages? | Bilingual regex for amounts; weight sources by reliability |
| What if payment_option first_payment_date < request_date? | Option invalid — skip |

---

## Next Steps for Phase 1 (Architecture)

1. **Design data models** — UserState, CashForecast, RequestContext, DecisionOutput
2. **Implement FX conversion module** with chaining and unit tests
3. **Build cash flow engine** — reconstruct balance, forecast 90 days, handle all event statuses
4. **Create OCR extraction script** for 16 images (or manual extraction table)
5. **Implement spending change optimizer** — eligibility matrix + greedy selection
6. **Build installment selector** — filter by user prefs, score by cost/start/payments
7. **Write validation harness** — run all 25 samples, assert exact output match
8. **Design main pipeline** — load → precompute → decide 250 → write output.csv

---

## Ready for Architecture Phase

All data characterized. No open questions. Analysis documents provide complete specification for implementation.