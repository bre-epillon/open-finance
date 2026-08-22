"""Recompute regime_history and sentiment_index from the source tables.

Called by the nightly worker and by scripts/backfill_history.py. Both tables
declare DEDUPLICATE UPSERT KEYS(timestamp), so a full recompute upserts rather
than appends and re-running it is free of consequences.

Full recompute rather than incremental: the whole regime history is ~780
monthly rows and sentiment ~10k daily rows, so recomputing everything costs
seconds. An incremental version would need to reason about how far back a
trailing 120-month window can be disturbed by a single FRED revision, which is
more logic than the saving is worth.
"""

import logging

from core import regime, sentiment
from core.config import PRICE_TABLE
from core.db import write
from core.db.rest import macro_frame, price_frame, tracked_tickers
from core.db.schema import ensure_tables
from core.sentiment import BONDS, SPX, VIX
from core.series import GROWTH, INFLATION, REGISTRY

logger = logging.getLogger(__name__)

# ^GSPC, ^VIX and TLT for the components; the rest of equity_prices supplies
# the breadth constituents.
SENTIMENT_TICKERS = [SPX, VIX, BONDS]
JUNK = "Junk_Bond_Spread"


def regime_rows() -> int:
    """Recompute the monthly regime history."""
    names = [s.name for s in REGISTRY.values()
             if s.axis in (GROWTH, INFLATION)]
    raw = macro_frame(names)
    if not raw:
        logger.warning("No macro data found -- has fred_worker run?")
        return 0
    logger.info("Building regime history from %d series: %s",
                len(raw), ", ".join(sorted(raw)))
    frame = regime.build(raw)
    if frame.empty:
        logger.warning("Regime frame is empty. The usual cause is too little "
                       "FRED history for a trailing z-score -- see "
                       "patches/README.md 0002.")
        return 0
    logger.info("Regime history spans %s to %s (%d months); latest call %s",
                frame.index[0].date(), frame.index[-1].date(), len(frame),
                frame.iloc[-1]["quadrant"])
    return write.write_regime(frame)


def sentiment_rows() -> int:
    """Recompute the daily sentiment index."""
    prices = price_frame(SENTIMENT_TICKERS)
    if prices.empty or SPX not in prices or VIX not in prices:
        logger.warning("Missing %s or %s in %s -- open-finance's worker "
                       "ingests these via FX_BONDS_TICKERS", SPX, VIX,
                       PRICE_TABLE)
        return 0

    junk = macro_frame([JUNK]).get(JUNK)
    constituents = [t for t in tracked_tickers() if t not in SENTIMENT_TICKERS]
    universe = price_frame(constituents) if constituents else None
    logger.info("Building sentiment from %d price bars, junk=%s, breadth "
                "constituents=%d", len(prices), junk is not None,
                len(constituents))

    frame = sentiment.build(prices, junk=junk, universe=universe)
    if frame.empty:
        logger.warning("Sentiment frame is empty -- fewer than %d components "
                       "available on every date.", sentiment.MIN_COMPONENTS)
        return 0
    logger.info("Sentiment spans %s to %s (%d days); latest %.1f (%s)",
                frame.index[0].date(), frame.index[-1].date(), len(frame),
                frame.iloc[-1]["composite"],
                sentiment.classify(frame.iloc[-1]["composite"]))
    return write.write_sentiment(frame)


def run_all() -> dict[str, int]:
    ensure_tables()
    return {"regime": regime_rows(), "sentiment": sentiment_rows()}
