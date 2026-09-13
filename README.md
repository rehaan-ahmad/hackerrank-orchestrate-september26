<div align="center">

# 💰 Buy or Wait?

**Deterministic 90-day cash flow simulation + LLM multimodal reasoning, deciding whether a user can safely afford any financial request.**

*HackerRank Orchestrate — September 2026*

[![Python](https://img.shields.io/badge/python-3.11%2B-blue?style=flat-square)](https://www.python.org/)
[![Claude Sonnet 4.6](https://img.shields.io/badge/Claude-Sonnet_4.6-D4A017?style=flat-square&logo=anthropic)](https://www.anthropic.com/)
[![Pandas](https://img.shields.io/badge/pandas-2.2%2B-150458?style=flat-square&logo=pandas)](https://pandas.pydata.org/)
[![Fedora Linux](https://img.shields.io/badge/platform-Fedora_Linux-294172?style=flat-square&logo=fedora)](https://fedoraproject.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-22c55e?style=flat-square)](LICENSE)

*Given a user's full financial history and an expense request, can they safely pay today — and if not, exactly when can they, and how?*

</div>

---

## What It Does

- **Runs a deterministic 90-day balance simulation per request** — forecasting daily cash flow using every confirmed income, recurring debit, scheduled payment, and pending reservation, with `decimal.Decimal` arithmetic to eliminate floating-point drift across five currencies (INR, IDR, ZAR, EUR, USD).
- **Extracts monetary amounts from scanned receipts and invoices via LLM vision** — 16 financial events in the dataset carry no numeric amount; the system calls Claude Sonnet 4.6 with base64-encoded PNG images to OCR the exact figure before including it in the simulation.
- **Interprets unstructured, multi-lingual support messages to amend the financial model** — employer salary updates, merchant refunds, and bank alerts in `messages.csv` (including Indonesian-language text) are semantically parsed and applied to modify projected balances before any decision is made.
- **Ranks competing safe plans by six ordered tiebreaker rules** — when more than one eligible payment option passes the 90-day safety check, the system selects the plan that completes by the deadline, avoids spending changes, minimizes total cost (including financing fees), starts earliest, uses fewest payments, and breaks ties by `payment_option_id`.

---

## Output Fields

| Field | Type / Allowed Values | Description |
|---|---|---|
| `request_id` | `string` | Unique identifier matching `requests.csv` |
| `amount_safe_to_pay` | `float`, `0 ≤ value ≤ requested_amount` | Maximum amount safely payable on `request_date` before optional spending changes, maintaining minimum balance throughout the 90-day window |
| `affordability_status` | `affordable_now` · `affordable_with_plan` · `affordable_later` · `not_affordable` | Whether and how the full request can be completed |
| `recommended_payment_method` | `full_payment` · `partial_payment` · `installments` · `wait` · `not_recommended` | Safest eligible payment approach given user's stated preferences |
| `payment_plan` | `YYYY-MM-DD:amount\|YYYY-MM-DD:amount` or `none` | Chronological payment schedule; installment plans must exactly match a row in `request_payment_options.csv` |
| `earliest_date_for_full_payment` | `YYYY-MM-DD` or empty | First projected date when the full requested amount passes the 90-day safety check without spending changes; equals `request_date` for `affordable_now` |
| `spending_changes_needed` | `stop:<event_id>\|reduce_to:<event_id>:<amount>` or `none` | Up to three modifications to flexible recurring expenses that unlock affordability |
| `decision_explanation` | `string` | Grounded natural-language explanation citing exact balance figures, minimum balance, and constraints in the user's home currency |

---

## Architecture

```text
┌─────────────────────────────────────────────────────────────────┐
│                     main.py  (orchestrator)                     │
│  Loads all datasets once · Iterates 250 requests · Checkpoints  │
└──────────┬─────────────────────────────────────────┬────────────┘
           │                                         │
    ┌──────▼──────┐                          ┌───────▼──────┐
    │ data_loader │                          │  llm_client  │
    │─────────────│                          │──────────────│
    │ Loads 8 CSVs│         context          │ Vision OCR   │
    │ Joins tables│ ──────────────────────► │ Msg parsing  │
    │ Converts FX │                          │ Explanation  │
    │ Builds ctx  │                          │ generation   │
    └──────┬──────┘                          └───────┬──────┘
           │  RequestContext                         │ enriched amounts
           └────────────────────┬────────────────────┘
                        ┌───────▼────────┐
                        │financial_engine│
                        │────────────────│
                        │ forecast_balance│
                        │ 90-day sim     │
                        │ plan ranking   │
                        │ spending search│
                        └───────┬────────┘
                                │ SelectedPlan
                        ┌───────▼──────────┐
                        │ output_formatter │
                        │──────────────────│
                        │ Schema validation│
                        │ CSV serialisation│
                        └───────┬──────────┘
                                │
                   output.csv  +  evaluation/usage_report.md
```

**Design principle:** The deterministic core (`financial_engine.py`) makes every binary safety decision using pure Python arithmetic; Claude is called only for tasks that require language or vision understanding — ensuring reproducibility and cost predictability regardless of LLM non-determinism.

---

## Dataset

| File | Purpose | Key fact |
|---|---|---|
| `requests.csv` | Prediction targets | 250 rows; 9 request types, balanced ~28 each |
| `sample_requests.csv` | Labeled reference examples | 25 rows with all 8 output fields completed |
| `financial_profiles.csv` | User financial state and preferences | 275 users; 5 home currencies; `max_installment_months` blank = installments refused |
| `financial_events.csv` | Historical and future cash flow | 25,342 events; 8 event types; 16 rows have blank `amount` requiring image OCR |
| `exchange_rates.csv` | Fixed dated FX conversion rates | 134 rows; monthly snapshots on the 15th; 5 currency pairs; chain-join required for indirect pairs (e.g. EUR→INR via USD) |
| `request_payment_options.csv` | Seller/provider payment offers per request | 790 options; 2–4 per request; includes explicit `financing_fee` and `total_payable_amount` |
| `messages.csv` | Unstructured supporting evidence | 215 messages; 5 source types including Indonesian-language employer payslips |
| `images.csv` | Image-to-event links for 16 blank amounts | 16 rows; each resolved to `dataset/media/images/<image_id>.png` |

**Scale:** 250 prediction requests · 9 request types · 5 home currencies (INR, IDR, ZAR, EUR, USD) · request dates ranging from 2019-09-03 to 2026-07-05 · 25,342 financial events across 275 user profiles.

---

## Core Logic: 90-Day Safety Check

```text
FUNCTION forecast_balance(start_balance, start_date, end_date, events, min_balance):
    balance ← start_balance
    FOR each day D from start_date to end_date:
        FOR each event E with settlement_date = D:
            IF E.status IN {cancelled, failed}     →  SKIP
            IF E.status = unrealized               →  SKIP  (investment mark-to-market)
            IF E.direction = credit AND E.status = pending  →  SKIP  (unconfirmed income)
            IF E.direction = debit  AND E.status = pending  →  RESERVE (subtract now)
            IF spending_change targets E            →  apply stop/reduce before subtracting
            balance ← balance + E.signed_amount_home_currency
        RECORD (D, balance)
    RETURN daily_series

FUNCTION amount_safe_to_pay(context, request_date):
    available ← balance_on(request_date) - min_balance
    FOR candidate FROM available DOWNTO 0  (binary search):
        projected ← forecast_balance(balance - candidate, request_date, +90 days, events)
        IF min(projected.balance) >= min_balance:
            RETURN candidate
    RETURN 0
```

**Six plan-ranking rules** (applied in priority order when multiple plans pass the safety check):

1. Complete the full request by `desired_completion_date`
2. Require no spending changes
3. Minimize total amount paid (including financing fees)
4. Start payment earlier
5. Use fewer payments
6. Use the lowest `payment_option_id` as the final tie-breaker

---

## Setup

```bash
# 1. Install system dependencies (Fedora Linux)
sudo dnf install -y python3.11 python3.11-devel python3-pip git

# 2. Clone the repository
git clone https://github.com/rehaan-ahmad/hackerrank-orchestrate-september26.git
cd hackerrank-orchestrate-september26

# 3. Create and activate a virtual environment
python3.11 -m venv .venv
source .venv/bin/activate

# 4. Install Python dependencies
pip install -r requirements.txt

# 5. Configure your Anthropic API key
cp .env.example .env
# Edit .env and set: ANTHROPIC_API_KEY=sk-ant-...

# 6. Verify the environment
python setup_check.py
# Expected: all checks PASS (system, dataset files, images, imports, API key format)
```

---

## Run

```bash
# Run the full pipeline (250 requests)
python main.py
```

The pipeline produces four artifacts:

| Artifact | Description |
|---|---|
| `output.csv` | 250-row prediction file with all 8 required output columns |
| `output_checkpoint.json` | Per-request checkpoint; restarting `main.py` skips already-completed rows |
| `evaluation/usage_report.md` | Token counts, cost breakdown, and architecture summary for submission |
| `logs/llm_calls.jsonl` | Structured JSON log of every LLM call (image OCR, message parsing, explanations) |

**Checkpoint resume:** If interrupted, re-running `python main.py` detects `output_checkpoint.json` and skips completed requests — no duplicate API calls, no wasted tokens.

---

## Testing

```bash
# Unit tests (20 tests across all modules)
python -m pytest tests/ -v

# Schema and constraint validation against output.csv
python tests/validate_output.py

# Environment and dependency check
python setup_check.py
```

---

## Project Structure

```text
.
├── main.py                         # Orchestrator: loads data, loops 250 requests, writes output
├── setup_check.py                  # Pre-flight: verifies Python, packages, dataset files, API key
├── requirements.txt                # Runtime dependencies (anthropic, pandas, pydantic, structlog…)
├── .env.example                    # Environment variable template (copy to .env, add API key)
│
├── src/
│   ├── data_loader.py              # Loads 8 CSVs, builds RequestContext, applies FX conversion
│   ├── financial_engine.py         # 90-day simulation, amount_safe_to_pay, plan ranking (no LLM)
│   ├── llm_client.py               # Claude Sonnet 4.6: vision OCR, message parsing, explanations
│   ├── output_formatter.py         # Serialises SelectedPlan → CSV row; validates schema constraints
│   ├── fx_converter.py             # Multi-hop dated FX graph (EUR→USD→INR etc.)
│   ├── models.py                   # Pydantic domain models: UserProfile, FinancialEvent, SelectedPlan
│   ├── plan_selector.py            # Applies 6-rule tiebreaker to rank candidate plans
│   └── utils.py                    # Shared helpers (date parsing, amount rounding)
│
├── dataset/
│   ├── requests.csv                # 250 prediction targets
│   ├── sample_requests.csv         # 25 labeled examples (format reference)
│   ├── financial_profiles.csv      # 275 user profiles
│   ├── financial_events.csv        # 25,342 transaction / event records
│   ├── exchange_rates.csv          # 134 fixed dated FX rates
│   ├── request_payment_options.csv # 790 seller payment options
│   ├── messages.csv                # 215 unstructured messages
│   ├── images.csv                  # 16 image-to-event links
│   ├── output.csv                  # Blank template (filled by pipeline)
│   └── media/images/               # 16 PNG receipt/invoice images
│
├── tests/
│   ├── test_data_loader.py         # Dataset loading, context building, FX lookup
│   ├── test_financial_engine.py    # Balance simulation, affordability computation, plan ranking
│   ├── test_fx_converter.py        # Same-currency and cross-currency conversions
│   ├── test_llm_client.py          # LLM client mocking and response parsing
│   ├── test_samples.py             # Sample request format validation
│   └── validate_output.py          # Schema, constraint, and cross-field validation of output.csv
│
├── evaluation/
│   └── usage_report.md             # Token counts, cost breakdown, architecture summary
│
├── architecture.md                 # Full system design document
├── dataset_analysis.md             # Per-file schema analysis and field notes
├── decision_rules.md               # Formal specification of all financial decision rules
├── data_flow.md                    # Data join paths and transformation pipeline
├── llm_prompts_spec.md             # Prompt templates and output format spec
└── log.txt                         # Agent session log (append-only, per AGENTS.md §5)
```

---

## Submission

| Artifact | Description | Status |
|---|---|---|
| `output.csv` | Predictions for all 250 requests in `dataset/requests.csv` | ✅ Complete |
| `code.zip` | Full runnable solution including `evaluation/usage_report.md` and README | ✅ Packed |
| `chat_transcript` | Development conversation showing system design and iteration | ✅ Included |
| `evaluation/usage_report.md` | Model providers, call counts, token totals, and cost breakdown for the final run | ✅ Complete |

---

## Limitations

| Limitation | Mitigation |
|---|---|
| **Recurrence detection uses historical frequency, not user declaration** — a one-time large purchase may be incorrectly projected as recurring if it appears multiple times in the event log. | Spending is classified conservative-first: only events with consistent interval patterns across ≥ 2 settled records are projected forward. |
| **16 image amounts rely on LLM OCR confidence threshold (≥ 0.7)** — low-quality scans may produce `None`, causing the event to be excluded from the simulation. | The pipeline logs every extraction with `confidence` score; events excluded due to low confidence are flagged in `logs/llm_calls.jsonl` for manual review. |
| **Exchange rates are monthly snapshots (15th of each month)** — events between two rate dates use the nearest prior rate, introducing up to 30-day staleness. | All rates in `exchange_rates.csv` are fixed by the contest organiser; no live market data is used or available, so this limitation is shared by all participants. |
| **Message interpretation is single-pass** — conflicting messages (e.g., two employer salary updates for the same period) are resolved by recency and source credibility without iterative reconciliation. | Conflict resolution follows the four-priority ordering specified in the problem statement: explicit cancellation › newer same-source record › settled event › financially safer interpretation. |

---

<div align="center">

*HackerRank Orchestrate — September 2026*

Python 3.11 · pandas 2.2 · Claude Sonnet 4.6 · Anthropic SDK · pydantic · structlog

</div>
