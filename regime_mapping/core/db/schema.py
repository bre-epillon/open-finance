"""DDL for the two tables regime_mapping owns.

Explicit CREATE TABLE, unlike macro_indicators -- which was left to be
auto-created by an ILP Sender and therefore came into existence with no
deduplication keys, which is why it now holds every observation many times
over. Both tables here declare their keys up front, so a recompute upserts
rather than appends and re-running a backfill is safe.

`sentiment_index`, not `sentiment_history`: the parked
_to_delete/fear_and_greed/compute_sentiment.py opens with
`DROP TABLE IF EXISTS sentiment_history`, so a different name means running
that old script can never destroy this one.
"""

from core.config import REGIME_TABLE, SENTIMENT_TABLE
from core.db.rest import query

# PARTITION BY YEAR: one row per month, ~65 years, so ~780 rows in total.
# MONTH partitioning would create 780 single-row partitions -- the same
# partition-count blowup BACKLOG.md records for equity_prices (11,513
# partitions, with QuestDB crashing under it).
REGIME_DDL = f"""
CREATE TABLE IF NOT EXISTS {REGIME_TABLE} (
    quadrant SYMBOL,
    growth_z DOUBLE,
    inflation_z DOUBLE,
    growth_delta DOUBLE,
    inflation_delta DOUBLE,
    growth_gamma DOUBLE,
    inflation_gamma DOUBLE,
    growth_components INT,
    inflation_components INT,
    confidence DOUBLE,
    timestamp TIMESTAMP
) TIMESTAMP(timestamp) PARTITION BY YEAR WAL
  DEDUPLICATE UPSERT KEYS(timestamp);
"""

# One row per trading day, ~250/year. YEAR partitions stay comfortably sized
# and the whole table is a single-digit number of MB at 30 years.
SENTIMENT_DDL = f"""
CREATE TABLE IF NOT EXISTS {SENTIMENT_TABLE} (
    momentum DOUBLE,
    volatility DOUBLE,
    safe_haven DOUBLE,
    junk_bond DOUBLE,
    breadth DOUBLE,
    composite DOUBLE,
    components INT,
    timestamp TIMESTAMP
) TIMESTAMP(timestamp) PARTITION BY YEAR WAL
  DEDUPLICATE UPSERT KEYS(timestamp);
"""


def ensure_tables() -> None:
    """Create both tables if absent. Idempotent, safe to call on every start."""
    for ddl in (REGIME_DDL, SENTIMENT_DDL):
        query(ddl)
