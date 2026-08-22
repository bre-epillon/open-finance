"""Greed & Fear composite, 0-100, on trading days.

Ported from open-finance's parked _to_delete/fear_and_greed/ with three
defects fixed. Each one biased the old score in a knowable direction:

1. VIX was counted twice. The old code derived `volatility` from ^VIX and then
   `put_call` from ^VIX again (labelled a "Put/Call Ratio Proxy"; it was the
   same series with a different lookback). With five equal-weighted components
   VIX held two of the five votes. Replaced with real market breadth, computed
   from the tracked equity universe -- genuinely independent, and the
   component CNN's index actually calls "stock price breadth".
2. Rolling min/max is not a percentile. See core.transforms.pct_rank.
3. resample('D') counted weekends, turning a 250-trading-day window into ~8
   months and forward-filling Saturday and Sunday in as duplicate values,
   damping every rolling statistic. There is no calendar resampling anywhere
   below: the index stays the trading-day index it arrives as.

A fourth, smaller fix: a missing component is dropped, not defaulted to 50.
"""

import pandas as pd

from core import transforms as T

SPX = "^GSPC"
VIX = "^VIX"
BONDS = "TLT"
REQUIRED = (SPX, VIX)

MOMENTUM_MA = 125
VOL_MA = 50
SAFE_HAVEN_LOOKBACK = 20
BREADTH_MA = 125
BREADTH_MIN_CONSTITUENTS = 15

COMPONENTS = ("momentum", "volatility", "safe_haven", "junk_bond", "breadth")
MIN_COMPONENTS = 3

# Symmetric around 50, unlike the parked code's 50-54 neutral band.
BANDS = ((25.0, "Extreme Fear"), (45.0, "Fear"), (55.0, "Neutral"),
         (75.0, "Greed"))
TOP_LABEL = "Extreme Greed"


def classify(score: float) -> str:
    if score is None or score != score:
        return "Unknown"
    for upper, name in BANDS:
        if score < upper:
            return name
    return TOP_LABEL


def _align(s: pd.Series, index: pd.DatetimeIndex) -> pd.Series:
    """Carry a series onto the trading-day index, last known value only.

    This is the pandas equivalent of QuestDB's ASOF JOIN: the junk-bond spread
    is a daily FRED series on its own calendar, so a plain reindex would punch
    holes in it on any date FRED skipped.
    """
    return s.reindex(s.index.union(index)).ffill().reindex(index)


def momentum(prices: pd.DataFrame) -> pd.Series:
    px = prices[SPX]
    ma = px.rolling(MOMENTUM_MA, min_periods=MOMENTUM_MA // 2).mean()
    return (px - ma) / ma


def volatility(prices: pd.DataFrame) -> pd.Series:
    """VIX relative to its own 50-day average.

    Kept at parity with CNN's "market volatility" component and with the
    parked code. Note what it therefore measures: volatility MOMENTUM, not
    level. A market sitting at VIX 35 for six months reads as neutral here,
    because 35 is where it has been -- it is the move to 35 that reads as
    fear. That is the intended behaviour, and it is the reason this component
    alone is a poor fear gauge and only means much inside the composite.
    """
    vix = prices[VIX]
    return vix - vix.rolling(VOL_MA, min_periods=VOL_MA // 2).mean()


def safe_haven(prices: pd.DataFrame) -> pd.Series:
    """Equity return minus long-bond return over 20 sessions.

    Positive means equities are being preferred to the safe haven -- greed.
    """
    n = SAFE_HAVEN_LOOKBACK
    return prices[SPX].pct_change(n) - prices[BONDS].pct_change(n)


def breadth(universe: pd.DataFrame) -> pd.Series:
    """Share of constituents trading above their own 125-day moving average.

    Requires BREADTH_MIN_CONSTITUENTS names with enough history on a given
    day, else NaN for that day -- a "breadth" reading off three tickers is
    noise wearing the name of a signal.
    """
    ma = universe.rolling(BREADTH_MA, min_periods=BREADTH_MA // 2).mean()
    above = (universe > ma)
    counted = ma.notna() & universe.notna()
    n = counted.sum(axis=1)
    pct = (above & counted).sum(axis=1) / n.where(n > 0) * 100.0
    return pct.where(n >= BREADTH_MIN_CONSTITUENTS)


def build(prices: pd.DataFrame, junk: pd.Series | None = None,
          universe: pd.DataFrame | None = None,
          window: int = T.RANK_WINDOW,
          min_periods: int = T.RANK_MIN_PERIODS) -> pd.DataFrame:
    """Daily component sub-scores and composite.

    prices    wide close-price frame, trading-day index; needs ^GSPC and ^VIX,
              and TLT for the safe-haven component
    junk      BAMLH0A0HYM2 option-adjusted spread, any daily calendar
    universe  wide close-price frame of the breadth constituents
    """
    missing = [t for t in REQUIRED if t not in prices.columns]
    if missing:
        raise ValueError(f"prices is missing required columns: {missing}")

    prices = prices.sort_index()
    idx = prices.index
    rank = lambda s: T.pct_rank(s, window=window, min_periods=min_periods)

    parts: dict[str, pd.Series] = {
        "momentum": rank(momentum(prices)),
        # Inverted: high volatility relative to its own trend is fear.
        "volatility": 100.0 - rank(volatility(prices)),
    }
    if BONDS in prices.columns:
        parts["safe_haven"] = rank(safe_haven(prices))
    if junk is not None and not junk.dropna().empty:
        # Inverted: a wide high-yield spread is fear.
        parts["junk_bond"] = 100.0 - rank(_align(junk, idx))
    if universe is not None and not universe.empty:
        b = breadth(universe.sort_index())
        parts["breadth"] = rank(_align(b, idx))

    frame = pd.DataFrame(parts, index=idx)
    frame["composite"] = T.weighted_mean(
        frame[[c for c in COMPONENTS if c in frame.columns]],
        min_components=MIN_COMPONENTS,
    )
    frame["components"] = T.component_count(
        frame[[c for c in COMPONENTS if c in frame.columns]])
    frame.index.name = "timestamp"
    return frame[frame["composite"].notna()].copy()


def reading(row: pd.Series) -> str:
    """Deterministic prose for one sentiment row, for the MCP tool."""
    score = float(row["composite"])
    drivers = {c: float(row[c]) for c in COMPONENTS
               if c in row.index and row[c] == row[c]}
    if not drivers:
        return f"{classify(score)} ({score:.0f}/100)."
    low = min(drivers, key=drivers.get)
    high = max(drivers, key=drivers.get)
    return (f"{classify(score)} ({score:.0f}/100) on {len(drivers)} of "
            f"{len(COMPONENTS)} components. Most fearful: {low} "
            f"({drivers[low]:.0f}). Most greedy: {high} ({drivers[high]:.0f}).")
