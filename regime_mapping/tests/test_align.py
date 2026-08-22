"""Frequency alignment, publication lag, and axis composites."""

import numpy as np
import pandas as pd
import pytest

from conftest import monthly
from core.align import (DELTA, GAMMA, LEVEL, apply_lag, axis_composite,
                        axis_frame, normalise, prepare, to_monthly)
from core.series import GROWTH, INFLATION, REGISTRY


def test_to_monthly_takes_the_last_observation_not_the_mean():
    """Averaging a month of daily data is a different quantity from a print."""
    idx = pd.to_datetime(["2024-01-05", "2024-01-15", "2024-01-31"])
    s = pd.Series([1.0, 2.0, 9.0], index=idx)
    assert to_monthly(s).iloc[0] == 9.0


def test_to_monthly_forward_fills_a_quarterly_series():
    q = pd.Series([1.0, 2.0], index=pd.to_datetime(["2024-01-01", "2024-04-01"]))
    out = to_monthly(q)
    # Jan..Apr = 4 month-ends; Feb and Mar carry January's print forward.
    assert out.tolist() == [1.0, 1.0, 1.0, 2.0]


def test_to_monthly_never_backfills():
    """A leading gap must stay a gap. Backfilling leaks the future."""
    s = pd.Series([np.nan, np.nan, 5.0],
                  index=pd.to_datetime(["2024-01-31", "2024-02-29", "2024-03-31"]))
    out = to_monthly(s)
    assert np.isnan(out.iloc[0]) and np.isnan(out.iloc[1])
    assert out.iloc[2] == 5.0


def test_apply_lag_delays_the_value():
    out = apply_lag(monthly([1.0, 2.0, 3.0]), 1)
    assert np.isnan(out.iloc[0])
    assert out.iloc[1] == 1.0, "January's print appears at the February point"
    assert out.iloc[2] == 2.0


def test_apply_lag_zero_is_a_noop():
    s = monthly([1.0, 2.0, 3.0])
    pd.testing.assert_series_equal(apply_lag(s, 0), s)


def test_prepare_does_not_difference_a_rate_series_again():
    """GDP_Growth is already an annualised percent change.

    transform='none' in the registry is load-bearing: applying YoY to it would
    yield acceleration, and the regime map would be one derivative out.
    """
    spec = REGISTRY["GDP_Growth"]
    assert spec.transform == "none"
    q = pd.Series([2.0, 2.0, 2.0],
                  index=pd.to_datetime(["2024-01-01", "2024-04-01", "2024-07-01"]))
    out = prepare(q, spec).dropna()
    assert out.eq(2.0).all(), "a constant growth rate must stay constant"


def test_prepare_applies_yoy_to_an_index_level():
    spec = REGISTRY["Inflation_CPI"]
    assert spec.transform == "yoy"
    level = monthly([100.0 * (1.05 ** (m / 12)) for m in range(30)])
    out = prepare(level, spec).dropna()
    assert out.iloc[-1] == pytest.approx(5.0, abs=0.01)


def test_prepare_rejects_an_unknown_transform():
    from dataclasses import replace
    spec = replace(REGISTRY["Inflation_CPI"], transform="wibble")
    with pytest.raises(ValueError, match="unknown transform"):
        prepare(monthly([1.0] * 20), spec)


def _growth_raw(n, unemployment_path):
    """Minimal growth-axis input: two series, one of them unemployment."""
    return {
        "Industrial_Production": monthly(
            [100.0 * 1.02 ** (m / 12) for m in range(n)]),
        "Unemployment": monthly(unemployment_path),
    }


def test_unemployment_enters_the_growth_axis_negated():
    """A flipped sign here produces a plausible, entirely wrong regime map."""
    n = 200
    assert REGISTRY["Unemployment"].sign == -1
    rising = _growth_raw(n, np.linspace(4.0, 10.0, n))
    falling = _growth_raw(n, np.linspace(10.0, 4.0, n))

    z_rising = axis_frame(rising, GROWTH, LEVEL, window=60, min_periods=36)
    z_falling = axis_frame(falling, GROWTH, LEVEL, window=60, min_periods=36)

    # Rising unemployment must contribute NEGATIVELY to growth.
    assert z_rising["Unemployment"].dropna().iloc[-1] < 0
    assert z_falling["Unemployment"].dropna().iloc[-1] > 0


def test_axis_composite_respects_min_components():
    n = 200
    raw = {"Industrial_Production": monthly(
        [100.0 * 1.02 ** (m / 12) for m in range(n)])}
    comp, frame = axis_composite(raw, GROWTH, LEVEL, min_components=2,
                                 window=60, min_periods=36)
    assert list(frame.columns) == ["Industrial_Production"]
    assert comp.dropna().empty, "one input is not a composite"

    comp2, _ = axis_composite(raw, GROWTH, LEVEL, min_components=1,
                              window=60, min_periods=36)
    assert not comp2.dropna().empty


def test_axis_composite_weights_consumer_sentiment_at_half():
    assert REGISTRY["Consumer_Sentiment"].weight == 0.5


def test_axis_composite_of_nothing_is_empty_not_an_error():
    comp, frame = axis_composite({}, INFLATION)
    assert comp.empty and frame.empty


# --------------------------------------------------------------------------
# normalise -- the delta-of-z trap
# --------------------------------------------------------------------------

def test_normalise_level_is_a_trailing_zscore():
    s = monthly(list(range(1, 41)))
    out = normalise(s, LEVEL, window=10, min_periods=10)
    roll = s.rolling(10)
    expected = (s - roll.mean()) / roll.std()
    pd.testing.assert_series_equal(out, expected, check_names=False)


def test_normalise_delta_keeps_the_sign_of_the_underlying_move():
    """The reason Delta is not computed as the difference of the z-score.

    A series falling steadily for 30 of the last 120 months is unambiguously
    falling. delta(zscore(p)) reports it as RISING, because the trailing
    standard deviation in the denominator grows faster than the numerator
    falls once the move occupies a meaningful share of the window. Dividing an
    undifferenced scale into a differenced level does not have that failure.
    """
    n, trend = 240, 30
    v = np.full(n, 2.0)
    v[-trend:] = np.linspace(2.0, -2.0, trend)
    p = monthly(v + 0.2 * np.sin(np.arange(n) / 6.0))

    ours = normalise(p, DELTA, diff_periods=3, window=120, min_periods=60)
    assert ours.iloc[-1] < 0, "a falling series must have a negative Delta"

    z = normalise(p, LEVEL, window=120, min_periods=60)
    naive = z - z.shift(3)
    assert naive.iloc[-1] > 0, (
        "guard on the trap itself: if delta-of-z stops inverting here, "
        "re-derive whether normalise still needs to avoid it")


def test_normalise_delta_of_an_unmoving_series_is_zero_not_noise():
    """The right zero. Confidence in core/regime.py depends on it.

    A series that moves and then plateaus has a numerator of exactly zero
    across the plateau, so it produces no signal -- whereas delta of a
    z-score keeps drifting as the trailing mean catches up.
    """
    v = list(np.linspace(0.0, 10.0, 120)) + [10.0] * 40
    p = monthly(v)
    out = normalise(p, DELTA, diff_periods=3, window=100, min_periods=60)
    assert out.iloc[-1] == pytest.approx(0.0, abs=1e-12)


def test_normalise_gamma_of_a_constant_slope_is_zero():
    p = monthly([float(3 * t) for t in range(200)])
    out = normalise(p, GAMMA, diff_periods=3, window=100, min_periods=60)
    assert out.dropna().abs().max() == pytest.approx(0.0, abs=1e-12)


def test_normalise_rejects_an_unknown_operator():
    with pytest.raises(ValueError, match="unknown operator"):
        normalise(monthly([1.0] * 100), "sideways")
