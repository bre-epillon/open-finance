"""All Weather tilts: structural invariants, then behaviour."""

import pytest

from core import regime as R
from core.tilts import BASELINE, DELTAS, DISCLAIMER, payload, tilt

REGIMES = [R.GOLDILOCKS, R.REFLATION, R.STAGFLATION, R.DEFLATION,
           R.TRANSITION]


def test_baseline_sums_to_one_hundred():
    assert sum(BASELINE.values()) == pytest.approx(100.0)


@pytest.mark.parametrize("regime", REGIMES)
def test_every_delta_column_sums_to_zero(regime):
    """Otherwise the renormalisation silently rescales every other sleeve.

    A column summing to +8 means tilt() divides everything by 1.08, which
    shows up as a tilt in sleeves the regime had no view on at all.
    """
    assert sum(DELTAS[regime].values()) == pytest.approx(0.0)


@pytest.mark.parametrize("regime", REGIMES)
def test_every_delta_column_covers_every_sleeve(regime):
    assert set(DELTAS[regime]) == set(BASELINE)


@pytest.mark.parametrize("regime", REGIMES)
def test_no_sleeve_clips_to_zero_at_full_confidence(regime):
    """Clipping is what makes renormalisation bite.

    If a sleeve went negative and got floored, the remaining sleeves absorb
    the shortfall, so a delta the model never expressed appears in the output.
    """
    for sleeve, base in BASELINE.items():
        assert base + DELTAS[regime][sleeve] > 0.0, sleeve


@pytest.mark.parametrize("regime", REGIMES)
def test_tilt_always_sums_to_one_hundred(regime):
    for conf in (0.0, 0.25, 0.5, 1.0):
        assert sum(tilt(regime, conf).values()) == pytest.approx(100.0, abs=0.05)


def test_zero_confidence_leaves_the_baseline_untouched():
    assert tilt(R.STAGFLATION, 0.0) == pytest.approx(BASELINE)


def test_transition_never_moves_the_portfolio():
    assert tilt(R.TRANSITION, 1.0) == pytest.approx(BASELINE)


def test_tilts_scale_monotonically_with_confidence():
    low = tilt(R.STAGFLATION, 0.25)["Gold"]
    mid = tilt(R.STAGFLATION, 0.5)["Gold"]
    high = tilt(R.STAGFLATION, 1.0)["Gold"]
    assert BASELINE["Gold"] < low < mid < high


def test_stagflation_favours_real_assets_over_equities_and_duration():
    t = tilt(R.STAGFLATION, 1.0)
    assert t["Gold"] > BASELINE["Gold"]
    assert t["Commodities"] > BASELINE["Commodities"]
    assert t["Equities"] < BASELINE["Equities"]
    assert t["Long Treasuries"] < BASELINE["Long Treasuries"]


def test_deflation_favours_duration_over_real_assets():
    t = tilt(R.DEFLATION, 1.0)
    assert t["Long Treasuries"] > BASELINE["Long Treasuries"]
    assert t["Commodities"] < BASELINE["Commodities"]


def test_goldilocks_favours_equities():
    assert tilt(R.GOLDILOCKS, 1.0)["Equities"] > BASELINE["Equities"]


def test_an_unknown_regime_does_not_move_the_portfolio():
    """A classifier that failed must not reallocate anything."""
    assert tilt("", 1.0) == pytest.approx(BASELINE)
    assert tilt("Wibble", 1.0) == pytest.approx(BASELINE)


def test_nan_confidence_is_treated_as_no_confidence():
    assert tilt(R.STAGFLATION, float("nan")) == pytest.approx(BASELINE)


def test_confidence_outside_zero_to_one_is_clamped():
    assert tilt(R.STAGFLATION, 5.0) == pytest.approx(tilt(R.STAGFLATION, 1.0))
    assert tilt(R.STAGFLATION, -5.0) == pytest.approx(BASELINE)


def test_payload_always_carries_the_disclaimer():
    """The numbers look actionable. That is exactly the risk."""
    p = payload(R.STAGFLATION, 0.8)
    assert p["disclaimer"] == DISCLAIMER
    assert "not investment advice" in DISCLAIMER.lower()


def test_payload_delta_matches_tilted_minus_baseline():
    p = payload(R.REFLATION, 1.0)
    for sleeve in BASELINE:
        assert p["delta_vs_baseline"][sleeve] == pytest.approx(
            p["tilted"][sleeve] - BASELINE[sleeve], abs=0.02)


def test_payload_handles_nan_confidence_without_emitting_nan_json():
    """json.dumps emits bare NaN, which is not valid JSON."""
    assert payload(R.STAGFLATION, float("nan"))["confidence"] is None
