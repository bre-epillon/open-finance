"""All Weather baseline weights and regime tilts.

RESEARCH OUTPUT, NOT INVESTMENT ADVICE. The numbers look actionable, which is
exactly the risk, so DISCLAIMER travels with every response that carries them
and the UI renders it on the panel rather than in a footnote.

Tilts scale with confidence, so a Transition call barely moves the portfolio.
That is the point of computing confidence at all: an ambiguous macro read
should produce an almost-unchanged allocation, not a coin-flip rotation.
"""

from core.regime import (DEFLATION, GOLDILOCKS, REFLATION, STAGFLATION,
                         TRANSITION)

DISCLAIMER = (
    "Illustrative research output from a mechanical model. Not investment "
    "advice, not a recommendation, and not suitable as a sole input to any "
    "allocation decision."
)

# The published All Weather shape. Percent, sums to 100.
BASELINE: dict[str, float] = {
    "Equities": 30.0,
    "Long Treasuries": 40.0,
    "Intermediate Treasuries": 15.0,
    "Gold": 7.5,
    "Commodities": 7.5,
}

# Percentage-point deltas applied at full confidence. Every column sums to
# exactly zero, and no sleeve is pushed below zero at full confidence, so the
# renormalisation in tilt() is a no-op in practice. Both properties are
# asserted in tests/test_tilts.py -- a column that does not sum to zero makes
# the renormalisation silently rescale every OTHER sleeve, which shows up as a
# tilt in a sleeve the regime had no view on.
DELTAS: dict[str, dict[str, float]] = {
    GOLDILOCKS: {"Equities": +10.0, "Long Treasuries": -5.0,
                 "Intermediate Treasuries": -2.0, "Gold": -2.0,
                 "Commodities": -1.0},
    REFLATION: {"Equities": +2.0, "Long Treasuries": -12.0,
                "Intermediate Treasuries": -3.0, "Gold": +6.0,
                "Commodities": +7.0},
    STAGFLATION: {"Equities": -10.0, "Long Treasuries": -10.0,
                  "Intermediate Treasuries": 0.0, "Gold": +10.0,
                  "Commodities": +10.0},
    DEFLATION: {"Equities": -10.0, "Long Treasuries": +14.0,
                "Intermediate Treasuries": +4.0, "Gold": -3.0,
                "Commodities": -5.0},
    # No view. Explicit rather than absent, so a caller never has to guess
    # whether a missing key means neutral or means broken.
    TRANSITION: {k: 0.0 for k in BASELINE},
}

# Rough proxies, for the dashboard to chart the sleeves against real prices.
# Tracked via open-finance's POST /api/track.
PROXY_TICKERS = {
    "Equities": "SPY",
    "Long Treasuries": "TLT",
    "Intermediate Treasuries": "IEF",
    "Gold": "GLD",
    "Commodities": "DBC",
}


def tilt(regime: str, conf: float = 1.0) -> dict[str, float]:
    """Baseline plus confidence-scaled deltas, floored at zero, renormalised.

    Unknown regime returns the baseline untouched -- a classifier that failed
    should not move the portfolio.
    """
    deltas = DELTAS.get(regime)
    if deltas is None:
        return dict(BASELINE)

    c = 0.0 if conf is None or conf != conf else max(0.0, min(1.0, float(conf)))
    raw = {k: max(0.0, v + deltas.get(k, 0.0) * c) for k, v in BASELINE.items()}
    total = sum(raw.values())
    if total <= 0:
        return dict(BASELINE)
    return {k: round(v * 100.0 / total, 2) for k, v in raw.items()}


def payload(regime: str, conf: float = 1.0) -> dict:
    """API/MCP-shaped tilt response, disclaimer included."""
    tilted = tilt(regime, conf)
    return {
        "regime": regime,
        "confidence": None if conf != conf else round(float(conf), 4),
        "baseline": dict(BASELINE),
        "tilted": tilted,
        "delta_vs_baseline": {
            k: round(tilted[k] - BASELINE[k], 2) for k in BASELINE
        },
        "proxy_tickers": dict(PROXY_TICKERS),
        "disclaimer": DISCLAIMER,
    }
