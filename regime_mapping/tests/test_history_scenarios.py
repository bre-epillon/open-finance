"""The whole chain over synthetic history shaped like the real record.

What this DOES verify: that the pipeline -- registry, monthly resample,
publication lag, per-component normalisation, weighted composite, Delta,
quadrant, and the scoring harness in scripts/validate_history.py -- turns a
macro path with a known shape into the regime labels that shape implies, over
65 years and across real calendar dates.

What it does NOT verify: calibration against the actual economy. The inputs
here are drawn from remembered anchor points, and a test built from the same
anchors it asserts against cannot tell you the model is right about the world.
That check needs live FRED data and is `scripts/validate_history.py`. This one
tells you the machinery is sound, which is the precondition for that check
meaning anything.
"""

import pandas as pd
import pytest

from core import regime as R

from scripts.demo_data import MONTHLY, macro


@pytest.fixture(scope="module")
def raw():
    """The shared synthetic history from scripts/demo_data.py.

    Imported rather than redefined here: scripts/demo_server.py needs the same
    series to drive the dashboard, and two copies of a 30-anchor fixture would
    drift the moment either is touched.
    """
    return macro()


@pytest.fixture(scope="module")
def frame(raw):
    return R.build(raw)


# Windows chosen where the MOMENTUM of both axes is unambiguous, which is not
# the same as the whole of a popularly-named episode. Two cases are worth
# spelling out, because they are where a momentum framework and everyday usage
# genuinely disagree:
#
#   * H2 2022. CPI peaked in June and fell after, so by momentum the second
#     half of 2022 was disinflationary contraction, not stagflation.
#   * "Goldilocks 2013-2015" is a statement about LEVELS -- decent growth,
#     inflation below target -- not about momentum. Measured on this fixture
#     that whole stretch has a median momentum radius of 0.19, below
#     CALL_RADIUS, so the model correctly declines to call it. The window used
#     here is the 2014-15 oil crash instead, where inflation was genuinely
#     falling fast while growth firmed. This is a real property of the
#     framework rather than a defect, and worth knowing before reading the
#     dashboard: quiet years get no call.
#
# Dates also allow for the publication lag -- the model's call for a month
# reflects what was knowable then, so it turns a month or two after the
# reference data does.
WINDOWS = [
    ("1978-09", "1980-09", R.STAGFLATION, "second oil shock into recession"),
    ("2008-11", "2009-09", R.DEFLATION, "GFC: growth and prices collapsing"),
    ("2014-09", "2015-09", R.GOLDILOCKS, "oil crash: inflation falling, growth firm"),
    ("2020-05", "2020-09", R.DEFLATION, "COVID shutdown"),
    ("2020-12", "2021-10", R.REFLATION, "reopening boom, inflation building"),
    ("2022-02", "2022-08", R.STAGFLATION, "inflation peak, growth slowing"),
]


def test_frame_covers_the_whole_period(frame):
    assert not frame.empty
    # 120-month z-window plus 60 min_periods plus the Delta horizon eats the
    # first few years; everything after should be there.
    assert frame.index[0].year <= 1970
    assert frame.index[-1].year >= 2026
    assert frame.index.is_monotonic_increasing


@pytest.mark.parametrize("start,end,expected,why", WINDOWS)
def test_window_is_mostly_the_expected_regime(frame, start, end, expected, why):
    window = frame.loc[start:end]
    assert len(window) >= 5, f"not enough months in {start}..{end}"
    quadrants = [R.quadrant(row["growth_delta"], row["inflation_delta"])
                 for _, row in window.iterrows()]
    hits = quadrants.count(expected)
    assert hits / len(quadrants) >= 0.7, (
        f"{why}: {hits}/{len(quadrants)} months matched {expected}; "
        f"got {pd.Series(quadrants).value_counts().to_dict()}")


def test_the_scoring_harness_agrees(frame, monkeypatch):
    """scripts/validate_history.py's scorer, on the same frame.

    Runs the real function rather than a copy, so a bug in the harness -- the
    thing that will be used to tune the model against live FRED data -- fails
    here rather than silently reporting a good number.
    """
    import scripts.validate_history as vh
    monkeypatch.setattr(vh, "EXPECTED", WINDOWS)
    table, overall = vh.score(frame)
    assert len(table) == len(WINDOWS)
    assert table["months"].min() > 0, "a window found no data"
    assert overall >= 0.7, f"{overall:.1%}\n{table.to_string(index=False)}"


def test_transition_share_is_not_the_whole_history(frame):
    """A model that says "Transition" everywhere would score well on the
    windows above by never being wrong. Guard against that."""
    share = (frame["quadrant"] == R.TRANSITION).mean()
    assert share < 0.5, f"{share:.1%} of all months are undecided"


def test_the_2022_inflation_peak_flips_the_inflation_delta(frame):
    """A specific, falsifiable claim: CPI momentum turns negative after the
    mid-2022 peak. If the sign does not flip, the Delta is measuring the wrong
    thing -- which is exactly what delta-of-z did."""
    before = frame.loc["2022-02":"2022-07", "inflation_delta"].mean()
    after = frame.loc["2023-01":"2023-09", "inflation_delta"].mean()
    assert before > 0 > after, f"before={before:.3f} after={after:.3f}"


def test_the_covid_trough_is_the_deepest_growth_reading(frame):
    """1960-2026, and the sharpest growth contraction should be spring 2020."""
    trough = frame["growth_delta"].idxmin()
    assert 2020 <= trough.year <= 2021, trough
