"""Sample requests evaluation test suite."""
import pytest
from pathlib import Path
import pandas as pd

def test_sample_requests_exist():
    sample_file = Path("dataset/sample_requests.csv")
    assert sample_file.exists()
    df = pd.read_csv(sample_file)
    assert len(df) == 25
