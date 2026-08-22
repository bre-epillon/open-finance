"""Table reads shared by the API routes and the MCP server.

Both surfaces answer the same questions, so they read through the same two
functions rather than each writing their own SQL -- open-finance's two
divergent copies of execute_historical_backfill are the cautionary tale.

These read only the computed tables. No route recomputes anything: doing the
maths on the request path is what made open-finance's API restart hang for
minutes (BACKLOG.md, "Correctness / data integrity").
"""

import pandas as pd

from core.config import REGIME_TABLE, SENTIMENT_TABLE
from core.db.rest import query


def _indexed(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    return df.set_index("timestamp").sort_index()


def last_row(df: pd.DataFrame) -> pd.Series | None:
    """Final row as an object-dtype Series, preserving per-column types.

    df.iloc[-1] is the obvious way to do this and it is wrong here: a Series
    carries one dtype, so pulling a row out of a frame with both int and float
    columns upcasts the ints. The visible symptom is an API reporting "5.0 of
    5 components". object dtype keeps each value as the numpy scalar its own
    column held.
    """
    if df.empty:
        return None
    out = pd.Series({c: df[c].iloc[-1] for c in df.columns}, dtype="object")
    out.name = df.index[-1]
    return out


def regime_history(limit: int = 24) -> pd.DataFrame:
    """The last `limit` monthly regime rows, oldest first.

    LIMIT -n takes the last n rows in QuestDB, which on a table with a
    designated timestamp means the most recent ones without a sort.
    """
    return _indexed(query(
        f"SELECT timestamp, quadrant, confidence, growth_z, inflation_z, "
        f"growth_delta, inflation_delta, growth_gamma, inflation_gamma, "
        f"growth_components, inflation_components "
        f"FROM {REGIME_TABLE} LIMIT -{int(limit)}"))


def sentiment_history(limit: int = 250) -> pd.DataFrame:
    """The last `limit` daily sentiment rows, oldest first."""
    return _indexed(query(
        f"SELECT timestamp, momentum, volatility, safe_haven, junk_bond, "
        f"breadth, composite, components "
        f"FROM {SENTIMENT_TABLE} LIMIT -{int(limit)}"))


def latest_regime() -> pd.Series | None:
    return last_row(regime_history(limit=1))


def latest_sentiment() -> pd.Series | None:
    return last_row(sentiment_history(limit=1))
