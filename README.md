# HackerRank Orchestrate — Buy or Wait?

Starter repository for the **HackerRank Orchestrate** 24-hour hackathon (September 2026).

## Buy or Wait?

Build an AI-powered financial agent that decides whether a user can safely afford a requested expense.

A user may ask: **"Can I afford this laptop?"**

Answering well takes more than the current balance. The agent must account for recurring expenses, pending payments, essential spending, confirmed income, available payment options, and relevant details buried in messages and images.

For every request, the agent decides whether the user should pay in full, pay partially, use installments, wait, or not proceed. The recommendation must be personalized: two users with the same balance can deserve different answers based on their commitments, priorities, payment preferences, and willingness to adjust flexible expenses.

A recommendation is safe only if the user can complete the full payment plan, cover essential expenses, and stay above their preferred minimum balance throughout the forecast period.

Read [`problem_statement.md`](./problem_statement.md) for the full task spec, input/output schema, allowed values, conflict-resolution rules, and submission format.

---

## Fedora Linux Setup

### Prerequisites (Fedora 38+)

```bash
sudo dnf install -y python3.11 python3.11-devel python3-pip git
```

### Project Setup

```bash
# Clone repository
git clone https://github.com/rehaan-ahmad/hackerrank-orchestrate-september26.git
cd hackerrank-orchestrate-september26

# Create virtual environment (must be .venv/)
python3.11 -m venv .venv
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip

# Install dependencies
pip install -r requirements.txt
```

### Environment Configuration

```bash
# Copy example environment file
cp .env.example .env

# Edit .env and add your Anthropic API key
# ANTHROPIC_API_KEY=sk-ant-...
```

### Verify Setup

```bash
python setup_check.py
```

Expected output:
```
============================================================
BUY OR WAIT? - SETUP VERIFICATION
============================================================
[PASS] Python Version: Python 3.11.x
[PASS] Imports: All imports successful
[PASS] API Key: ANTHROPIC_API_KEY is set
[PASS] Dataset Files: All 8 dataset files present
[PASS] Media Images: 16 PNG images found
[PASS] Project Structure: Project structure matches architecture.md
[PASS] API Connectivity: API connectivity verified
============================================================
ALL CHECKS PASSED ✓
```

---

## Running the Solution

```bash
# Activate venv (if not already)
source .venv/bin/activate

# Run the main pipeline
python main.py
```

### Expected Output

- `output.csv` in repository root with 250 rows (one per request in `dataset/requests.csv`)
- `evaluation/usage_report.md` with token usage summary

### Columns in output.csv (exact order required):

```
request_id,amount_safe_to_pay,affordability_status,recommended_payment_method,payment_plan,earliest_date_for_full_payment,spending_changes_needed,decision_explanation
```

### Validation Requirements

- `0 <= amount_safe_to_pay <= requested_amount`
- `affordability_status` ∈ {affordable_now, affordable_with_plan, affordable_later, not_affordable}
- `recommended_payment_method` ∈ {full_payment, partial_payment, installments, wait, not_recommended}
- `payment_plan` = "none" or chronological `YYYY-MM-DD:amount|YYYY-MM-DD:amount`
- `earliest_date_for_full_payment` = "" for not_affordable, valid date otherwise
- `spending_changes_needed` = "none" or `stop:event_X|reduce_to:event_Y:amount`
- Installment plans must match a supplied payment option exactly

---

## Project Structure

```
project/
├── src/
│   ├── __init__.py
│   ├── data_loader.py          # CSV loading, joining, indexing
│   ├── financial_engine.py     # Core affordability logic
│   ├── fx_converter.py         # Exchange rate conversion with chaining
│   ├── llm_client.py           # Anthropic SDK wrapper with batching/caching
│   ├── plan_selector.py        # Plan generation, ranking, tiebreakers
│   ├── output_formatter.py     # Output validation & CSV writing
│   ├── models.py               # Pydantic domain models
│   └── utils.py                # Helpers (date parsing, Decimal, etc.)
├── dataset/                    # (provided data)
│   ├── financial_profiles.csv
│   ├── financial_events.csv
│   ├── exchange_rates.csv
│   ├── requests.csv
│   ├── sample_requests.csv
│   ├── request_payment_options.csv
│   ├── messages.csv
│   ├── images.csv
│   ├── output.csv
│   └── media/
│       └── images/*.png
├── evaluation/
│   └── usage_report.md         # Token usage summary (auto-generated)
├── cache/
│   ├── image_extractions.json  # Cached OCR results
│   ├── message_interpretations.json
│   └── explanation_cache.json
├── tests/
│   ├── test_fx_converter.py
│   ├── test_financial_engine.py
│   ├── test_plan_selector.py
│   └── test_samples.py         # Validates all 25 samples exact match
├── output.csv                  # Generated submission
├── main.py                     # Entry point
├── requirements.txt
├── .env                        # ANTHROPIC_API_KEY (not committed)
├── .env.example                # Template
├── .gitignore
├── setup_check.py              # Setup verification
├── README.md                   # This file
└── architecture.md             # System design document
```

---

## Key Implementation Details

### Technology Stack

| Component | Technology | Version |
|-----------|------------|---------|
| Language | Python | 3.11+ |
| Data Processing | pandas | 2.2+ |
| Numeric Precision | Python `decimal.Decimal` | stdlib |
| LLM Client | Anthropic Python SDK | 0.40+ |
| Vision (Images) | Anthropic API (base64) | — |
| Image Preprocessing | Pillow | 10+ |
| Config | python-dotenv | 1.0+ |
| Validation | pydantic | 2.9+ |
| Testing | pytest | 8.3+ |
| Logging | structlog | 24+ |

### Financial Engine Rules (from problem_statement.md)

1. **Available Balance**: Start with `current_available_balance`, add settled credits ≤ request_date, subtract settled debits ≤ request_date, **reserve pending debits**, ignore pending credits/scheduled income/unrealized gains
2. **90-Day Forecast**: request_date (exclusive) to request_date + 90 days (inclusive); include scheduled income on settlement_date; detect recurrence only with ≥3 historical occurrences
3. **Currency Conversion**: All amounts in user's `home_currency`; use `exchange_rates.csv` on settlement_date (nearest prior 15th); chain via USD if direct pair missing
4. **Spending Changes**: Max 3 changes; only non-protected, flexible events in categories user permits; reduction respects `minimum_allowed_amount`
5. **Plan Ranking** (6 tiebreakers):
   1. Complete by desired_completion_date
   2. No spending changes
   3. Minimize total_payable_amount
   4. Earliest start date
   5. Fewest payments
   6. Lowest payment_option_id

### LLM Call Strategy

| Call Type | Purpose | Model | Batching |
|-----------|---------|-------|----------|
| Vision | Extract amounts from 16 images | claude-sonnet-4-6 | Single multi-image call |
| Messages | Parse salary changes, cancellations | claude-sonnet-4-6 | Batched by user |
| Explanations | Generate decision_explanation | claude-sonnet-4-6 | 25-50 requests per call |

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# Run specific test file
pytest tests/test_samples.py -v

# Run with coverage
pytest tests/ --cov=src --cov-report=term-missing
```

The `test_samples.py` validates that all 25 samples in `dataset/sample_requests.csv` reproduce exactly.

---

## Token Usage Report

The solution automatically generates `evaluation/usage_report.md` with:
- Total API calls
- Input/output tokens per call type
- Estimated total and per-request cost
- Model provider and name

---

## Submission

Submit these three files to HackerRank:

| File | Description |
|------|-------------|
| `code.zip` | Full runnable solution, prompts/config, README, `evaluation/` folder |
| `output.csv` | Predictions for all 250 requests in `dataset/requests.csv` |
| `chat_transcript` | The `log.txt` file showing development conversation |

### Pre-Submission Checklist

- [ ] `output.csv` has 250 rows + header
- [ ] `output.csv` columns in exact required order
- [ ] All `amount_safe_to_pay` satisfy `0 <= amount <= requested_amount`
- [ ] Installment plans match supplied payment options exactly
- [ ] Spending changes target only flexible recurring expenses
- [ ] `code.zip` includes `evaluation/usage_report.md`
- [ ] No API keys or secrets in submission

---

## License

For HackerRank Orchestrate September 2026 hackathon use only.