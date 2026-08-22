import os
import sys

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def monthly(values, start="1980-01-31"):
    """Monthly Series from a list, month-end index."""
    idx = pd.date_range(start, periods=len(values), freq="ME")
    return pd.Series(np.asarray(values, dtype="float64"), index=idx)


def ramp(n, start, end):
    """Linear path from start to end over n points."""
    return np.linspace(start, end, n)


@pytest.fixture
def n_months():
    """Long enough for a 120-month z-score window plus Delta/Gamma room."""
    return 480


def index_series(n, growth_pct, start=100.0):
    """An index level that grows at a constant annual percent rate.

    Used where the registry applies a 'yoy' transform, so the test fixture has
    to be a level rather than a rate.
    """
    monthly_rate = (1.0 + growth_pct / 100.0) ** (1.0 / 12.0)
    return start * monthly_rate ** np.arange(n)


def level_from_yoy(yoy_path, start=100.0):
    """Build an index level whose year-over-year rate follows yoy_path.

    Compounds month by month at the annualised rate given for that month, so
    a test can specify the economics it wants (inflation falling from 6% to
    1%) and get a level series the 'yoy' transform will reproduce it from.
    """
    yoy_path = np.asarray(yoy_path, dtype="float64")
    rates = (1.0 + yoy_path / 100.0) ** (1.0 / 12.0)
    return start * np.cumprod(rates)
