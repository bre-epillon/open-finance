"""QuestDB reads over the REST /exec endpoint, into pandas.

REST rather than pg-wire for bulk pulls, matching what open-finance's own code
does -- one fewer moving part, and the payload is JSON we can hand straight to
a DataFrame. core/db/pg.py covers the one query that genuinely needs pg-wire.
"""

import pandas as pd
import requests

from core.config import (HTTP_TIMEOUT, MACRO_TABLE, PRICE_TABLE, REST_URL)


class QueryError(RuntimeError):
    """QuestDB rejected the query, or was unreachable."""


def query(sql: str) -> pd.DataFrame:
    """Run one SQL statement, return a DataFrame with typed timestamps."""
    try:
        r = requests.get(f"{REST_URL}/exec", params={"query": sql},
                         timeout=HTTP_TIMEOUT)
    except requests.exceptions.RequestException as e:
        raise QueryError(f"QuestDB unreachable at {REST_URL}: {e}") from e
    if r.status_code != 200:
        raise QueryError(f"HTTP {r.status_code}: {r.text[:400]}")

    body = r.json()
    if "error" in body:
        raise QueryError(f"{body['error']} -- query was: {sql.strip()[:200]}")

    cols = [c["name"] for c in body.get("columns", [])]
    df = pd.DataFrame(body.get("dataset", []), columns=cols)
    if "timestamp" in df.columns:
        df["timestamp"] = pd.to_datetime(df["timestamp"], format="mixed",
                                         utc=True).dt.tz_localize(None)
    return df


def table_exists(name: str) -> bool:
    tables = query("SHOW TABLES")
    return not tables.empty and name in set(tables.iloc[:, 0])


def _series(df: pd.DataFrame, value_col: str) -> pd.Series:
    """timestamp/value DataFrame -> clean, unique-indexed, sorted Series.

    The de-dup is not belt-and-braces. macro_indicators was auto-created by an
    ILP Sender and therefore has no DEDUPLICATE UPSERT KEYS, while fred_worker
    re-ingests its whole observation window nightly -- so identical
    (timestamp, indicator) rows are the norm, not the exception, and a pivot
    would raise on them. keep='last' also gives correct handling of a genuine
    FRED revision for free. See patches/0003-macro-dedup.sql.
    """
    if df.empty:
        return pd.Series(dtype="float64")
    s = df.set_index("timestamp")[value_col].astype("float64").sort_index()
    return s[~s.index.duplicated(keep="last")]


def macro_series(indicator: str) -> pd.Series:
    """One macro indicator's full history."""
    return _series(query(
        f"SELECT timestamp, value FROM {MACRO_TABLE} "
        f"WHERE indicator = '{indicator}' ORDER BY timestamp"
    ), "value")


def macro_frame(indicators: list[str]) -> dict[str, pd.Series]:
    """Several indicators in one round trip, as name -> Series.

    A dict rather than a wide DataFrame because the series have genuinely
    different frequencies and calendars; pivoting them into one frame here
    would force an alignment decision that belongs in core/align.py.
    """
    if not indicators:
        return {}
    quoted = ", ".join(f"'{i}'" for i in indicators)
    df = query(
        f"SELECT timestamp, indicator, value FROM {MACRO_TABLE} "
        f"WHERE indicator IN ({quoted}) ORDER BY timestamp"
    )
    if df.empty:
        return {}
    return {
        name: _series(g[["timestamp", "value"]], "value")
        for name, g in df.groupby("indicator", sort=False)
    }


def price_frame(tickers: list[str], start: str | None = None) -> pd.DataFrame:
    """Wide daily close prices, one column per ticker, trading-day index.

    No calendar resampling: the index is whatever trading days QuestDB holds.
    Resampling to calendar days is what turned the parked sentiment code's
    250-day windows into ~8 months of history.
    """
    if not tickers:
        return pd.DataFrame()
    quoted = ", ".join(f"'{t}'" for t in tickers)
    where = f"ticker IN ({quoted})"
    if start:
        where += f" AND timestamp >= '{start}'"
    df = query(
        f"SELECT timestamp, ticker, close FROM {PRICE_TABLE} "
        f"WHERE {where} ORDER BY timestamp"
    )
    if df.empty:
        return pd.DataFrame()
    df = df.drop_duplicates(subset=["timestamp", "ticker"], keep="last")
    wide = df.pivot(index="timestamp", columns="ticker", values="close")
    return wide.astype("float64").sort_index()


def tracked_tickers(min_bars: int = 125) -> list[str]:
    """Tickers in equity_prices with enough history to be a breadth constituent.

    open-finance's BACKLOG.md notes several recently-added tickers hold only a
    handful of days; including those would make breadth jump around as thin
    names flicker above and below a moving average built from almost no data.
    """
    df = query(
        f"SELECT ticker, count() AS bars FROM {PRICE_TABLE} GROUP BY ticker"
    )
    if df.empty:
        return []
    return sorted(df.loc[df["bars"] >= min_bars, "ticker"].tolist())
