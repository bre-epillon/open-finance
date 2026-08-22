"""The MCP tools, including what they say when the database is not there.

The failure path is the point. FastMCP surfaces a raised exception to the
caller verbatim, so an uncaught QueryError reaches the model as a wrapped
urllib3 connection-pool stack -- twenty lines of noise for a consumer whose
only useful next step is "start the container". These tests pin the short
message instead.
"""

import asyncio
import json

import numpy as np
import pandas as pd
import pytest

from api import reads
from core.db.rest import QueryError
from mcp_server import server as srv

MONTHS = pd.date_range("2023-01-31", periods=3, freq="ME")
DAYS = pd.bdate_range("2024-06-03", periods=3)


def regime_frame():
    f = pd.DataFrame({
        "quadrant": ["Reflation", "Reflation", "Stagflation"],
        "confidence": [0.44, 0.51, 0.63],
        "growth_z": [0.4, 0.7, 0.3], "inflation_z": [0.6, 1.1, 1.4],
        "growth_delta": [0.4, 0.5, -0.4],
        "inflation_delta": [0.5, 0.6, 0.5],
        "growth_gamma": [np.nan, 0.2, -0.6],
        "inflation_gamma": [0.4, 0.1, -0.1],
        "growth_components": [6, 6, 6], "inflation_components": [3, 3, 3],
    }, index=MONTHS)
    f.index.name = "timestamp"
    return f


def sentiment_frame():
    f = pd.DataFrame({
        "momentum": [55.0, 41.0, 33.0], "volatility": [60.0, 38.0, 22.0],
        "safe_haven": [50.0, 44.0, 30.0], "junk_bond": [58.0, 47.0, 35.0],
        "breadth": [np.nan, 40.0, 28.0],
        "composite": [55.75, 42.0, 29.6], "components": [4, 5, 5],
    }, index=DAYS)
    f.index.name = "timestamp"
    return f


def call(tool, **kw):
    """Invoke a FastMCP tool and return its payload as a dict.

    The SDK hands back a list of content blocks whose text is the
    JSON-serialised return value. Parsing it here rather than reaching into
    the function directly means these tests exercise the same serialisation
    path a real MCP client sees -- which is where a stray NaN would surface,
    since json.dumps inside the SDK would reject it.
    """
    async def run():
        result = await srv.server.call_tool(tool, kw)
        if isinstance(result, tuple):          # (content, structured)
            result = result[0]
        return json.loads(result[0].text)
    return asyncio.run(run())


@pytest.fixture
def wired(monkeypatch):
    r, s = regime_frame(), sentiment_frame()
    monkeypatch.setattr(reads, "regime_history", lambda limit=24: r.iloc[-limit:])
    monkeypatch.setattr(reads, "sentiment_history",
                        lambda limit=250: s.iloc[-limit:])


@pytest.fixture
def unreachable(monkeypatch):
    def boom(*a, **k):
        raise QueryError("QuestDB unreachable at http://questdb:9000: "
                         "HTTPConnectionPool(host='questdb', port=9000): Max "
                         "retries exceeded with url: /exec?query=SELECT...")
    monkeypatch.setattr(reads, "regime_history", boom)
    monkeypatch.setattr(reads, "sentiment_history", boom)


@pytest.fixture
def empty(monkeypatch):
    monkeypatch.setattr(reads, "regime_history", lambda limit=24: pd.DataFrame())
    monkeypatch.setattr(reads, "sentiment_history",
                        lambda limit=250: pd.DataFrame())


# --------------------------------------------------------------------------

def test_the_three_tools_are_registered():
    tools = asyncio.run(srv.server.list_tools())
    assert {t.name for t in tools} == {"get_regime", "get_sentiment",
                                      "get_regime_history"}


def test_every_tool_describes_itself_for_a_model():
    """The description is the only thing the model reads before choosing."""
    for tool in asyncio.run(srv.server.list_tools()):
        assert tool.description and len(tool.description) > 80, tool.name


def test_get_regime_returns_a_reading_and_tilts(wired):
    out = call("get_regime")
    assert out["quadrant"] == "Stagflation"
    assert "Stagflation" in out["reading"]
    assert "inflationary contraction" in out["description"]
    assert out["tilts"]["tilted"]["Gold"] > out["tilts"]["baseline"]["Gold"]
    assert "not investment advice" in out["tilts"]["disclaimer"].lower()


def test_get_regime_output_is_valid_json(wired):
    """NaN gamma must serialise as null; a bare NaN is not JSON."""
    body = json.dumps(call("get_regime"), allow_nan=False)
    assert '"growth_gamma"' in body


def test_get_sentiment_reports_the_component_count(wired):
    out = call("get_sentiment")
    assert out["label"] == "Fear"
    assert out["components"] == 5 and out["components_expected"] == 5
    json.dumps(out, allow_nan=False)


def test_get_regime_history_is_oldest_first(wired):
    out = call("get_regime_history", months=3)
    assert out["months"] == 3
    dates = [p["as_of"] for p in out["points"]]
    assert dates == sorted(dates)


def test_get_regime_history_clamps_a_silly_window(wired):
    """No HTTP validation layer here, so the tool clamps its own input."""
    assert call("get_regime_history", months=-5)["months"] >= 1
    assert call("get_regime_history", months=10 ** 9)["months"] <= 1200


@pytest.mark.parametrize("tool", ["get_regime", "get_sentiment",
                                  "get_regime_history"])
def test_an_unreachable_database_gives_a_short_actionable_error(unreachable,
                                                               tool):
    out = call(tool)
    assert "Cannot reach QuestDB" in out["error"]
    assert "docker compose ps" in out["error"]
    # The urllib3 detail must not come along for the ride.
    assert "HTTPConnectionPool" not in json.dumps(out)
    assert len(json.dumps(out)) < 400


@pytest.mark.parametrize("tool,needle", [
    ("get_regime", "backfill_history.py"),
    ("get_sentiment", "backfill_history.py"),
    ("get_regime_history", "backfill_history.py"),
])
def test_empty_tables_name_the_script_that_fills_them(empty, tool, needle):
    assert needle in call(tool)["error"]
