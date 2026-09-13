#!/usr/bin/env python3
"""
Setup verification script for Buy or Wait? project.
Run this after setting up the environment to verify everything works.
"""
import sys
import os
import subprocess
from pathlib import Path
from decimal import Decimal

# Add src to path
sys.path.insert(0, str(Path(__file__).parent / "src"))

def check_python_version():
    """Verify Python version is 3.11+"""
    version = sys.version_info
    if version.major >= 3 and version.minor >= 11:
        return True, f"Python {version.major}.{version.minor}.{version.micro}"
    return False, f"Python {version.major}.{version.minor}.{version.micro} (need 3.11+)"

def check_imports():
    """Verify all required packages can be imported"""
    required = [
        ("anthropic", "anthropic"),
        ("pandas", "pandas"),
        ("PIL", "Pillow"),
        ("dotenv", "python-dotenv"),
        ("pydantic", "pydantic"),
        ("pytest", "pytest"),
        ("structlog", "structlog"),
        ("decimal", "stdlib"),
        ("json", "stdlib"),
        ("pathlib", "stdlib"),
    ]
    failed = []
    for module, package in required:
        try:
            __import__(module)
        except ImportError:
            failed.append(package)
    if failed:
        return False, f"Missing imports: {', '.join(failed)}"
    return True, "All imports successful"

def check_api_key():
    """Verify ANTHROPIC_API_KEY is set"""
    # Load .env if exists
    env_path = Path(__file__).parent / ".env"
    if env_path.exists():
        from dotenv import load_dotenv
        load_dotenv(env_path)
    
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your_key_here":
        return False, "ANTHROPIC_API_KEY not set or still placeholder"
    return True, "ANTHROPIC_API_KEY is set"

def check_dataset():
    """Verify dataset directory exists with all 8 CSVs"""
    dataset_dir = Path(__file__).parent / "dataset"
    required_files = [
        "financial_profiles.csv",
        "financial_events.csv",
        "exchange_rates.csv",
        "requests.csv",
        "sample_requests.csv",
        "request_payment_options.csv",
        "messages.csv",
        "images.csv",
    ]
    missing = []
    for f in required_files:
        if not (dataset_dir / f).exists():
            missing.append(f)
    if missing:
        return False, f"Missing dataset files: {', '.join(missing)}"
    return True, f"All {len(required_files)} dataset files present"

def check_media():
    """Verify media/images directory with 16 PNGs"""
    media_dir = Path(__file__).parent / "dataset" / "media" / "images"
    if not media_dir.exists():
        return False, "dataset/media/images directory not found"
    pngs = list(media_dir.glob("*.png"))
    if len(pngs) != 16:
        return False, f"Expected 16 PNGs, found {len(pngs)}"
    return True, f"16 PNG images found"

def check_api_connectivity():
    """Make one minimal API call to verify connectivity"""
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent / ".env")
    
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key or api_key == "your_key_here":
        return False, "Skipped (no API key)"
    
    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
        # Minimal call - just list models or send a tiny message
        response = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}]
        )
        if response.content:
            return True, "API connectivity verified"
        return False, "API returned empty response"
    except Exception as e:
        return False, f"API call failed: {e}"

def check_project_structure():
    """Verify project directory structure matches architecture.md"""
    base = Path(__file__).parent
    required_dirs = [
        "src",
        "evaluation",
        "cache",
        "tests",
        "dataset",
        "dataset/media/images",
    ]
    missing = []
    for d in required_dirs:
        if not (base / d).exists():
            missing.append(d)
    if missing:
        return False, f"Missing directories: {', '.join(missing)}"
    return True, "Project structure matches architecture.md"

def run_checks():
    """Run all verification checks"""
    checks = [
        ("Python Version", check_python_version),
        ("Imports", check_imports),
        ("API Key", check_api_key),
        ("Dataset Files", check_dataset),
        ("Media Images", check_media),
        ("Project Structure", check_project_structure),
        ("API Connectivity", check_api_connectivity),
    ]
    
    print("=" * 60)
    print("BUY OR WAIT? - SETUP VERIFICATION")
    print("=" * 60)
    
    all_passed = True
    for name, check_fn in checks:
        try:
            passed, msg = check_fn()
            status = "PASS" if passed else "FAIL"
            print(f"[{status}] {name}: {msg}")
            if not passed:
                all_passed = False
        except Exception as e:
            print(f"[FAIL] {name}: Exception - {e}")
            all_passed = False
    
    print("=" * 60)
    if all_passed:
        print("ALL CHECKS PASSED ✓")
        return 0
    else:
        print("SOME CHECKS FAILED ✗")
        return 1

if __name__ == "__main__":
    sys.exit(run_checks())