"""Greed & Fear index, with the three ported-in defects asserted fixed."""

import numpy as np
import pandas as pd
import pytest

from core import sentiment as S
from core import transforms as T

DAYS = 900


def trading_days(n=DAYS, start="2019-01-02"):
    """Business-day index. Deliberately NOT calendar days -- see the module
    docstring in core/sentiment.py, defect 3."""
    return pd.bdate_range(start, periods=n)


def prices(spx=None, vix=None, tlt=None, n=DAYS):
    idx = trading_days(n)
    data = {}
    data[S.SPX] = np.asarray(spx if spx is not None else
                             100.0 * 1.0002 ** np.arange(n), dtype="float64")
    data[S.VIX] = np.asarray(vix if vix is not None else
                             np.full(n, 18.0) + np.sin(np.arange(n) / 30.0),
                             dtype="float64")
    if tlt is not False:
        data[S.BONDS] = np.asarray(tlt if tlt is not None else
                                   np.full(n, 95.0), dtype="float64")
    return pd.DataFrame(data, index=idx)


def universe(n_names=25, n=DAYS, rising=True, seed=3):
    """Wide price frame for the breadth component."""
    rng = np.random.default_rng(seed)
    idx = trading_days(n)
    drift = 0.0004 if rising else -0.0004
    cols = {
        f"T{i}": 100.0 * np.cumprod(1.0 + drift + rng.normal(0, 0.004, n))
        for i in range(n_names)
    }
    return pd.DataFrame(cols, index=idx)


# --------------------------------------------------------------------------
# labels
# --------------------------------------------------------------------------

@pytest.mark.parametrize("score,expected", [
    (0.0, "Extreme Fear"), (24.99, "Extreme Fear"),
    (25.0, "Fear"), (44.99, "Fear"),
    (45.0, "Neutral"), (50.0, "Neutral"), (54.99, "Neutral"),
    (55.0, "Greed"), (74.99, "Greed"),
    (75.0, "Extreme Greed"), (100.0, "Extreme Greed"),
])
def test_label_boundaries(score, expected):
    assert S.classify(score) == expected


def test_neutral_band_is_symmetric_around_fifty():
    """The parked code used 50-54, which is not centred on anything."""
    assert S.classify(45.0) == "Neutral" and S.classify(54.9) == "Neutral"
    assert S.classify(44.9) == "Fear" and S.classify(55.0) == "Greed"


def test_label_of_missing_score_is_unknown_not_neutral():
    assert S.classify(float("nan")) == "Unknown"


# --------------------------------------------------------------------------
# components
# --------------------------------------------------------------------------

def test_momentum_is_positive_above_the_moving_average():
    p = prices()
    assert S.momentum(p).dropna().iloc[-1] > 0


def test_volatility_component_is_inverted_so_a_vol_spike_reads_as_fear():
    """The component measures VIX against its own 50-day average, so what it
    scores is a MOVE in volatility rather than its level -- see the docstring
    on core.sentiment.volatility. The fixtures move it accordingly."""
    n = DAYS
    base = np.full(n, 18.0) + np.sin(np.arange(n) / 30.0)
    spike = base.copy()
    spike[-5:] = 45.0
    drop = base.copy()
    drop[-5:] = 9.0
    calm_score = S.build(prices(vix=drop))["volatility"].iloc[-1]
    panic_score = S.build(prices(vix=spike))["volatility"].iloc[-1]
    assert calm_score > panic_score
    assert panic_score < 50.0 < calm_score


def test_safe_haven_prefers_equities_when_they_outrun_bonds():
    n = DAYS
    up = 100.0 * 1.001 ** np.arange(n)
    flat = np.full(n, 95.0)
    assert S.safe_haven(prices(spx=up, tlt=flat)).dropna().iloc[-1] > 0
    assert S.safe_haven(prices(spx=flat, tlt=up)).dropna().iloc[-1] < 0


def test_junk_bond_component_is_inverted_so_wide_spreads_read_as_fear():
    p = prices()
    tight = pd.Series(np.full(DAYS, 3.0), index=p.index)
    wide = tight.copy()
    wide.iloc[-60:] = 12.0
    assert S.build(p, junk=wide)["junk_bond"].iloc[-1] < 50.0


def test_breadth_is_high_when_most_names_are_above_their_average():
    u = universe(rising=True)
    b = S.breadth(u).dropna()
    assert b.iloc[-1] > 60.0
    d = S.breadth(universe(rising=False)).dropna()
    assert d.iloc[-1] < 40.0


def test_breadth_is_nan_with_too_few_constituents():
    """A breadth reading off three tickers is noise wearing the name of a
    signal. open-finance holds several tickers with only days of history."""
    thin = universe(n_names=S.BREADTH_MIN_CONSTITUENTS - 1)
    assert S.breadth(thin).dropna().empty


def test_breadth_accepts_exactly_the_minimum():
    ok = universe(n_names=S.BREADTH_MIN_CONSTITUENTS)
    assert not S.breadth(ok).dropna().empty


# --------------------------------------------------------------------------
# the three ported-in defects
# --------------------------------------------------------------------------

def test_vix_is_not_counted_twice():
    """Defect 1. The parked code derived both `volatility` and `put_call`
    from ^VIX, giving VIX two of five equal-weighted votes."""
    assert "put_call" not in S.COMPONENTS
    assert "breadth" in S.COMPONENTS
    assert len(S.COMPONENTS) == 5


def test_scores_are_percentiles_not_minmax_scaled():
    """Defect 2. Under min/max scaling, one crisis spike pins the range for a
    whole window, so every later reading looks calm by comparison -- which is
    how a fear index reads "greed" through a bear market. A percentile rank
    does not compress like that."""
    n = DAYS
    vix = np.full(n, 16.0) + np.sin(np.arange(n) / 25.0)
    vix[300] = 85.0                      # one enormous spike, long past
    frame = S.build(prices(vix=vix))
    after = frame["volatility"].iloc[400:]
    assert after.max() - after.min() > 25.0, (
        "post-spike readings collapsed into a narrow band -- that is the "
        "min/max artefact this fix exists to remove")


def test_no_calendar_resampling_so_the_index_stays_trading_days():
    """Defect 3. resample('D') turned 250 trading days into ~8 months and
    forward-filled weekends in as duplicate values."""
    p = prices()
    out = S.build(p)
    assert out.index.isin(p.index).all()
    assert out.index.dayofweek.max() <= 4, "a weekend appeared in the output"


def test_missing_components_are_dropped_not_defaulted_to_fifty():
    """The fourth, smaller fix. Substituting 50 drags the composite toward
    neutral and makes "not measurable" indistinguishable from "average"."""
    p = prices()
    full = S.build(p, junk=pd.Series(np.full(DAYS, 3.0), index=p.index),
                   universe=universe())
    partial = S.build(p)
    assert full["components"].iloc[-1] == 5
    assert partial["components"].iloc[-1] == 3
    assert "junk_bond" not in partial.columns


# --------------------------------------------------------------------------
# build
# --------------------------------------------------------------------------

def test_composite_stays_within_bounds():
    p = prices()
    out = S.build(p, junk=pd.Series(np.full(DAYS, 4.0), index=p.index),
                  universe=universe())
    assert out["composite"].between(0.0, 100.0).all()


def test_build_requires_spx_and_vix():
    p = prices().drop(columns=[S.VIX])
    with pytest.raises(ValueError, match="missing required columns"):
        S.build(p)


def test_build_tolerates_a_missing_bond_series():
    p = prices(tlt=False)
    out = S.build(p, junk=pd.Series(np.full(DAYS, 4.0), index=p.index))
    assert "safe_haven" not in out.columns
    assert not out.empty


def test_build_drops_rows_with_too_few_components():
    """Only momentum and volatility are available here -- two of the required
    three -- so the correct output is nothing at all rather than a composite
    built from half the inputs."""
    out = S.build(prices(tlt=False))
    assert out.empty


def test_build_keeps_rows_once_the_minimum_is_met():
    p = prices()
    out = S.build(p, junk=pd.Series(np.full(DAYS, 4.0), index=p.index))
    assert not out.empty
    assert out["components"].min() >= S.MIN_COMPONENTS


def test_junk_series_on_its_own_calendar_is_carried_forward_not_holed():
    """The junk spread is a daily FRED series with its own gaps; a plain
    reindex onto trading days would punch holes in it."""
    p = prices()
    sparse = pd.Series(np.linspace(3.0, 5.0, 40),
                       index=pd.date_range("2019-01-02", periods=40, freq="30D"))
    out = S.build(p, junk=sparse)
    assert out["junk_bond"].notna().mean() > 0.9


def test_reading_names_the_extremes():
    p = prices()
    out = S.build(p, junk=pd.Series(np.full(DAYS, 4.0), index=p.index),
                  universe=universe())
    text = S.reading(out.iloc[-1])
    assert "/100" in text
    assert "Most fearful" in text and "Most greedy" in text


def test_reading_survives_a_row_with_only_a_composite():
    row = pd.Series({"composite": 71.0})
    assert "Greed" in S.reading(row)
