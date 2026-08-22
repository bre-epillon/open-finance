"""Dalio 4-quadrant macro regime classification.

The quadrant is decided by the SIGN OF THE CHANGE in each axis, not the level.
That is Bridgewater's actual framing: an economy with 2% inflation that is
rising behaves like an inflationary regime, and one with 6% inflation that is
collapsing behaves like a disinflationary one. Levels ride along as context.

Pipeline, per axis:
    raw series -> monthly + transform + publication lag + sign  (core.align)
    -> normalised as a level, a 3-month change (Delta) and a
       change-in-change (Gamma), each divided by the trailing
       standard deviation of the level                          (core.align)
    -> weighted mean across the axis's components               (core.align)
    -> quadrant from sign(Delta_growth), sign(Delta_inflation)

Delta and Gamma are computed on the LEVEL and then scaled, never as the
difference of an already-normalised series -- core.align.normalise explains
why at length, and it is the single most important detail in this module.
"""

import numpy as np
import pandas as pd

from core import transforms as T
from core.align import DELTA, GAMMA, LEVEL, axis_composite
from core.series import GROWTH, INFLATION

GOLDILOCKS = "Goldilocks"
REFLATION = "Reflation"
STAGFLATION = "Stagflation"
DEFLATION = "Deflation"
TRANSITION = "Transition"

# Units: standard deviations of each axis' own level, per quarter (see
# core.align.normalise). Two knobs, both in those units, because collapsing
# them into a single dimensionless threshold made the decision that actually
# matters -- "how big a move counts as a regime" -- impossible to reason about:
#
#   CALL_RADIUS             below this distance from the origin no quadrant is
#                           named, and the call is reported as Transition
#   FULL_CONFIDENCE_RADIUS  the distance at which confidence saturates at 1.0
#
# CONFIDENCE_FLOOR is derived from the two and exposed by the API, so a
# consumer can see the boundary rather than having to infer it.
#
# CALL_RADIUS = 0.30 is a compromise between two sweeps that pull opposite
# ways. On the synthetic scenarios in tests/test_regime.py -- 40 noise seeds x
# 4 trending quadrants against 40 becalmed economies -- raising it suppresses
# more spurious calls at almost no cost:
#
#     CALL_RADIUS   becalmed -> Transition   real regimes kept
#         0.30              78%                    100%
#         0.375             88%                    100%
#         0.45              95%                     97%
#
# But on history-shaped input (tests/test_history_scenarios.py) the same
# thresholds leave most of the record undecided, because real macro momentum
# is small most of the time:
#
#     CALL_RADIUS   months given a quadrant
#         0.30              50%
#         0.375             43%
#         0.45              30%
#
# 0.30 keeps roughly four in five becalmed readings quiet while still naming a
# regime in half of all months. Re-tune with scripts/validate_history.py
# --grid against real FRED history before relying on either figure: that is
# the only sweep that sees real macro noise.
FULL_CONFIDENCE_RADIUS = 1.2
CALL_RADIUS = 0.30
CONFIDENCE_FLOOR = CALL_RADIUS / FULL_CONFIDENCE_RADIUS

DESCRIPTION = {
    GOLDILOCKS: "growth rising, inflation falling -- disinflationary expansion",
    REFLATION: "growth rising, inflation rising -- inflationary expansion",
    STAGFLATION: "growth falling, inflation rising -- inflationary contraction",
    DEFLATION: "growth falling, inflation falling -- disinflationary contraction",
    TRANSITION: "both axes near flat -- no regime call at this confidence",
}


def quadrant(growth_delta: float, inflation_delta: float) -> str:
    """Quadrant from the two Delta signs, ignoring confidence.

    A zero Delta is treated as falling. Exactly zero does not occur in
    practice on float data, and picking a side keeps the function total.
    """
    if pd.isna(growth_delta) or pd.isna(inflation_delta):
        return ""
    if growth_delta > 0:
        return REFLATION if inflation_delta > 0 else GOLDILOCKS
    return STAGFLATION if inflation_delta > 0 else DEFLATION


def confidence(growth_delta: float, inflation_delta: float) -> float:
    """0-1 confidence: how far the point sits from the origin.

    A point at (+0.04, -0.02) is technically Goldilocks and actually
    undetermined. Reporting that as a regime call is the main way a dashboard
    like this misleads, so the distance is surfaced rather than hidden.
    """
    if pd.isna(growth_delta) or pd.isna(inflation_delta):
        return float("nan")
    r = float(np.hypot(growth_delta, inflation_delta))
    return min(1.0, r / FULL_CONFIDENCE_RADIUS)


def label(growth_delta: float, inflation_delta: float,
          conf: float | None = None) -> tuple[str, float]:
    """(regime, confidence), collapsing low-confidence calls to Transition."""
    c = confidence(growth_delta, inflation_delta) if conf is None else conf
    q = quadrant(growth_delta, inflation_delta)
    if not q or pd.isna(c):
        return "", float("nan")
    return (TRANSITION if c < CONFIDENCE_FLOOR else q), c


def build(raw: dict[str, pd.Series], diff_periods: int = T.DIFF_PERIODS,
          **axis_kw) -> pd.DataFrame:
    """Full monthly regime history from raw macro series.

    `raw` maps registry names to raw observation Series, exactly as
    core.db.rest.macro_frame returns them. Returns one row per month with the
    axis levels, their Delta and Gamma, the quadrant and the confidence.
    """
    kw = dict(diff_periods=diff_periods, **axis_kw)
    series, parts = {}, {}
    for axis in (GROWTH, INFLATION):
        for op in (LEVEL, DELTA, GAMMA):
            series[axis, op], parts[axis, op] = axis_composite(
                raw, axis, op, **kw)

    if series[GROWTH, DELTA].empty or series[INFLATION, DELTA].empty:
        return _empty_frame()

    # Union index, then reindex: a regime call needs both coordinates, and an
    # inner join here would silently shorten the history whenever one axis
    # starts later than the other. Rows missing either Delta are dropped at
    # the end by the empty-quadrant filter.
    idx = series[GROWTH, DELTA].index.union(series[INFLATION, DELTA].index)

    out = pd.DataFrame(index=idx)
    out.index.name = "timestamp"
    out["growth_z"] = series[GROWTH, LEVEL].reindex(idx)
    out["inflation_z"] = series[INFLATION, LEVEL].reindex(idx)
    out["growth_delta"] = series[GROWTH, DELTA].reindex(idx)
    out["inflation_delta"] = series[INFLATION, DELTA].reindex(idx)
    out["growth_gamma"] = series[GROWTH, GAMMA].reindex(idx)
    out["inflation_gamma"] = series[INFLATION, GAMMA].reindex(idx)
    # Counted off the Delta frame, because the Delta is what the quadrant
    # rests on -- reporting the level's component count next to a Delta-based
    # call would overstate what the call is built from.
    out["growth_components"] = T.component_count(
        parts[GROWTH, DELTA].reindex(idx))
    out["inflation_components"] = T.component_count(
        parts[INFLATION, DELTA].reindex(idx))

    labels = [
        label(gd, idl)
        for gd, idl in zip(out["growth_delta"], out["inflation_delta"])
    ]
    out["quadrant"] = [q for q, _ in labels]
    out["confidence"] = [c for _, c in labels]

    return out[out["quadrant"] != ""].copy()


def reading(row: pd.Series) -> str:
    """Deterministic prose for one regime row.

    Exists so that an LLM consuming get_regime does not have to invent an
    interpretation of a z-score. Same thresholds the UI uses.
    """
    q = row.get("quadrant", "")
    if not q:
        return "No regime call available."
    c = float(row.get("confidence", float("nan")))
    strength = "low" if c < 0.4 else "moderate" if c < 0.7 else "high"
    accel = np.hypot(row.get("growth_gamma", 0.0) or 0.0,
                     row.get("inflation_gamma", 0.0) or 0.0)
    trend = "accelerating" if accel > 0.5 else "steady"
    return (f"{q}: {DESCRIPTION[q]}. Confidence {strength} ({c:.2f}), "
            f"move {trend}.")


def _empty_frame() -> pd.DataFrame:
    cols = ["growth_z", "inflation_z", "growth_delta", "inflation_delta",
            "growth_gamma", "inflation_gamma", "growth_components",
            "inflation_components", "quadrant", "confidence"]
    f = pd.DataFrame({c: pd.Series(dtype="float64") for c in cols})
    f.index = pd.DatetimeIndex([], name="timestamp")
    return f
