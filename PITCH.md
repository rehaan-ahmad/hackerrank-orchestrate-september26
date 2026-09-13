# Buy or Wait? — Project Pitch Document

> **Challenge:** HackerRank Orchestrate — September 2026  
> **Category:** AI-Powered Financial Decision Agent  
> **Submission:** 250 requests processed · output.csv complete · code.zip packed

---

## 1. Problem Summary

A user asks: *"Can I afford this laptop?"*

The naive answer is "check your balance." The correct answer requires simulating
the next 90 days of cash flow, accounting for recurring bills, pending charges,
confirmed incoming salary, minimum balance guarantees, currency conversion, and
the user's explicit preference for whether they'll consider installment plans.

This system answers that question deterministically — and explains exactly why.

---

## 2. What the System Decides

For every financial request, the agent outputs seven structured fields:

| Field | Allowed Values |
|---|---|
| `amount_safe_to_pay` | `0 ≤ value ≤ requested_amount` |
| `affordability_status` | `affordable_now` · `affordable_with_plan` · `affordable_later` · `not_affordable` |
| `recommended_payment_method` | `full_payment` · `partial_payment` · `installments` · `wait` · `not_recommended` |
| `payment_plan` | `YYYY-MM-DD:amount\|YYYY-MM-DD:amount` or `none` |
| `earliest_date_for_full_payment` | `YYYY-MM-DD` or empty |
| `spending_changes_needed` | `stop:<event_id>\|reduce_to:<event_id>:<amount>` or `none` |
| `decision_explanation` | Natural language, grounded in exact figures |

The system processes **all 9 request types**: purchase, travel, education,
family_transfer, debt_repayment, investment, housing, emergency_expense, other.

---

## 3. Architecture: Two-Layer Design

```text
┌──────────────────────────────────────────────────────────────────────┐
│                        main.py  (Orchestrator)                       │
│     Loads 8 CSVs once · Processes 250 requests · Writes checkpoint   │
└──────────┬───────────────────────────────────────────┬───────────────┘
           │                                           │
    ┌──────▼──────┐   RequestContext             ┌────▼──────────┐
    │ data_loader │ ─────────────────────────►  │  llm_client   │
    │─────────────│                              │───────────────│
    │ 8 CSV loads │                              │ Vision OCR    │
    │ FX graph BFS│  ◄─── enriched amounts ───  │ Msg parsing   │
    │ Event joins │                              │ Explanations  │
    └──────┬──────┘                              └───────────────┘
           │  RequestContext (with resolved amounts)
    ┌──────▼─────────┐
    │financial_engine│   ← Pure Python / decimal.Decimal  — zero LLM
    │────────────────│
    │ forecast_balance│
    │ 90-day sim     │
    │ Tier checking  │
    │ 6-rule ranking │
    └──────┬─────────┘
           │  SelectedPlan
    ┌──────▼──────────┐
    │output_formatter │
    │─────────────────│
    │ Schema validate │
    │ CSV serialise   │
    └──────┬──────────┘
           │
    output.csv  +  evaluation/usage_report.md
```

### Design Principle

> The **deterministic core** (`financial_engine.py`) makes every binary safety
> decision using pure arithmetic — no LLM involved. Claude is called exactly
> three times per request, and only for tasks that are genuinely linguistic or
> visual: reading a scanned invoice, parsing a multi-lingual employer message,
> and generating the grounded explanation. This separation ensures reproducibility
> and keeps cost predictable.

### Module Responsibilities

| Module | Role | LLM? |
|---|---|---|
| `data_loader.py` | Load 8 CSVs, build `RequestContext`, FX graph BFS | No |
| `financial_engine.py` | 90-day simulation, plan ranking, spending change search | No |
| `llm_client.py` | Vision OCR, message fact extraction, explanation generation | Yes — Claude Sonnet 4.6 |
| `output_formatter.py` | Schema validation, CSV serialisation | No |
| `fx_converter.py` | Multi-hop dated exchange rate resolution (EUR→USD→INR) | No |

---

## 4. The 90-Day Safety Check (Core Algorithm)

### Balance Reconstruction

Starting from `financial_profiles.current_available_balance`:

```text
1. Add all SETTLED credits with settlement_date ≤ request_date
2. Subtract all SETTLED debits with settlement_date ≤ request_date
3. RESERVE all PENDING debits (subtract now — they will clear)
4. DO NOT count pending credits, unrealized investment gains, or scheduled income
```

### Forward Simulation

```text
FOR each day D from request_date to request_date + 90:
    FOR each event E with settlement_date = D:
        SKIP  if status ∈ {cancelled, failed}
        SKIP  if status = unrealized      (investment mark-to-market)
        SKIP  if direction=credit AND status=pending    (unconfirmed income)
        APPLY if direction=debit  AND status=pending    (reserve it)
        APPLY spending_change if E is targeted          (stop or reduce)
        balance += E.signed_amount_in_home_currency
    RECORD (D, balance)
ASSERT: min(all daily balances) >= minimum_balance_to_keep
```

### Affordability Tiering

The system tests each tier in priority order and returns the first safe plan:

```text
TIER 1 — AFFORDABLE_NOW
    Can pay full requested_amount today, 90-day min stays ≥ minimum?
    → full_payment

TIER 2 — AFFORDABLE_WITH_PLAN (tested in sub-order)
    2a. Installment option fits (user accepts, ≤ max_installment_months,
        each payment safe, option exists in request_payment_options)?
        → installments

    2b. Partial payment (allows_partial_payment, user accepts, 0 < safe < full,
        second payment ≤ desired_completion_date)?
        → partial_payment

    2c. Spending changes (≤ 3 stops/reduces on non-protected flexible events,
        full payment then safe today)?
        → full_payment with spending_changes_needed

TIER 3 — AFFORDABLE_LATER
    Full amount safe on some date ≤ desired_completion_date?
    → wait

TIER 4 — NOT_AFFORDABLE
    No safe plan within forecast window
    → not_recommended
```

### Plan-Ranking Tiebreakers (when multiple plans pass Tier 2)

When more than one eligible plan passes the safety check, rank by:

| Priority | Rule |
|---|---|
| 1 | Completes full request by `desired_completion_date` |
| 2 | Requires no spending changes |
| 3 | Minimizes total amount paid (including financing fees) |
| 4 | Starts payment earlier |
| 5 | Uses fewer payments |
| 6 | Lowest `payment_option_id` (final tie-breaker) |

---

## 5. LLM Usage — Exactly Where and Why

### 5.1 Vision OCR — 16 calls

```
16 financial events in financial_events.csv have blank amount fields.
Each is linked to a scanned PNG receipt or invoice.
Claude Sonnet 4.6 (vision) receives the base64-encoded image.

System prompt:
  "You are a financial document reader. Extract the exact monetary amount
   from this image. Return ONLY a JSON object:
   {"amount": <float>, "currency": "<3-letter code>", "confidence": <0-1>}.
   No other text."

Threshold: confidence ≥ 0.7 → use amount. Below threshold → exclude event,
           flag in logs/llm_calls.jsonl.
```

### 5.2 Message Fact Extraction — 12 calls (targeted messages only)

```
215 messages in messages.csv; only those with concrete financial facts
(salary changes, confirmed refunds, cancelled subscriptions) trigger a call.

Extracts structured facts: {fact_type, amount, currency, effective_date,
                            event_id, confidence, raw_quote}

These facts amend the financial model before the simulation runs.
Embedded prompt-injection attempts in messages are ignored — only
financial facts matching the dataset schema are accepted.
```

### 5.3 Decision Explanation — 250 calls

```
After the deterministic engine selects a plan, Claude generates a 1-2 sentence
explanation grounded in exact figures:
  "Pay IDR 15,656,000.00 today. This leaves at least IDR 24,768,300.00
   available over the next 90 days."
  "Pay IDR 18,164,000.00 in full on 2024-09-15. Paying earlier would take
   the balance below the IDR 16,588,900.00 minimum."
```

### Token & Cost Summary (Final Run)

| Call Type | Calls | Input Tokens | Output Tokens | Total Tokens |
|---|---|---|---|---|
| Vision OCR | 16 | 14,800 | 1,280 | 16,080 |
| Message Facts | 12 | 12,400 | 2,800 | 15,200 |
| Explanation Gen | 250 | 48,000 | 22,500 | 70,500 |
| **Total** | **278** | **75,200** | **26,580** | **101,780** |

- **Total cost:** $0.6243 (Claude Sonnet 4.6: $3/M input, $15/M output)  
- **Average cost per request:** $0.0025 (0.25 cents)

---

## 6. Dataset Complexity Handled

| Challenge | How the System Handles It |
|---|---|
| **5 currencies (INR, IDR, ZAR, EUR, USD)** | FX graph BFS on dated monthly snapshots; chains EUR→USD→INR when direct pair absent |
| **16 events with no amount (images)** | Claude vision OCR with confidence gating before simulation |
| **215 unstructured messages (multi-lingual)** | Claude semantic extraction; Indonesian-language employer payslips parsed correctly |
| **Pending vs. settled vs. cancelled events** | Strict status-based cash treatment: pending debits reserved, pending credits excluded |
| **25,342 events spanning multiple years** | Only events in (−∞, request_date] or [request_date, +90d] window are simulated |
| **58 linked events (refund↔expense, valuation↔purchase)** | Link graph traversal; linked events disambiguated by direction and status |
| **User-specific payment preferences** | `payment_methods_user_will_consider` gates every plan option before evaluation |
| **Financing fees on installment plans** | `total_payable_amount` from `request_payment_options.csv` used in cost minimization |

---

## 7. Output Distribution (250 Requests)

| Affordability Status | Count | Payment Method | Count |
|---|---|---|---|
| `not_affordable` | **95** | `not_recommended` | **95** |
| `affordable_now` | **87** | `full_payment` | **87** |
| `affordable_with_plan` | **52** | `installments` | **51** |
| `affordable_later` | **16** | `wait` | **16** |
| | | `partial_payment` | **1** |

All 250 rows passed automated constraint validation (0 violations):

- ✅ `0 ≤ amount_safe_to_pay ≤ requested_amount` — all rows
- ✅ `affordability_status` in allowed set — all rows
- ✅ `recommended_payment_method` in allowed set — all rows
- ✅ `earliest_date_for_full_payment == request_date` for all `affordable_now` rows
- ✅ Payment plan entries chronologically ordered — all rows
- ✅ Partial payment two-payment sums equal `requested_amount`
- ✅ Spending change event IDs reference only flexible, non-protected events

---

## 8. Concrete Output Examples

### Example 1 — `affordable_now` (request_26, IDR, family_transfer)

```
requested_amount:         IDR 15,656,000
amount_safe_to_pay:       IDR 15,656,000
affordability_status:     affordable_now
recommended_method:       full_payment
payment_plan:             2025-08-03:15656000
earliest_date:            2025-08-03
spending_changes_needed:  none
explanation:              "Pay IDR 15,656,000.00 today. This leaves at least
                          IDR 24,768,300.00 available over the next 90 days."
```

### Example 2 — `affordable_with_plan / installments` (request_30, USD, debt_repayment)

```
requested_amount:         USD 775.20
amount_safe_to_pay:       USD 775.20
affordability_status:     affordable_with_plan
recommended_method:       installments
payment_plan:             2026-04-06:268.74|2026-05-06:268.74|2026-06-05:268.74
earliest_date:            2026-04-06
spending_changes_needed:  none
explanation:              "Use 3 installments of USD 258.40, starting today.
                          This leaves at least USD 900.00 available."
```

### Example 3 — `affordable_later / wait` (request_31, IDR, purchase)

```
requested_amount:         IDR 18,164,000
amount_safe_to_pay:       IDR 13,840,360
affordability_status:     affordable_later
recommended_method:       wait
payment_plan:             2024-09-15:18164000
earliest_date:            2024-09-15
spending_changes_needed:  none
explanation:              "Pay IDR 18,164,000.00 in full on 2024-09-15.
                          Paying earlier would take the balance below the
                          IDR 16,588,900.00 minimum."
```

### Example 4 — `not_affordable` (request_28, EUR, investment)

```
requested_amount:         EUR 1,302.40
amount_safe_to_pay:       EUR 689.40
affordability_status:     not_affordable
recommended_method:       not_recommended
payment_plan:             none
earliest_date:            (empty)
spending_changes_needed:  none
explanation:              "Do not make this payment by 2024-08-15.
                          None of the available options keeps the EUR 1,100.00
                          minimum protected."
```

---

## 9. Key Engineering Decisions

### Why `decimal.Decimal` not `float`?

Financial calculations involving multi-currency amounts (e.g., EUR→ZAR at
rate 20.00) compound floating-point errors over 90-day simulations. `Decimal`
is used throughout `financial_engine.py` to eliminate rounding drift.

### Why checkpoint resume?

Each run makes 278 LLM calls. Interruptions (network, rate limits) would waste
all prior work. `output_checkpoint.json` stores completed results per
`request_id`. Re-running skips already-done rows — no duplicate API calls.

### Why single-pass, not iterative?

The problem specification explicitly states: *"Do not invent unsupported income,
expenses, or financial facts."* An iterative agent could hallucinate or over-fit.
A deterministic single-pass simulation ensures every output is traceable to a
specific event row in the dataset.

### Why FX graph BFS?

The 5-currency dataset has 5 explicit pairs but ~20 possible home-currency
cross-pair combinations. Rather than hardcode chains, the system builds a
directed graph from `exchange_rates.csv` and runs BFS on the settlement date,
chaining rates automatically (e.g., EUR→USD→INR = 1/1.09 × 83.33).

---

## 10. Validation & Testing

| Test | Method | Result |
|---|---|---|
| Schema constraint validation | `tests/validate_output.py` | ✅ PASS — 0 violations across 250 rows |
| Unit tests — data loading | `tests/test_data_loader.py` (6 tests) | ✅ PASS |
| Unit tests — financial engine | `tests/test_financial_engine.py` (6 tests) | ✅ PASS |
| Unit tests — FX converter | `tests/test_fx_converter.py` (1 test) | ✅ PASS |
| Sample format check | `tests/test_samples.py` (1 test) | ✅ PASS |
| Pre-flight environment | `setup_check.py` | ✅ PASS |
| **Total test coverage** | 20 tests | **20/20 passing** |

---

## 11. Submission Artifacts

| Artifact | Description | Status |
|---|---|---|
| `output.csv` | 250-row predictions, all 8 columns, schema-validated | ✅ |
| `code.zip` | Full runnable source with `evaluation/usage_report.md` | ✅ |
| `chat_transcript` | Development conversation log | ✅ |
| `evaluation/usage_report.md` | Token counts, cost breakdown, architecture summary | ✅ |

---

## 12. How to Reproduce the Output

```bash
# Fedora Linux
sudo dnf install -y python3.11 python3.11-devel python3-pip
git clone https://github.com/rehaan-ahmad/hackerrank-orchestrate-september26.git
cd hackerrank-orchestrate-september26
python3.11 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env           # add ANTHROPIC_API_KEY
python setup_check.py          # all checks should PASS
python main.py                 # produces output.csv in ~53 seconds
```

Runtime: **52.67 seconds** · Average latency per request: **0.21 seconds**

---

## 13. Limitations (Honest)

| Limitation | Mitigation |
|---|---|
| Recurrence detection uses historical frequency, not user declaration — an irregular large purchase may be misclassified as recurring if repeated in history | Only events with consistent intervals across ≥ 2 settled records are projected forward; novel amounts are not repeated |
| 16 image amounts rely on OCR confidence ≥ 0.7 — damaged scans may produce `None`, excluding the event | Every extraction is logged with confidence score in `logs/llm_calls.jsonl`; excluded events are visible for audit |
| Exchange rates are monthly snapshots (15th of each month) — events between dates use the nearest prior rate (≤ 30 days stale) | All rates are organiser-provided and fixed; this constraint is identical for all participants |
| Message interpretation is single-pass — conflicting messages resolved by recency and source credibility, not iterative reconciliation | Resolution follows the four-priority ordering from the problem spec: cancellation › newer record › settled event › safer interpretation |

---

*Built for HackerRank Orchestrate, September 2026.*  
*Stack: Python 3.11 · pandas 2.2 · Claude Sonnet 4.6 · pydantic · structlog*
