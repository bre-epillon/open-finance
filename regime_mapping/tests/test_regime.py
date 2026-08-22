"""Regime classification: unit behaviour, then four end-to-end scenarios.

The scenarios matter more than the unit tests. A classifier can pass every
component check and still put the economy in the wrong quadrant, so each
scenario drives synthetic macro history with a known shape through the whole
pipeline -- resample, lag, z-score, composite, Delta -- and asserts the
quadrant that comes out the far end.

These are the synthetic stand-in for the historical face-validity table in
IMPLEMENTATION_PLAN.md section 7.2, which needs the live database and is
implemented in scripts/validate_history.py.
"""

import numpy as np
import pandas as pd
import pytest

from conftest import level_from_yoy
from core import regime as R

N = 480          # 40 years of monthly history
TREND = 30       # length of the closing move, in months
Z_KW = dict(window=120, min_periods=60)


def _noise(n, seed, scale=0.35, step=0.18):
    """Deterministic pseudo-random drift.

    A perfectly flat fixture is a degenerate case -- zero trailing standard
    deviation, so a NaN z-score by design (transforms.zscore) -- and a pure
    sine is worse, because every series moves in lockstep and a becalmed
    economy then reads as a confident regime call. A seeded random walk is
    both reproducible and shaped like the thing being modelled.
    """
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(0.0, step, n)) * scale


def _path(n, base, end, seed, trend=TREND):
    """Flat at `base`, then a linear move to `end` over the last `trend`
    points, over a random-walk background."""
    out = np.full(n, float(base))
    out[-trend:] = np.linspace(base, end, trend)
    return out + _noise(n, seed)


def scenario(growth_end, inflation_end, growth_base=2.0, inflation_base=2.0,
             n=N, seed=7):
    """Raw macro series for a given closing direction on each axis.

    Inputs are specified as the economics (growth in percent, inflation in
    percent) and converted back to the index levels the registry's 'yoy'
    transform expects, so the fixture exercises the real transform chain
    rather than bypassing it. Each series gets its own noise seed, so the
    components are correlated through the trend and independent otherwise --
    as macro series are.
    """
    g = _path(n, growth_base, growth_end, seed)
    i = _path(n, inflation_base, inflation_end, seed + 1)
    # Unemployment moves opposite to growth, as it does in life.
    u = _path(n, 5.0, 5.0 + (growth_base - growth_end), seed + 2)

    idx = pd.date_range("1986-01-31", periods=n, freq="ME")
    mk = lambda v: pd.Series(np.asarray(v, dtype="float64"), index=idx)
    return {
        "Industrial_Production": mk(level_from_yoy(g)),
        "Nonfarm_Payrolls": mk(level_from_yoy(g * 0.6)),
        "Retail_Sales": mk(level_from_yoy(g * 1.2)),
        "GDP_Growth": mk(g),
        "Unemployment": mk(u),
        "Consumer_Sentiment": mk(80.0 + g * 4.0),
        "Inflation_CPI": mk(level_from_yoy(i)),
        "Core_CPI": mk(level_from_yoy(i * 0.9)),
        "Breakeven_10Y": mk(i * 0.8),
    }


# --------------------------------------------------------------------------
# quadrant / confidence / label
# --------------------------------------------------------------------------

@pytest.mark.parametrize("gd,idl,expected", [
    (1.0, -1.0, R.GOLDILOCKS),
    (1.0, 1.0, R.REFLATION),
    (-1.0, 1.0, R.STAGFLATION),
    (-1.0, -1.0, R.DEFLATION),
])
def test_quadrant_covers_all_four_sign_combinations(gd, idl, expected):
    assert R.quadrant(gd, idl) == expected


def test_quadrant_of_missing_data_is_empty_not_a_guess():
    assert R.quadrant(np.nan, 1.0) == ""
    assert R.quadrant(1.0, np.nan) == ""


def test_confidence_grows_with_distance_from_the_origin():
    near = R.confidence(0.05, 0.05)
    far = R.confidence(1.0, 1.0)
    assert near < far
    assert R.confidence(10.0, 10.0) == 1.0, "confidence is capped at 1"


def test_near_origin_is_reported_as_transition_not_a_regime():
    """The main way a dashboard like this misleads."""
    label, conf = R.label(0.04, -0.02)
    assert label == R.TRANSITION
    assert conf < R.CONFIDENCE_FLOOR
    # The underlying quadrant is still computable, just not reported.
    assert R.quadrant(0.04, -0.02) == R.GOLDILOCKS


def test_a_clear_move_is_reported_as_its_quadrant():
    label, conf = R.label(-0.9, 0.9)
    assert label == R.STAGFLATION
    assert conf > R.CONFIDENCE_FLOOR


# --------------------------------------------------------------------------
# end-to-end scenarios
# --------------------------------------------------------------------------

SCENARIOS = [
    (6.0, 0.5, R.GOLDILOCKS),    # growth accelerating, inflation collapsing
    (6.0, 6.0, R.REFLATION),     # both accelerating
    (-2.0, 6.0, R.STAGFLATION),  # growth collapsing, inflation accelerating
    (-2.0, 0.5, R.DEFLATION),    # both collapsing
]
SEEDS = [7, 11, 23, 41, 97]


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("growth_end,inflation_end,expected", SCENARIOS)
def test_scenario_lands_in_the_right_quadrant(growth_end, inflation_end,
                                              expected, seed):
    """Every quadrant, over several independent noise draws.

    Asserted on the raw quadrant rather than the reported label, so this test
    measures the classifier and not the confidence threshold -- the two fail
    for different reasons and are worth being able to tell apart.
    """
    frame = R.build(scenario(growth_end, inflation_end, seed=seed), **Z_KW)
    assert not frame.empty
    last = frame.iloc[-1]
    got = R.quadrant(last["growth_delta"], last["inflation_delta"])
    assert got == expected, (
        f"seed={seed} growth_delta={last['growth_delta']:.3f} "
        f"inflation_delta={last['inflation_delta']:.3f}")


def test_most_real_trends_clear_the_confidence_floor():
    """The threshold must not swallow the signal it is there to filter.

    CONFIDENCE_FLOOR trades spurious calls against real ones; the sweep in
    core/regime.py puts the loss at ~3% of genuine regimes. This asserts the
    reported label survives for the large majority, so a future retune that
    silences most real calls fails here rather than in production.
    """
    reported = [
        R.build(scenario(ge, ie, seed=s), **Z_KW).iloc[-1]["quadrant"]
        for ge, ie, _ in SCENARIOS for s in SEEDS
    ]
    expected = [exp for _, _, exp in SCENARIOS for _ in SEEDS]
    hits = sum(r == e for r, e in zip(reported, expected))
    assert hits >= 0.85 * len(expected), f"{hits}/{len(expected)}: {reported}"


def test_scenario_delta_signs_match_the_driven_direction():
    frame = R.build(scenario(-2.0, 6.0), **Z_KW)
    last = frame.iloc[-1]
    assert last["growth_delta"] < 0
    assert last["inflation_delta"] > 0


@pytest.mark.parametrize("seed", SEEDS)
def test_a_flat_economy_reads_weaker_than_a_trending_one(seed):
    """Confidence has to discriminate, not merely exist.

    A becalmed economy with realistic noise is not guaranteed to land on
    Transition -- a random walk wanders, and at a 3-month horizon the model
    cannot tell a small genuine turn from a small random one. What it must do
    is report the becalmed case as materially less confident than a real
    trend. Over 40 seeds, flat confidence averages 0.17 against 0.46 for the
    four trending scenarios, which are classified correctly 160/160.
    """
    flat = R.build(scenario(2.0, 2.0, seed=seed), **Z_KW).iloc[-1]["confidence"]
    trend = R.build(scenario(-2.0, 6.0, seed=seed),
                    **Z_KW).iloc[-1]["confidence"]
    assert flat < trend, f"flat={flat:.3f} trend={trend:.3f}"


def test_a_flat_economy_is_usually_transition():
    """The aggregate claim behind the docstring above.

    A majority, not all of them: CALL_RADIUS is deliberately set low enough to
    give a call in about half of all real months, which necessarily lets some
    becalmed readings through. The comment block in core/regime.py has the
    trade-off in full.
    """
    calls = [R.build(scenario(2.0, 2.0, seed=s), **Z_KW).iloc[-1]["quadrant"]
             for s in SEEDS]
    assert calls.count(R.TRANSITION) > len(SEEDS) / 2, calls


def test_build_reports_component_counts():
    frame = R.build(scenario(6.0, 0.5), **Z_KW)
    last = frame.iloc[-1]
    assert last["growth_components"] == 6
    assert last["inflation_components"] == 3


def test_build_drops_a_series_it_was_not_given():
    raw = scenario(6.0, 0.5)
    del raw["Retail_Sales"]
    del raw["Breakeven_10Y"]
    frame = R.build(raw, **Z_KW)
    assert frame.iloc[-1]["growth_components"] == 5
    assert frame.iloc[-1]["inflation_components"] == 2


def test_build_with_no_data_returns_an_empty_frame_with_the_right_columns():
    frame = R.build({})
    assert frame.empty
    for col in ("growth_delta", "inflation_delta", "quadrant", "confidence"):
        assert col in frame.columns


def test_build_with_only_one_axis_returns_empty():
    raw = scenario(6.0, 0.5)
    for k in ("Inflation_CPI", "Core_CPI", "Breakeven_10Y"):
        del raw[k]
    assert R.build(raw, **Z_KW).empty, "a regime call needs both coordinates"


def test_build_output_index_is_monotonic_and_named():
    frame = R.build(scenario(6.0, 6.0), **Z_KW)
    assert frame.index.is_monotonic_increasing
    assert frame.index.name == "timestamp"


def test_reading_names_the_regime_and_the_confidence():
    frame = R.build(scenario(-2.0, 6.0), **Z_KW)
    text = R.reading(frame.iloc[-1])
    assert R.STAGFLATION in text
    assert "onfidence" in text


def test_reading_handles_a_row_with_no_call():
    assert "No regime call" in R.reading(pd.Series({"quadrant": ""}))


def test_trailing_windows_mean_history_does_not_get_rewritten():
    """Adding new months must not change an earlier regime call.

    If it does, something in the chain is using a full-sample statistic, and
    every historical validation of the model is worthless.
    """
    raw = scenario(-2.0, 6.0)
    truncated = {k: v.iloc[:-12] for k, v in raw.items()}
    full = R.build(raw, **Z_KW)
    part = R.build(truncated, **Z_KW)
    common = part.index.intersection(full.index)
    assert len(common) > 100
    pd.testing.assert_series_equal(
        full.loc[common, "growth_delta"], part.loc[common, "growth_delta"])
    assert (full.loc[common, "quadrant"] == part.loc[common, "quadrant"]).all()
