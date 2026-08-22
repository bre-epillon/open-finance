"""Pure series transforms. No I/O, no registry knowledge, no config.

Every function takes a pandas Series with a sorted DatetimeIndex and returns
one of the same shape. All windows are trailing: a statistic at time t uses
only data up to and including t. That is not a stylistic preference -- a
full-sample z-score scores 1995 using 2026's variance, which makes any
historical validation of the model meaningless.
"""

import numpy as np
import pandas as pd

# Defaults. Overridable at every call site; set by the grid search in
# scripts/validate_history.py rather than picked for looking round.
Z_WINDOW = 120       # months -- 10 years of macro history per z-score
Z_MIN_PERIODS = 60   # 5 years before a z-score is reported at all
DIFF_PERIODS = 3     # months -- the Delta/Gamma horizon
RANK_WINDOW = 250    # trading days -- ~1 year for the sentiment percentiles
RANK_MIN_PERIODS = 60


def _check(s: pd.Series, name: str = "series") -> pd.Series:
    if not isinstance(s, pd.Series):
        raise TypeError(f"{name} must be a pandas Series, got {type(s).__name__}")
    if not isinstance(s.index, pd.DatetimeIndex):
        raise TypeError(f"{name} must have a DatetimeIndex")
    if not s.index.is_monotonic_increasing:
        raise ValueError(f"{name} index must be sorted ascending")
    return s.astype("float64")


def yoy(s: pd.Series, periods: int = 12) -> pd.Series:
    """Year-over-year percent change.

    For index levels (CPI, industrial production, payrolls, M2). `periods` is
    in index steps, so 12 on a monthly series and 4 on a quarterly one.
    """
    s = _check(s, "yoy input")
    prev = s.shift(periods)
    # Guard the zero denominator explicitly rather than letting it produce inf,
    # which survives arithmetic and poisons a composite silently.
    return ((s - prev) / prev.replace(0.0, np.nan)) * 100.0


def delta(s: pd.Series, periods: int = DIFF_PERIODS) -> pd.Series:
    """Change over `periods` steps -- momentum.

    Three months rather than one: monthly macro prints get revised, and a
    1-month difference flips sign on revisions alone.
    """
    s = _check(s, "delta input")
    return s - s.shift(periods)


def gamma(s: pd.Series, periods: int = DIFF_PERIODS) -> pd.Series:
    """Change in the change over `periods` steps -- acceleration.

    Applied to the level, not to an already-differenced series, so gamma(s)
    is the second difference of s and not a fourth difference by accident.
    """
    return delta(delta(s, periods), periods)


def zscore(s: pd.Series, window: int = Z_WINDOW,
           min_periods: int = Z_MIN_PERIODS) -> pd.Series:
    """Trailing z-score over `window` steps.

    Returns NaN until `min_periods` observations exist, and where the trailing
    standard deviation is zero (a series that has not moved has no meaningful
    z-score, and dividing by it would give inf).
    """
    s = _check(s, "zscore input")
    roll = s.rolling(window, min_periods=min_periods)
    sd = roll.std()
    return (s - roll.mean()) / sd.where(sd > 0)


def pct_rank(s: pd.Series, window: int = RANK_WINDOW,
             min_periods: int = RANK_MIN_PERIODS) -> pd.Series:
    """Percentile rank of each value within its own trailing window, 0-100.

    This is what the spec asks for and what rolling min/max is not. Min/max
    scaling lets a single outlier pin the range for a whole window: after
    March 2020 every subsequent VIX reading looked calm by comparison, so a
    min/max-scaled fear index read "greed" through a bear market.
    """
    s = _check(s, "pct_rank input")
    return s.rolling(window, min_periods=min_periods).rank(pct=True) * 100.0


def weighted_mean(frame: pd.DataFrame, weights: dict[str, float] | None = None,
                  min_components: int = 1) -> pd.Series:
    """Row-wise weighted mean over available columns.

    Missing components are dropped from both numerator and denominator, never
    substituted with a neutral value. Substituting drags a composite toward
    the middle and makes "we could not measure this" indistinguishable in the
    output from "this measured as average" -- the specific bug in the parked
    fear_and_greed code, which defaulted absent components to 50.

    Rows with fewer than `min_components` available columns return NaN.
    """
    if frame.empty:
        return pd.Series(dtype="float64", index=frame.index)

    w = pd.Series(
        {c: float((weights or {}).get(c, 1.0)) for c in frame.columns},
        dtype="float64",
    )
    present = frame.notna()
    denom = present.mul(w, axis=1).sum(axis=1)
    numer = frame.mul(w, axis=1).sum(axis=1, skipna=True)
    out = numer / denom.where(denom > 0)
    return out.where(present.sum(axis=1) >= min_components)


def component_count(frame: pd.DataFrame) -> pd.Series:
    """How many components actually contributed to each row.

    Reported alongside every composite. A score built from two of five inputs
    is a different claim from one built from five, and the number is the only
    way a consumer can tell.
    """
    return frame.notna().sum(axis=1).astype("int64")
