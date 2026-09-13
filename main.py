#!/usr/bin/env python3
"""
Buy or Wait? — Main Pipeline Entry Point

Batch pipeline processing all 250 affordability requests in dataset/requests.csv.
Integrates data_loader, financial_engine, llm_client, and output_formatter.
Produces output.csv, evaluation/usage_report.md, and output_checkpoint.json.
"""

import os
import sys
import json
import time
from pathlib import Path
from datetime import datetime
import pandas as pd
import structlog

# Add src to sys.path
sys.path.insert(0, str(Path(__file__).parent / "src"))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

from src.data_loader import load_all_datasets, get_request_context, classify_events, apply_exchange_rate
from src.financial_engine import compute_amount_safe_to_pay, get_earliest_full_payment_date, find_spending_changes, rank_and_select_plan
from src.llm_client import LLMClient
from src.output_formatter import build_output_row, validate_output, write_output_csv

logger = structlog.get_logger()


def run_pipeline(checkpoint_path: str = "output_checkpoint.json", output_path: str = "output.csv", report_path: str = "evaluation/usage_report.md"):
    """
    Run full 250 request batch pipeline with checkpointing and resume support.
    """
    start_time = time.time()
    print("=" * 60)
    print("BUY OR WAIT? — STARTING BATCH PROCESSING PIPELINE")
    print("=" * 60)

    # 1. Initialize LLM Client
    llm = LLMClient()
    print(f"[INIT] LLM Client configured: {llm.is_configured()} (model: {llm.model})")

    # 2. Load all datasets once
    print("[INIT] Loading datasets from dataset/...")
    data = load_all_datasets("dataset", debug=False)
    requests_df = data["requests"]
    total_requests = len(requests_df)
    print(f"[INIT] Loaded {total_requests} target requests from dataset/requests.csv")

    # 3. Load existing checkpoint file if available
    chk_file = Path(checkpoint_path)
    checkpoint: dict = {}
    if chk_file.exists():
        try:
            checkpoint = json.loads(chk_file.read_text(encoding="utf-8"))
            print(f"[RESUME] Loaded checkpoint with {len(checkpoint)} completed requests.")
        except Exception as e:
            print(f"[WARN] Failed to load checkpoint: {e}. Starting fresh.")
            checkpoint = {}

    results: list = []
    fallback_count = 0

    # 4. Iterate over all 250 requests
    for idx, (_, req) in enumerate(requests_df.iterrows(), 1):
        req_id = str(req["request_id"])
        
        # Checkpoint skip
        if req_id in checkpoint:
            print(f"[{idx}/{total_requests}] Processing request: {req_id} (RESTORED FROM CHECKPOINT)")
            results.append(checkpoint[req_id])
            continue
            
        print(f"[{idx}/{total_requests}] Processing request: {req_id}...")
        
        try:
            # a. Build RequestContext
            ctx = get_request_context(req_id, data)
            
            # b. Classify financial events
            ctx.events = classify_events(ctx.events)
            
            # c. Vision amount extraction for missing image events
            if not ctx.images.empty and not ctx.events.empty:
                missing_mask = ctx.events["amount"].isna()
                if missing_mask.any():
                    for ev_idx, ev in ctx.events[missing_mask].iterrows():
                        ev_id = ev["event_id"]
                        img_match = ctx.images[ctx.images["related_event_id"] == ev_id]
                        if not img_match.empty:
                            img_id = img_match.iloc[0]["image_id"]
                            img_path = Path("dataset/media/images") / f"{img_id}.png"
                            if img_path.exists():
                                ctx_desc = f"{ev.get('description', '')} ({ev.get('category', '')})"
                                extracted_amt = llm.extract_amount_from_image(img_path, ctx_desc)
                                if extracted_amt:
                                    ctx.events.at[ev_idx, "amount"] = extracted_amt
                                    print(f"  [VISION] Extracted {img_id}: {extracted_amt}")

            # d. Message fact interpretation
            if not ctx.messages.empty:
                msg_texts = [str(m["message_text"]) for _, m in ctx.messages.iterrows()]
                facts_data = llm.interpret_messages(msg_texts, str(req.get("request_text", "")))
                facts = facts_data.get("facts", [])
                
                # Apply high confidence cancellation facts
                for fact in facts:
                    if fact.get("type") == "cancellation" and fact.get("confidence") == "high":
                        c_ev_id = fact.get("event_id")
                        if c_ev_id and not ctx.events.empty:
                            c_mask = ctx.events["event_id"] == c_ev_id
                            ctx.events.loc[c_mask, "status"] = "cancelled"

            # e. FX currency conversion to home currency
            home_curr = str(ctx.profile["home_currency"])
            rates_df = ctx.exchange_rates
            
            if not ctx.events.empty:
                for ev_idx, ev in ctx.events.iterrows():
                    ev_curr = str(ev.get("currency", home_curr))
                    ev_amt = ev.get("amount")
                    ev_dt = ev.get("settlement_date") or ev.get("event_date")
                    
                    if pd.notna(ev_amt) and ev_curr != home_curr:
                        try:
                            converted = apply_exchange_rate(float(ev_amt), ev_curr, home_curr, ev_dt, rates_df)
                            ctx.events.at[ev_idx, "amount"] = converted
                            ctx.events.at[ev_idx, "currency"] = home_curr
                        except Exception as e:
                            logger.warning(f"FX conversion failed for event {ev.get('event_id')}: {e}")

            # f. Quantitative Financial Engine Decision
            requested_amount = float(req["requested_amount"])
            req_date = req["request_date"].date() if isinstance(req["request_date"], (pd.Timestamp, str)) else req["request_date"]
            
            safe_amount = compute_amount_safe_to_pay(ctx, req_date)
            earliest_date = get_earliest_full_payment_date(ctx, requested_amount)
            shortfall = requested_amount - safe_amount
            spending_changes = find_spending_changes(ctx, shortfall)
            
            selected_plan = rank_and_select_plan(ctx, safe_amount, earliest_date, ctx.payment_options, spending_changes)
            
            # g. LLM Decision Explanation
            key_figures = {
                "currency": home_curr,
                "requested_amount": requested_amount,
                "minimum_balance": float(ctx.profile["minimum_balance_to_keep"]),
                "min_available_balance": float(ctx.profile["minimum_balance_to_keep"]),
                "desired_completion_date": req["desired_completion_date"]
            }
            
            explanation = llm.generate_decision_explanation(ctx, selected_plan, key_figures)
            selected_plan.decision_explanation = explanation
            
            # h. Format output row
            row = build_output_row(req_id, selected_plan, ctx)
            
            # i. Save to checkpoint
            checkpoint[req_id] = row
            chk_file.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
            results.append(row)
            
        except Exception as e:
            logger.error(f"Error processing request {req_id}: {e}")
            print(f"  [ERROR] Request {req_id} failed: {e}. Writing fallback row.")
            fallback_count += 1
            
            # Fallback row on error
            fallback_row = {
                "request_id": req_id,
                "amount_safe_to_pay": 0.0,
                "affordability_status": "not_affordable",
                "recommended_payment_method": "not_recommended",
                "payment_plan": "none",
                "earliest_date_for_full_payment": "",
                "spending_changes_needed": "none",
                "decision_explanation": "Unable to verify request affordability safely."
            }
            checkpoint[req_id] = fallback_row
            chk_file.write_text(json.dumps(checkpoint, indent=2), encoding="utf-8")
            results.append(fallback_row)

    # 5. Order results matching requests.csv order
    ordered_results = []
    for _, req in requests_df.iterrows():
        rid = str(req["request_id"])
        if rid in checkpoint:
            ordered_results.append(checkpoint[rid])

    # 6. Validate and write output.csv
    print(f"\n[OUTPUT] Validating {len(ordered_results)} predictions...")
    validate_output(ordered_results)
    write_output_csv(ordered_results, output_path)
    print(f"[OUTPUT] Wrote predictions to {output_path} ✓")

    # 7. Write usage report
    llm.tracker.write_usage_report(report_path)
    print(f"[REPORT] Wrote token usage report to {report_path} ✓")

    elapsed = time.time() - start_time
    report = llm.tracker.get_report()
    
    print("=" * 60)
    print("PIPELINE EXECUTION COMPLETE")
    print(f"- Total Requests Processed: {len(ordered_results)}/250")
    print(f"- Fallback Rows: {fallback_count}")
    print(f"- Elapsed Time: {elapsed:.2f} seconds ({elapsed/60.0:.2f} minutes)")
    print(f"- Total API Calls: {report['total_calls']}")
    print(f"- Total Tokens: {report['total_input_tokens'] + report['total_output_tokens']:,}")
    print(f"- Estimated Cost: ${report['total_cost']:.4f}")
    print("=" * 60)
    
    return 0


if __name__ == "__main__":
    sys.exit(run_pipeline())