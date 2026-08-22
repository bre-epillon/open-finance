"""Transforms against hand-computed values.

Every expected number below was worked out by hand, not by running the code
and pasting the result -- otherwise the test only asserts that the code does
what it does.
"""

import numpy as np
import pandas as pd
import pytest

from conftest import monthly
from core import transforms as T


def test_yoy_is_percent_change_over_twelve_months():
    # 13 months, level doubling from 100 to 200 in the last step.
    v = [100.0] * 12 + [200.0]
    out = T.yoy(monthly(v))
    assert np.isnan(out.iloc[:12]).all(), "no YoY before 12 months of history"
    assert out.iloc[12] == pytest.approx(100.0)


def test_yoy_handles_zero_denominator_without_inf():
    v = [0.0] * 12 + [5.0]
    out = T.yoy(monthly(v))
    assert np.isnan(out.iloc[12]), "division by zero must be NaN, not inf"
    assert not np.isinf(out.to_numpy()).any()


def test_delta_is_a_plain_difference_over_the_horizon():
    out = T.delta(monthly([1.0, 2.0, 4.0, 7.0, 11.0]), periods=3)
    # 7 - 1 = 6, 11 - 2 = 9
    assert out.dropna().tolist() == [6.0, 9.0]


def test_gamma_is_the_second_difference_not_the_fourth():
    # A quadratic in t has a constant second difference. With periods=1 the
    # second difference of t^2 is exactly 2.
    s = monthly([float(t * t) for t in range(10)])
    g = T.gamma(s, periods=1).dropna()
    assert g.tolist() == pytest.approx([2.0] * len(g))


def test_gamma_of_a_straight_line_is_zero():
    assert T.gamma(monthly(list(range(20))), periods=3).dropna().abs().max() == 0.0


def test_zscore_is_trailing_only():
    """A late spike must not move an earlier z-score."""
    base = [1.0] * 40
    quiet = T.zscore(monthly(base + [1.0] * 10), window=20, min_periods=10)
    spiked = T.zscore(monthly(base + [99.0] * 10), window=20, min_periods=10)
    pd.testing.assert_series_equal(quiet.iloc[:40], spiked.iloc[:40])


def test_zscore_of_a_flat_series_is_nan_not_inf():
    out = T.zscore(monthly([5.0] * 40), window=20, min_periods=10)
    assert out.dropna().empty
    assert not np.isinf(out.to_numpy()).any()


def test_zscore_matches_hand_computation():
    # Window of 4 over 1,2,3,4: mean 2.5, sample sd (ddof=1) = 1.29099...
    s = monthly([1.0, 2.0, 3.0, 4.0])
    out = T.zscore(s, window=4, min_periods=4)
    expected = (4.0 - 2.5) / np.std([1, 2, 3, 4], ddof=1)
    assert out.iloc[-1] == pytest.approx(expected)


def test_pct_rank_bounds_and_direction():
    s = monthly(list(range(1, 21)))
    out = T.pct_rank(s, window=10, min_periods=5)
    # A monotonically rising series is always at the top of its own window.
    assert out.dropna().eq(100.0).all()
    # A monotonically falling one is always at the bottom. Only the full
    # windows are checked: during the min_periods ramp-up the window holds
    # fewer observations, so the bottom rank is 1/5 = 20% rather than 1/10.
    falling = T.pct_rank(monthly(list(range(20, 0, -1))), window=10, min_periods=5)
    assert falling.iloc[9:].eq(10.0).all()
    assert falling.dropna().le(20.0 + 1e-9).all()


def test_pct_rank_matches_manual_percentile():
    s = monthly([5.0, 1.0, 4.0, 2.0, 3.0])
    out = T.pct_rank(s, window=5, min_periods=5)
    # Final window is [5,1,4,2,3]; the current value 3 is the 3rd smallest of
    # 5, so rank 3/5 = 60%.
    assert out.iloc[-1] == pytest.approx(60.0)


def test_pct_rank_is_not_min_max_scaling():
    """The regression the parked fear_and_greed code had.

    One huge outlier must not compress every later reading. Under min/max
    scaling the tail values would all sit near 0; under a percentile rank they
    keep spreading across the range.
    """
    s = monthly([10.0] + [1.0, 2.0, 3.0, 4.0, 5.0] * 4)
    out = T.pct_rank(s, window=21, min_periods=5).dropna()
    assert out.max() - out.min() > 30.0


def test_weighted_mean_drops_missing_components():
    f = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, np.nan]},
                     index=monthly([0, 0]).index)
    out = T.weighted_mean(f, {"a": 1.0, "b": 3.0})
    assert out.iloc[0] == pytest.approx((1.0 * 1 + 3.0 * 3) / 4)
    # Second row: only 'a' present, so the answer is 'a' -- not a blend with a
    # substituted neutral value.
    assert out.iloc[1] == pytest.approx(2.0)


def test_weighted_mean_respects_min_components():
    f = pd.DataFrame({"a": [1.0, 2.0], "b": [3.0, np.nan]},
                     index=monthly([0, 0]).index)
    out = T.weighted_mean(f, min_components=2)
    assert not np.isnan(out.iloc[0])
    assert np.isnan(out.iloc[1])


def test_component_count():
    f = pd.DataFrame({"a": [1.0, np.nan], "b": [3.0, np.nan]},
                     index=monthly([0, 0]).index)
    assert T.component_count(f).tolist() == [2, 0]


def test_transforms_reject_unsorted_input():
    s = monthly([1.0, 2.0, 3.0]).iloc[::-1]
    with pytest.raises(ValueError):
        T.delta(s)
