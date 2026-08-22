"""The one query that genuinely needs QuestDB's pg-wire protocol.

Everything else reads over REST. ASOF JOIN is a QuestDB SQL extension, so it
works over either transport -- but this is the query where it earns its place,
and running it over pg-wire on 8812 keeps it separate from the bulk pulls and
gives proper parameter binding for the one user-supplied value.

The join itself: regime_history has one row per month, sentiment_index one per
trading day. ASOF JOIN matches each regime row to the most recent sentiment
row at or before it -- exactly the "what did sentiment look like at that
regime point" semantics, and awkward to express any other way.
"""

import logging

import pandas as pd

from core.config import (QUESTDB_HOST, QUESTDB_PG_PASSWORD, QUESTDB_PG_PORT,
                         QUESTDB_PG_USER, REGIME_TABLE, SENTIMENT_TABLE)

logger = logging.getLogger(__name__)

CONNINFO = (f"host={QUESTDB_HOST} port={QUESTDB_PG_PORT} "
            f"user={QUESTDB_PG_USER} password={QUESTDB_PG_PASSWORD} "
            f"dbname=qdb")

ASOF_SQL = f"""
SELECT r.timestamp, r.quadrant, r.confidence,
       r.growth_z, r.inflation_z,
       r.growth_delta, r.inflation_delta,
       r.growth_gamma, r.inflation_gamma,
       s.composite AS sentiment, s.components AS sentiment_components
FROM {REGIME_TABLE} r
ASOF JOIN {SENTIMENT_TABLE} s
ORDER BY r.timestamp DESC
LIMIT %(limit)s
"""


def regime_with_sentiment(limit: int = 24) -> pd.DataFrame:
    """Recent regime rows, each carrying the sentiment reading as of that date.

    Returns an empty frame rather than raising if pg-wire is unavailable --
    the caller falls back to two separate REST reads, so an unreachable 8812
    degrades the response instead of failing it.
    """
    try:
        import psycopg
    except ImportError:
        logger.warning("psycopg not installed; skipping the ASOF JOIN read")
        return pd.DataFrame()

    try:
        with psycopg.connect(CONNINFO, connect_timeout=10) as conn:
            with conn.cursor() as cur:
                cur.execute(ASOF_SQL, {"limit": int(limit)})
                cols = [d.name for d in cur.description]
                rows = cur.fetchall()
    except Exception as e:
        logger.warning("pg-wire ASOF read failed (%s); falling back to REST", e)
        return pd.DataFrame()

    df = pd.DataFrame(rows, columns=cols)
    if "timestamp" in df.columns and not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
    return df.sort_values("timestamp") if not df.empty else df
