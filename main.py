#!/usr/bin/env python3
"""
Buy or Wait? — Main Entry Point

Batch pipeline that reads dataset/, processes 250 affordability requests,
and writes output.csv with predictions.
"""
import os
import sys
from pathlib import Path
from decimal import Decimal

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

# Load environment
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

def main():
    """Main pipeline entry point."""
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your_key_here":
        print("ERROR: ANTHROPIC_API_KEY not set in .env", file=sys.stderr)
        sys.exit(1)
    
    print("Buy or Wait? — Starting pipeline...")
    print(f"Python: {sys.version}")
    print(f"Working directory: {Path.cwd()}")
    
    # TODO: Implement pipeline
    # 1. Load all data (data_loader.py)
    # 2. Extract image amounts (llm_client.py)
    # 3. Convert currencies (fx_converter.py)
    # 4. Process each request through financial engine
    # 5. Generate explanations (llm_client.py)
    # 6. Write output.csv (output_formatter.py)
    # 7. Write usage report (llm_client.py)
    
    print("Pipeline not yet implemented. See architecture.md for design.")
    return 1

if __name__ == "__main__":
    sys.exit(main())