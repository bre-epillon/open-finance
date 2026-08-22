"""Frequency alignment, per-component normalisation, and axis composites.

The regime engine works at monthly frequency. GDP is quarterly, CPI monthly,
breakevens daily; a daily regime series would be almost entirely interpolation
noise, and Dalio's framework is a quarters-to-years framework regardless.

Three alignment rules, applied here and nowhere else:

1. Resample to month-end taking the LAST observation in the month. Never the
   mean -- averaging a month of daily breakevens is a different quantity from
   a single monthly CPI print, and mixing the two makes the axis incomparable
   across series.
2. Forward-fill only. A backward fill leaks future information into the past
   and would make any historical validation look better than the model is.
3. Shift by the publication lag from the registry, so a value appears in the
   series at the date it was knowable rather than the date it describes.
"""

import pandas as pd

from core import transforms as T
from core.series import MacroSeries, by_axis

MONTH_END = "ME"

LEVEL = "level"
DELTA = "delta"
GAMMA = "gamma"


def to_monthly(s: pd.Series) -> pd.Series:
    """Month-end resample, last observation wins, forward-filled.

    Forward-filling here is what carries a quarterly GDP print across the two
    months that follow it, and a Friday breakeven across a month-end weekend.
    """
    if s.empty:
        return s
    return s.resample(MONTH_END).last().ffill()


def apply_lag(s: pd.Series, lag_months: int) -> pd.Series:
    """Delay a monthly series by its publication lag.

    CPI for March is published in mid-April, so on a month-end monthly index
    the March value belongs at the April point. Positive shift on a regular
    monthly index does exactly that. Lag 0 (market prices) is a no-op.
    """
    if lag_months <= 0:
        return s
    return s.shift(lag_months)


def prepare(s: pd.Series, spec: MacroSeries) -> pd.Series:
    """One raw series -> monthly, transformed, publication-lagged, signed.

    Transform order matters: resample first, then transform. Every 'yoy' entry
    in the registry is natively monthly, so a 12-period shift after resampling
    is a true year-over-year; doing it before would give a year-over-year in
    trading days for the daily series.

    The registry sign is applied here rather than downstream because it
    commutes with every later operation (differencing and z-scoring are both
    linear), and one multiplication is easier to audit than three.
    """
    m = to_monthly(s)
    if spec.transform == "yoy":
        m = T.yoy(m, periods=12)
    elif spec.transform != "none":
        raise ValueError(f"unknown transform {spec.transform!r} for {spec.name}")
    return apply_lag(m, spec.lag_months) * spec.sign


def normalise(p: pd.Series, op: str, diff_periods: int = T.DIFF_PERIODS,
              window: int = T.Z_WINDOW,
              min_periods: int = T.Z_MIN_PERIODS) -> pd.Series:
    """Scale one prepared series to comparable units, as a level or a change.

    All three operators divide by the same thing: the trailing standard
    deviation of the LEVEL. The result is in units of "this series' own
    typical variation", which is what makes an unemployment rate and an
    industrial-production growth rate addable.

    Why the change is not simply the difference of the z-score
    ---------------------------------------------------------
    Because delta(z) has the wrong sign on any sustained move. z = (p - mu)/sd
    with mu and sd both trailing, so differencing it differences the
    normalisation too. Once a move has run for a meaningful fraction of the
    window, sd is growing faster than (p - mu) is falling, and delta(z) turns
    positive while the series is still dropping. Measured on the synthetic
    scenarios in tests/test_regime.py, delta(z) reports growth ACCELERATING
    through a collapse from +2% to -2%.

    Taking the difference of the level and dividing by an undifferenced scale
    keeps the numerator honest -- it is a real change in real units -- and
    keeps the denominator slow-moving. It also keeps the right zero: a series
    that has not moved has a numerator of zero, so no move means no signal,
    which is what makes the confidence measure in core/regime.py mean
    anything.
    """
    scale = p.rolling(window, min_periods=min_periods).std()
    scale = scale.where(scale > 0)
    if op == LEVEL:
        mean = p.rolling(window, min_periods=min_periods).mean()
        return (p - mean) / scale
    if op == DELTA:
        return T.delta(p, diff_periods) / scale
    if op == GAMMA:
        return T.gamma(p, diff_periods) / scale
    raise ValueError(f"unknown operator {op!r}")


def axis_frame(raw: dict[str, pd.Series], axis: str, op: str = LEVEL,
               **kw) -> pd.DataFrame:
    """Every normalised component of one axis, as columns.

    Returned rather than collapsed straight to a composite because the API and
    the MCP server both need to say *why* an axis moved, and because a
    per-component view is how a wrong sign gets spotted.
    """
    cols: dict[str, pd.Series] = {}
    for spec in by_axis(axis):
        s = raw.get(spec.name)
        if s is None or s.dropna().empty:
            continue
        cols[spec.name] = normalise(prepare(s, spec), op, **kw)

    if not cols:
        return pd.DataFrame(dtype="float64")
    return pd.DataFrame(cols).sort_index()


def axis_composite(raw: dict[str, pd.Series], axis: str, op: str = LEVEL,
                   min_components: int = 2,
                   **kw) -> tuple[pd.Series, pd.DataFrame]:
    """(composite, component frame) for one axis.

    min_components=2 by default: a "growth" reading resting on a single
    surviving input is not a composite, and reporting it as one would be the
    kind of quietly-wrong number this project exists to avoid.
    """
    frame = axis_frame(raw, axis, op, **kw)
    if frame.empty:
        return pd.Series(dtype="float64"), frame
    weights = {s.name: s.weight for s in by_axis(axis)}
    comp = T.weighted_mean(frame, weights, min_components=min_components)
    return comp, frame
