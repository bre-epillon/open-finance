"""ILP writes for the two tables this project owns.

One Sender per call, flushed once. open-finance's BACKLOG.md flags "many small
ILP commits into a DEDUPLICATE UPSERT table" as the pattern behind two QuestDB
crashes, so a recompute writes its whole frame in a single flush rather than
row-batch by row-batch.
"""

import logging

import pandas as pd
from questdb.ingress import Sender

from core.config import ILP_CONF, REGIME_TABLE, SENTIMENT_TABLE

logger = logging.getLogger(__name__)

REGIME_DOUBLES = ("growth_z", "inflation_z", "growth_delta", "inflation_delta",
                  "growth_gamma", "inflation_gamma", "confidence")
REGIME_INTS = ("growth_components", "inflation_components")
SENTIMENT_DOUBLES = ("momentum", "volatility", "safe_haven", "junk_bond",
                     "breadth", "composite")


def _cols(row: pd.Series, doubles, ints=()) -> dict:
    """Row -> ILP column dict, skipping NaN.

    Skipping rather than zero-filling: a NaN component means "not measurable
    on this date", and writing 0.0 would make that indistinguishable from a
    genuine zero reading downstream.
    """
    out = {}
    for c in doubles:
        v = row.get(c)
        if v is not None and pd.notna(v):
            out[c] = float(v)
    for c in ints:
        v = row.get(c)
        if v is not None and pd.notna(v):
            out[c] = int(v)
    return out


def write_regime(frame: pd.DataFrame) -> int:
    """Write regime rows. Returns the number written."""
    if frame.empty:
        return 0
    n = 0
    with Sender.from_conf(ILP_CONF) as sender:
        for ts, row in frame.iterrows():
            cols = _cols(row, REGIME_DOUBLES, REGIME_INTS)
            if not cols:
                continue
            sender.row(REGIME_TABLE,
                       symbols={"quadrant": str(row["quadrant"])},
                       columns=cols, at=ts.to_pydatetime())
            n += 1
        sender.flush()
    logger.info("Wrote %d rows to %s", n, REGIME_TABLE)
    return n


def write_sentiment(frame: pd.DataFrame) -> int:
    """Write sentiment rows. Returns the number written."""
    if frame.empty:
        return 0
    n = 0
    with Sender.from_conf(ILP_CONF) as sender:
        for ts, row in frame.iterrows():
            cols = _cols(row, SENTIMENT_DOUBLES, ("components",))
            if "composite" not in cols:
                continue
            sender.row(SENTIMENT_TABLE, columns=cols, at=ts.to_pydatetime())
            n += 1
        sender.flush()
    logger.info("Wrote %d rows to %s", n, SENTIMENT_TABLE)
    return n
