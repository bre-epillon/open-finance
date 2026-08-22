"""core/db/rest.py against a stub QuestDB REST endpoint.

Exercises the real JSON shape QuestDB's /exec returns -- column list plus a
`dataset` array of arrays, with ISO-8601 timestamp strings -- rather than
mocking the parse away, because the parse is the part that breaks.
"""

import http.server
import json
import socketserver
import threading
from urllib.parse import parse_qs, urlparse

import pandas as pd
import pytest

from core.db import rest

TABLES = [["equity_prices"], ["macro_indicators"], ["corporate_actions"]]

# Deliberately duplicated rows, as macro_indicators genuinely is: no
# DEDUPLICATE UPSERT KEYS, and fred_worker re-ingests nightly.
MACRO = [
    ["2024-01-31T00:00:00.000000Z", "Inflation_CPI", 300.0],
    ["2024-01-31T00:00:00.000000Z", "Inflation_CPI", 300.0],
    ["2024-01-31T00:00:00.000000Z", "Inflation_CPI", 301.5],   # a revision
    ["2024-02-29T00:00:00.000000Z", "Inflation_CPI", 302.0],
    ["2024-01-31T00:00:00.000000Z", "Core_CPI", 310.0],
    ["2024-02-29T00:00:00.000000Z", "Core_CPI", 311.0],
]

PRICES = [
    ["2024-01-31T00:00:00.000000Z", "^GSPC", 4800.0],
    ["2024-01-31T00:00:00.000000Z", "^GSPC", 4800.0],
    ["2024-02-01T00:00:00.000000Z", "^GSPC", 4850.0],
    ["2024-01-31T00:00:00.000000Z", "^VIX", 13.0],
    ["2024-02-01T00:00:00.000000Z", "^VIX", 13.5],
]

TICKER_COUNTS = [["^GSPC", 8000], ["^VIX", 8000], ["THIN.DE", 6]]


def _dataset(sql):
    sql = " ".join(sql.split())
    if "SHOW TABLES" in sql:
        return {"columns": [{"name": "table"}], "dataset": TABLES}
    if "bad_table" in sql:
        return {"error": "table does not exist [table=bad_table]"}
    if "count() AS bars" in sql:
        return {"columns": [{"name": "ticker"}, {"name": "bars"}],
                "dataset": TICKER_COUNTS}
    if "FROM macro_indicators" in sql and "indicator," in sql:
        return {"columns": [{"name": "timestamp"}, {"name": "indicator"},
                            {"name": "value"}], "dataset": MACRO}
    if "FROM macro_indicators" in sql:
        rows = [[t, v] for t, i, v in MACRO if f"'{i}'" in sql]
        return {"columns": [{"name": "timestamp"}, {"name": "value"}],
                "dataset": rows}
    if "FROM equity_prices" in sql:
        rows = [r for r in PRICES if f"'{r[1]}'" in sql]
        return {"columns": [{"name": "timestamp"}, {"name": "ticker"},
                            {"name": "close"}], "dataset": rows}
    return {"columns": [], "dataset": []}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        sql = parse_qs(urlparse(self.path).query).get("query", [""])[0]
        body = json.dumps(_dataset(sql)).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


class ReusableServer(socketserver.TCPServer):
    # Port 0 plus SO_REUSEADDR: a fixed port collides with a TIME_WAIT socket
    # left by the previous run, which fails the whole module with an OSError
    # that looks nothing like the real problem.
    allow_reuse_address = True


@pytest.fixture(scope="module")
def stub():
    server = ReusableServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    original = rest.REST_URL
    rest.REST_URL = f"http://127.0.0.1:{port}"
    try:
        yield rest.REST_URL
    finally:
        rest.REST_URL = original
        server.shutdown()
        server.server_close()


def test_query_types_the_timestamp_column(stub):
    df = rest.query("SELECT timestamp, indicator, value FROM macro_indicators")
    assert pd.api.types.is_datetime64_any_dtype(df["timestamp"])
    assert df["timestamp"].dt.tz is None, "naive timestamps keep pandas ops simple"


def test_query_raises_on_a_questdb_error(stub):
    with pytest.raises(rest.QueryError, match="does not exist"):
        rest.query("SELECT * FROM bad_table")


def test_query_error_names_the_offending_sql(stub):
    """A bare QuestDB message with no query attached is very hard to place."""
    with pytest.raises(rest.QueryError, match="bad_table"):
        rest.query("SELECT * FROM bad_table")


def test_query_raises_when_questdb_is_unreachable():
    original = rest.REST_URL
    rest.REST_URL = "http://127.0.0.1:9"
    try:
        with pytest.raises(rest.QueryError, match="unreachable"):
            rest.query("SHOW TABLES")
    finally:
        rest.REST_URL = original


def test_table_exists(stub):
    assert rest.table_exists("macro_indicators")
    assert not rest.table_exists("regime_history")


def test_macro_series_collapses_duplicate_timestamps(stub):
    """The defence that makes every read correct whether or not
    patches/0003-macro-dedup.sql has been applied."""
    s = rest.macro_series("Inflation_CPI")
    assert s.index.is_unique
    assert len(s) == 2
    # keep='last' means a genuine FRED revision wins over the first print.
    assert s.iloc[0] == 301.5


def test_macro_frame_returns_one_clean_series_per_indicator(stub):
    frames = rest.macro_frame(["Inflation_CPI", "Core_CPI"])
    assert set(frames) == {"Inflation_CPI", "Core_CPI"}
    assert all(s.index.is_unique for s in frames.values())
    assert frames["Core_CPI"].tolist() == [310.0, 311.0]


def test_macro_frame_of_nothing_is_empty_not_an_error(stub):
    assert rest.macro_frame([]) == {}


def test_price_frame_pivots_to_one_column_per_ticker(stub):
    wide = rest.price_frame(["^GSPC", "^VIX"])
    assert list(wide.columns) == ["^GSPC", "^VIX"]
    assert wide.index.is_unique, "a duplicate bar would make pivot raise"
    assert wide["^GSPC"].iloc[0] == 4800.0


def test_price_frame_index_is_not_resampled_to_calendar_days(stub):
    """Trading days in, trading days out. Calendar resampling is what turned
    the parked sentiment code's 250-day window into ~8 months."""
    wide = rest.price_frame(["^GSPC"])
    assert len(wide) == 2, "two distinct bars, not a filled calendar range"


def test_tracked_tickers_excludes_thin_history(stub):
    """open-finance holds several tickers with only days of data; they would
    make the breadth component flicker."""
    assert rest.tracked_tickers(min_bars=125) == ["^GSPC", "^VIX"]
    assert "THIN.DE" in rest.tracked_tickers(min_bars=1)
