# System Architecture: Buy or Wait?

## 1. Processing Pipeline Overview

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              MAIN PIPELINE (main.py)                                │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
        ┌───────────────────┐ ┌─────────────────┐ ┌──────────────────┐
        │  LOAD PHASE       │ │  ENRICH PHASE   │ │  DECIDE PHASE    │
        │  (data_loader.py) │ │  (data_loader.py)│ │ (financial_engine)│
        └───────────────────┘ └─────────────────┘ └──────────────────┘
                    │                 │                 │
                    ▼                 ▼                 ▼
        ┌─────────────────────────────────────────────────────────────────────┐
        │                      PER-REQUEST DECISION LOOP                       │
        │  For each request_id in requests.csv (250 rows):                    │
        │                                                                     │
        │  1. Build RequestContext (user profile, events, payment options,   │
        │     messages, images, FX rates)                                     │
        │  2. Extract image amounts (LLM Vision) for 16 blank-amount events  │
        │  3. Convert ALL amounts to user home_currency (FX engine)          │
        │  4. Compute available_balance as of request_date                    │
        │  5. Build 90-day cash flow forecast (request_date to +90 days)     │
        │  6. Test affordability tiers in priority order:                     │
        │     a) AFFORDABLE_NOW → full_payment                                │
        │     b) AFFORDABLE_WITH_PLAN → installments / partial / full+changes │
        │     c) AFFORDABLE_LATER → wait                                      │
        │     d) NOT_AFFORDABLE → not_recommended                             │
        │  7. Rank valid plans by 6 tiebreaker rules                          │
        │  8. Generate decision_explanation (LLM)                             │
        │  9. Format output row                                               │
        └─────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┼─────────────────┐
                    ▼                 ▼                 ▼
        ┌───────────────────┐ ┌─────────────────┐ ┌──────────────────┐
        │  VALIDATE PHASE   │ │  OUTPUT PHASE   │ │  TOKEN LOG PHASE │
        │ (output_formatter)│ │ (output_formatter)│ │ (llm_client)     │
        └───────────────────┘ └─────────────────┘ └──────────────────┘
                    │                 │                 │
                    └─────────────────┼─────────────────┘
                                      ▼
                          ┌───────────────────────┐
                          │      output.csv       │
                          │  evaluation/usage_    │
                          │      report.md        │
                          └───────────────────────┘
```

---

## 2. Technology Stack

| Component | Technology | Version | Justification |
|-----------|------------|---------|---------------|
| Language | Python | 3.11+ | pandas, rich ecosystem, required by AGENTS.md |
| Data Processing | pandas | 2.2+ | Efficient CSV loading, joins, groupby operations |
| Numeric Precision | Python `decimal.Decimal` | stdlib | Financial calculations — no float errors |
| FX Conversion | Custom module | — | Only 5 currency pairs, monthly rates, explicit chaining |
| LLM Client | Anthropic Python SDK | 0.39+ | Official SDK for claude-sonnet-4-6 |
| Vision (Images) | Anthropic API (base64) | — | 16 images only; base64 encoding avoids file upload |
| Image Preprocessing | Pillow | 10+ | Resize/compress before base64 to reduce tokens |
| Config | python-dotenv | 1.0+ | Load ANTHROPIC_API_KEY from .env |
| Validation | pydantic | 2.9+ | Output schema validation before write |
| Testing | pytest | 8.3+ | Unit tests for all 25 samples exact match |
| Logging | structlog | 24+ | Structured JSON logs for audit trail |

**Explicitly NOT used:**
- Web framework (Flask/FastAPI) — batch script only
- Docker — not needed per constraints
- Database — all data fits in memory (25K events)
- Async — sequential 250 requests is fast enough; no I/O concurrency needed

---

## 3. Financial Engine Design

### 3.1 Data Structures

```python
# Core domain models (pydantic for validation)

class UserProfile:
    user_id: str
    home_currency: str
    current_available_balance: Decimal
    minimum_balance_to_keep: Decimal
    financial_priorities: Set[str]          # parsed from pipe-separated
    protected_categories: Set[str]          # expense_categories_to_protect
    reducible_categories: Set[str]          # willing_to_reduce (NaN → empty)
    stoppable_categories: Set[str]          # willing_to_stop (NaN → empty)
    accepted_payment_methods: Set[str]      # payment_methods_user_will_consider
    max_installment_months: Optional[int]   # NaN → None

class FinancialEvent:
    event_id: str
    user_id: str
    event_type: str          # expense, subscription, income, debt_payment, etc.
    description: str
    category: str
    direction: str           # debit, credit, non_cash
    amount: Decimal          # after FX conversion to home_currency
    currency: str            # original currency
    event_date: date
    settlement_date: date
    status: str              # settled, pending, scheduled, cancelled, failed, unrealized
    linked_event_id: Optional[str]
    flexibility: str         # fixed, reducible, stoppable, reducible_or_stoppable
    minimum_allowed_amount: Optional[Decimal]  # NaN → None

class PaymentOption:
    payment_option_id: str
    request_id: str
    payment_method: str      # full_payment, installments
    payment_amount: Decimal  # per-installment amount
    number_of_payments: int
    first_payment_date: date
    payment_frequency_days: Optional[int]
    financing_fee: Decimal
    total_payable_amount: Decimal

class RequestContext:
    request_id: str
    user_id: str
    request_date: date
    request_type: str
    requested_amount: Decimal
    desired_completion_date: date
    allows_partial_payment: bool
    request_text: str
    request_currency: str    # detected from request_text or home_currency
    user_profile: UserProfile
    events: List[FinancialEvent]
    payment_options: List[PaymentOption]
    messages: List[Message]
    images: List[ImageRef]
```

### 3.2 Available Balance Computation (as of request_date)

```python
def compute_available_balance(profile: UserProfile, events: List[FinancialEvent], 
                              request_date: date) -> Decimal:
    """
    Rules from problem statement §6.3 and decision_rules.md:
    1. Start with current_available_balance
    2. Add settled credits (income, refunds) with settlement_date <= request_date
    3. Subtract settled debits (expenses, debt_payments) with settlement_date <= request_date
    4. Reserve pending debits (treat as already spent)
    5. Do NOT count pending credits, scheduled income, unrealized gains
    """
    balance = profile.current_available_balance
    
    for event in events:
        if event.settlement_date > request_date:
            continue
            
        if event.status == "settled":
            if event.direction == "credit":
                balance += event.amount
            elif event.direction == "debit":
                balance -= event.amount
            # non_cash (investment_valuation) ignored
            
        elif event.status == "pending":
            if event.direction == "debit":
                balance -= event.amount  # RESERVE
            # pending credits IGNORED
            
        # cancelled, failed, unrealized ignored
    
    return balance
```

### 3.3 90-Day Cash Flow Forecast

```python
def build_90_day_forecast(profile: UserProfile, events: List[FinancialEvent],
                          request_date: date, messages: List[Message]) -> Forecast:
    """
    Forecast period: request_date (exclusive) to request_date + 90 days (inclusive)
    
    Returns: List[DailyBalance] with date, opening_balance, net_flow, closing_balance
    """
    forecast_end = request_date + timedelta(days=90)
    
    # Step 1: Collect all future cash flows in window
    future_flows = []  # (date, amount, description, is_recurring)
    
    for event in events:
        if event.settlement_date <= request_date:
            continue
        if event.settlement_date > forecast_end:
            continue
        if event.status in ("cancelled", "failed", "unrealized"):
            continue
            
        if event.direction == "debit":
            future_flows.append((event.settlement_date, -event.amount, 
                               f"{event.description} ({event.category})", 
                               event.event_type == "subscription"))
        elif event.direction == "credit":
            # Only count CONFIRMED income (salary scheduled, not pending bonuses)
            if event.event_type == "income" and event.status == "scheduled":
                future_flows.append((event.settlement_date, event.amount,
                                   f"{event.description}", True))
            # pending credits ignored per rules
    
    # Step 2: Detect and project recurring patterns
    recurring_projections = detect_recurrence(events, request_date, forecast_end)
    future_flows.extend(recurring_projections)
    
    # Step 3: Apply message amendments (salary changes, etc.)
    future_flows = apply_message_amendments(future_flows, messages, request_date, forecast_end)
    
    # Step 4: Sort by date and compute daily balances
    future_flows.sort(key=lambda x: x[0])
    
    daily_balances = []
    current_balance = compute_available_balance(profile, events, request_date)
    
    for day_offset in range(91):  # 0 to 90 inclusive
        check_date = request_date + timedelta(days=day_offset)
        day_flows = [f for f in future_flows if f[0] == check_date]
        net_flow = sum(f[1] for f in day_flows)
        
        daily_balances.append(DailyBalance(
            date=check_date,
            opening_balance=current_balance,
            net_flow=net_flow,
            closing_balance=current_balance + net_flow,
            flows=day_flows
        ))
        current_balance += net_flow
    
    return Forecast(daily_balances=daily_balances, 
                    min_balance=min(d.closing_balance for d in daily_balances))
```

### 3.4 Recurrence Detection (Conservative)

```python
def detect_recurrence(events: List[FinancialEvent], request_date: date, 
                      forecast_end: date) -> List[Tuple[date, Decimal, str, bool]]:
    """
    Only project if ≥3 historical occurrences at regular interval.
    Returns projected future flows.
    """
    projections = []
    
    # Group by user, category, direction
    grouped = defaultdict(list)
    for event in events:
        if event.status != "settled":
            continue
        if event.settlement_date >= request_date:
            continue  # only historical
        key = (event.user_id, event.category, event.direction, event.event_type)
        grouped[key].append(event)
    
    for key, evts in grouped.items():
        if len(evts) < 3:
            continue
            
        # Check monthly salary pattern
        if key[2] == "credit" and key[3] == "income":
            dates = sorted([e.settlement_date for e in evts])
            intervals = [(dates[i+1] - dates[i]).days for i in range(len(dates)-1)]
            if all(27 <= d <= 31 for d in intervals):  # monthly
                last_date = dates[-1]
                amount = evts[-1].amount
                # Project forward
                next_date = last_date + timedelta(days=30)
                while next_date <= forecast_end:
                    projections.append((next_date, amount, 
                                      f"Projected salary ({key[2]})", True))
                    next_date += timedelta(days=30)
    
    # Similar logic for subscriptions (monthly fixed debits)
    # Variable expenses (groceries): use 90th percentile of last 6 months
    # but only if ≥3 occurrences
    
    return projections
```

### 3.5 Affordability Testing Functions

```python
def can_pay_full_today(available: Decimal, minimum: Decimal, 
                       amount: Decimal, forecast: Forecast) -> bool:
    """Check if paying `amount` today keeps balance ≥ minimum for 90 days."""
    if available - amount < minimum:
        return False
    # Simulate payment today
    test_forecast = forecast.copy()
    test_forecast.apply_payment(request_date, -amount)
    return test_forecast.min_balance >= minimum

def find_max_safe_partial(available: Decimal, minimum: Decimal, 
                          forecast: Forecast) -> Decimal:
    """Binary search max amount payable today without breaching minimum."""
    low, high = Decimal('0'), available - minimum
    if high <= 0:
        return Decimal('0')
    
    while high - low > Decimal('0.01'):
        mid = (low + high) / 2
        if can_pay_full_today(available, minimum, mid, forecast):
            low = mid
        else:
            high = mid
    return low.quantize(Decimal('0.01'))

def find_earliest_full_payment_date(forecast: Forecast, amount: Decimal, 
                                     minimum: Decimal) -> Optional[date]:
    """Find first date where full amount can be paid safely."""
    for daily in forecast.daily_balances:
        if daily.closing_balance - amount >= minimum:
            # Check remaining days
            remaining = forecast.daily_balances[
                forecast.daily_balances.index(daily):]
            if all(d.closing_balance - amount >= minimum for d in remaining):
                return daily.date
    return None
```

### 3.6 Spending Change Engine

```python
def find_spending_changes(profile: UserProfile, events: List[FinancialEvent],
                          forecast: Forecast, target_amount: Decimal) -> List[Change]:
    """
    Find up to 3 changes (stop/reduce) that free enough cash for target_amount.
    Priority: stop > reduce (more savings), highest savings first.
    """
    # Collect eligible flexible events in forecast window
    eligible = []
    for event in events:
        if event.status not in ("settled", "scheduled"):
            continue
        if event.direction != "debit":
            continue
        if event.flexibility == "fixed":
            continue
        if event.category in profile.protected_categories:
            continue
        
        can_stop = (event.flexibility in ("stoppable", "reducible_or_stoppable") 
                    and event.category in profile.stoppable_categories)
        can_reduce = (event.flexibility in ("reducible", "reducible_or_stoppable") 
                      and event.category in profile.reducible_categories)
        
        if not can_stop and not can_reduce:
            continue
            
        # Calculate savings over 90 days
        if event.event_type == "subscription":
            occurrences = count_occurrences_in_window(event, forecast_start, forecast_end)
        else:
            occurrences = 1  # one-time
        
        if can_stop:
            savings = event.amount * occurrences
            eligible.append(Change("stop", event.event_id, savings, 
                                  event.minimum_allowed_amount))
        
        if can_reduce and event.minimum_allowed_amount:
            savings = (event.amount - event.minimum_allowed_amount) * occurrences
            eligible.append(Change("reduce_to", event.event_id, savings, 
                                  event.minimum_allowed_amount))
    
    # Sort by savings descending
    eligible.sort(key=lambda c: c.savings, reverse=True)
    
    # Greedy pick top 3
    selected = []
    total_savings = Decimal('0')
    for change in eligible:
        if len(selected) >= 3:
            break
        if total_savings + change.savings <= 0:
            break
        selected.append(change)
        total_savings += change.savings
    
    return selected if total_savings >= target_amount else []
```

### 3.7 Plan Ranking (6 Tiebreaker Rules)

```python
def rank_plans(plans: List[Plan]) -> List[Plan]:
    """
    Problem statement §6.3 tiebreaker order:
    1. Complete by desired_completion_date (bool)
    2. No spending changes (bool)
    3. Minimize total_payable_amount (Decimal)
    4. Earliest start date (date)
    5. Fewest payments (int)
    6. Lowest payment_option_id (str)
    """
    def sort_key(plan):
        return (
            not plan.completes_by_deadline,      # 1. False < True (complete first)
            plan.spending_changes_count > 0,      # 2. False < True (no changes first)
            plan.total_cost,                      # 3. Lower cost first
            plan.first_payment_date,              # 4. Earlier first
            plan.number_of_payments,              # 5. Fewer first
            plan.payment_option_id or "zzz"       # 6. Lexicographic
        )
    return sorted(plans, key=sort_key)
```

---

## 4. LLM Call Strategy

### 4.1 Calls Requiring LLM

| Call Type | Purpose | Model | Est. Calls (250 req) |
|-----------|---------|-------|---------------------|
| Vision (Image Amount Extraction) | Extract amount from 16 PNGs | claude-sonnet-4-6 | 16 (one-time, cached) |
| Message Interpretation | Parse salary changes, cancellations | claude-sonnet-4-6 | ~128 (request-linked messages) |
| Decision Explanation Generation | Write human-readable explanation | claude-sonnet-4-6 | 250 (one per request) |

### 4.2 Calls NOT Requiring LLM (Deterministic)

- FX conversion (explicit rates, chaining logic)
- Balance computation (explicit rules)
- 90-day forecast (deterministic projection)
- Affordability tier testing (explicit thresholds)
- Spending change eligibility (rule-based matrix)
- Installment selection (scoring algorithm)
- Plan ranking (6 explicit tiebreakers)
- Output formatting (schema validation)

### 4.3 Batching Strategy

| Batch Type | Approach |
|------------|----------|
| Vision | Process all 16 images in single batch call with multi-image prompt |
| Messages | Group by user; send all request-linked messages for a user in one call |
| Explanations | Batch 25-50 requests per call with structured context; parse JSON array response |

**Caching:**
- Vision results cached to disk (`cache/image_extractions.json`) — run once
- Message interpretations cached per user-request pair
- Explanation prompts use identical system prompt; only user context varies

---

## 5. Data Layer Design

### 5.1 Loading & Joining (data_loader.py)

```python
def load_all_data(data_dir: Path) -> Dataset:
    """Load all CSVs, build indexes, return joined Dataset object."""
    profiles = pd.read_csv(data_dir / "financial_profiles.csv")
    events = pd.read_csv(data_dir / "financial_events.csv")
    rates = pd.read_csv(data_dir / "exchange_rates.csv")
    requests = pd.read_csv(data_dir / "requests.csv")
    payment_opts = pd.read_csv(data_dir / "request_payment_options.csv")
    messages = pd.read_csv(data_dir / "messages.csv")
    images = pd.read_csv(data_dir / "images.csv")
    
    # Build indexes for O(1) lookup
    profile_by_user = profiles.set_index("user_id").to_dict("index")
    events_by_user = events.groupby("user_id")
    events_by_id = events.set_index("event_id").to_dict("index")
    rates_index = build_fx_index(rates)  # (rate_date, from_curr, to_curr) → rate
    payment_opts_by_req = payment_opts.groupby("request_id")
    messages_by_req = messages[messages["request_id"].notna()].groupby("request_id")
    messages_by_event = messages[messages["related_event_id"].notna()].groupby("related_event_id")
    images_by_event = images.set_index("related_event_id").to_dict("index")
    
    return Dataset(profiles, events, rates, requests, payment_opts, messages, images,
                   profile_by_user, events_by_user, events_by_id, rates_index,
                   payment_opts_by_req, messages_by_req, messages_by_event, images_by_event)
```

### 5.2 FX Conversion Module

```python
class FXConverter:
    """Handles all currency conversion with chaining via USD."""
    
    DIRECT_PAIRS = {
        ("EUR", "ZAR"): True,
        ("USD", "EUR"): True,
        ("USD", "IDR"): True,
        ("USD", "INR"): True,
        ("EUR", "USD"): True,  # from 2024-04
    }
    
    def __init__(self, rates_df: pd.DataFrame):
        self.rates = build_fx_index(rates_df)  # (rate_date, from, to) → Decimal
    
    def get_rate(self, from_curr: str, to_curr: str, rate_date: date) -> Decimal:
        """Find rate for date (nearest prior 15th). Chain via USD if needed."""
        if from_curr == to_curr:
            return Decimal('1')
        
        # Find nearest rate_date (monthly on 15th)
        rate_date_15 = date(rate_date.year, rate_date.month, 15)
        if rate_date_15 > rate_date:
            # Go to previous month
            if rate_date_15.month == 1:
                rate_date_15 = date(rate_date_15.year - 1, 12, 15)
            else:
                rate_date_15 = date(rate_date_15.year, rate_date_15.month - 1, 15)
        
        # Try direct
        if (from_curr, to_curr) in self.DIRECT_PAIRS:
            key = (rate_date_15, from_curr, to_curr)
            if key in self.rates:
                return self.rates[key]
        
        # Chain via USD
        if from_curr != "USD" and to_curr != "USD":
            rate1 = self.get_rate(from_curr, "USD", rate_date)
            rate2 = self.get_rate("USD", to_curr, rate_date)
            return rate1 * rate2
        
        raise ValueError(f"No rate path: {from_curr} → {to_curr} on {rate_date}")
    
    def convert(self, amount: Decimal, from_curr: str, to_curr: str, 
                rate_date: date) -> Decimal:
        rate = self.get_rate(from_curr, to_curr, rate_date)
        return (amount * rate).quantize(Decimal('0.01'))
```

### 5.3 Image Amount Extraction

```python
def extract_image_amounts(images_df: pd.DataFrame, events_df: pd.DataFrame,
                          media_dir: Path, anthropic_client) -> Dict[str, Decimal]:
    """Extract amounts from 16 images. Returns event_id → amount mapping."""
    # Load cached results if available
    cache_path = Path("cache/image_extractions.json")
    if cache_path.exists():
        return json.load(cache_path)
    
    # Build prompts for all 16 images
    image_data = []
    for _, img in images_df.iterrows():
        event = events_df[events_df["event_id"] == img["related_event_id"]].iloc[0]
        img_path = media_dir / f"{img['image_id']}.png"
        image_data.append((img['image_id'], img['related_event_id'], img_path, event))
    
    # Single multi-image call to Anthropic
    results = {}
    for image_id, event_id, img_path, event in image_data:
        # Resize/compress to reduce tokens
        img_b64 = encode_image_base64(img_path, max_size=1024)
        
        prompt = f"""Extract the monetary amount from this financial document.
Event context: {event['description']}, Category: {event['category']}, Currency: {event['currency']}
Return ONLY a JSON object: {{"amount": <number>, "currency": "<3-letter>"}}"""
        
        response = anthropic_client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=100,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": img_b64}},
                {"type": "text", "text": prompt}
            ]}]
        )
        result = json.loads(response.content[0].text)
        results[event_id] = Decimal(str(result["amount"]))
    
    # Cache
    cache_path.parent.mkdir(exist_ok=True)
    json.dump({k: str(v) for k, v in results.items()}, cache_path.open("w"))
    return results
```

---

## 6. Error Handling Strategy

| Failure Point | Fallback Behavior |
|---------------|-------------------|
| Image OCR fails / ambiguous | Use conservative estimate (lower bound); log warning; continue |
| LLM explanation returns invalid JSON | Retry once with stricter prompt; if fails, use template fallback |
| FX rate missing for date/pair | Chain via USD; if still missing, use nearest available rate; log |
| Message parsing fails | Ignore message; rely only on structured events |
| Recurrence detection ambiguous | Conservative: don't project |
| Output validation fails | Log error, write "not_recommended" row with explanation |
| API rate limit / timeout | Exponential backoff (max 3 retries); then use fallback |

**No external call is allowed to block the pipeline.** Every LLM call has a deterministic fallback.

---

## 7. File Structure

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
├── dataset/                    # (symlink to provided dataset/)
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
├── README.md
└── architecture.md             # This file
```

---

## 8. Main Entry Point (main.py)

```python
def main():
    # 1. Load environment
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    
    # 2. Initialize LLM client
    llm = LLMClient(api_key)
    
    # 3. Load all data
    data = load_all_data(Path("dataset"))
    
    # 4. Pre-extract image amounts (one-time, cached)
    image_amounts = extract_image_amounts(data.images, data.events, 
                                           Path("dataset/media/images"), llm)
    
    # 5. Apply image amounts to events
    apply_image_amounts(data.events, image_amounts)
    
    # 6. Convert all events to home_currency
    fx = FXConverter(data.exchange_rates)
    convert_events_to_home_currency(data.events, data.profiles, fx)
    
    # 7. Process each request
    results = []
    for _, req in data.requests.iterrows():
        context = build_request_context(req, data, fx)
        decision = decide_affordability(context, llm)
        results.append(decision.to_output_row())
    
    # 8. Validate and write output
    validate_output(results)
    write_output_csv(results, "output.csv")
    
    # 9. Write token usage report
    llm.write_usage_report("evaluation/usage_report.md")

if __name__ == "__main__":
    main()
```

---

## 9. Determinism Guarantees

1. **No randomness** — all algorithms deterministic
2. **Sorted iteration** — events, payment options, plans always sorted by ID/date
3. **Decimal arithmetic** — no float rounding
4. **Fixed LLM temperature=0** — explanations deterministic
5. **Cached LLM calls** — same input → same output
6. **Sorted output** — output.csv rows ordered by request_id

---

## 10. Performance Targets

| Metric | Target |
|--------|--------|
| Total runtime | < 60 seconds |
| Memory usage | < 500 MB |
| LLM Vision calls | 16 (one-time) |
| LLM Message calls | ≤ 50 (batched) |
| LLM Explanation calls | ≤ 10 (batched 25-50/req) |
| Total input tokens | ~200K |
| Total output tokens | ~50K |
| Estimated cost | < $5 |