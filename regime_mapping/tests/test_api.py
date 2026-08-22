"""Every endpoint, against a fake table store.

The point is not that FastAPI routes work -- it is that the responses are
valid JSON. pandas hands out NaN freely (a missing component, a Delta before
enough history), json.dumps writes it as a bare `NaN` token, and no strict
parser accepts that, the browser's included. Every assertion below re-parses
with allow_nan=False, which is the check that catches it.
"""

import json

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api import reads
from api.main import app
from core import regime as R
from core.db import rest

MONTHS = pd.date_range("2023-01-31", periods=6, freq="ME")
DAYS = pd.bdate_range("2024-06-03", periods=5)


def regime_frame():
    f = pd.DataFrame({
        "quadrant": ["Deflation", "Deflation", "Transition", "Reflation",
                     "Reflation", "Stagflation"],
        "confidence": [0.71, 0.66, 0.12, 0.42, 0.55, 0.61],
        "growth_z": [-1.2, -1.0, -0.2, 0.4, 0.7, 0.3],
        "inflation_z": [-0.8, -0.6, 0.0, 0.6, 1.1, 1.4],
        "growth_delta": [-0.8, -0.7, -0.05, 0.4, 0.5, -0.4],
        "inflation_delta": [-0.5, -0.4, 0.02, 0.5, 0.6, 0.5],
        # NaN on purpose: Gamma needs more history than Delta, so the earliest
        # rows genuinely have none.
        "growth_gamma": [np.nan, np.nan, 0.1, 0.3, 0.2, -0.6],
        "inflation_gamma": [np.nan, np.nan, 0.05, 0.4, 0.1, -0.1],
        "growth_components": [6, 6, 6, 6, 6, 6],
        "inflation_components": [3, 3, 3, 3, 3, 3],
    }, index=MONTHS)
    f.index.name = "timestamp"
    return f


def sentiment_frame():
    f = pd.DataFrame({
        "momentum": [72.0, 68.0, 55.0, 41.0, 33.0],
        "volatility": [80.0, 76.0, 60.0, 38.0, 22.0],
        "safe_haven": [65.0, 61.0, 50.0, 44.0, 30.0],
        "junk_bond": [70.0, 66.0, 58.0, 47.0, 35.0],
        "breadth": [np.nan, np.nan, np.nan, 40.0, 28.0],   # thin universe early
        "composite": [71.75, 67.75, 55.75, 42.0, 29.6],
        "components": [4, 4, 4, 5, 5],
    }, index=DAYS)
    f.index.name = "timestamp"
    return f


@pytest.fixture
def client(monkeypatch):
    """Serve the two computed tables from memory.

    api.reads is patched rather than core.db.rest.query, so the routes' own
    SQL is bypassed but everything above it -- serialisation, labelling,
    tilt computation, error handling -- runs for real.
    """
    regime, sentiment = regime_frame(), sentiment_frame()
    monkeypatch.setattr(reads, "regime_history",
                        lambda limit=24: regime.iloc[-limit:])
    monkeypatch.setattr(reads, "sentiment_history",
                        lambda limit=250: sentiment.iloc[-limit:])
    monkeypatch.setattr(rest, "table_exists", lambda name: True)
    return TestClient(app)


def strict(response):
    """Body re-parsed with allow_nan=False. Raises on NaN or Infinity."""
    return json.loads(json.dumps(response.json(), allow_nan=False))


# --------------------------------------------------------------------------

def test_health_reports_freshness(client):
    body = strict(client.get("/health"))
    assert body["status"] == "ok"
    assert body["last_regime"] == "2023-06-30"
    assert body["regime_call"] == "Stagflation"
    assert body["last_sentiment"] == "2024-06-07"


def test_regime_returns_the_latest_call(client):
    body = strict(client.get("/api/regime"))
    assert body["quadrant"] == "Stagflation"
    assert body["as_of"] == "2023-06-30"
    assert "inflationary contraction" in body["description"]
    assert "Stagflation" in body["reading"]
    # Derived: CALL_RADIUS / FULL_CONFIDENCE_RADIUS.
    assert body["confidence_floor"] == pytest.approx(
        R.CALL_RADIUS / R.FULL_CONFIDENCE_RADIUS)


def test_regime_history_is_oldest_first(client):
    body = strict(client.get("/api/regime/history?months=6"))
    assert body["months"] == 6
    dates = [p["as_of"] for p in body["points"]]
    assert dates == sorted(dates)


def test_regime_history_nan_gamma_becomes_null_not_nan(client):
    """The specific thing that breaks a browser JSON.parse."""
    body = strict(client.get("/api/regime/history?months=6"))
    assert body["points"][0]["growth_gamma"] is None


def test_regime_history_rejects_a_silly_window(client):
    assert client.get("/api/regime/history?months=0").status_code == 422
    assert client.get("/api/regime/history?months=99999").status_code == 422


def test_tilts_reflect_the_current_regime(client):
    body = strict(client.get("/api/regime/tilts"))
    assert body["regime"] == "Stagflation"
    assert sum(body["tilted"].values()) == pytest.approx(100.0, abs=0.05)
    # Stagflation favours real assets over equities.
    assert body["delta_vs_baseline"]["Gold"] > 0
    assert body["delta_vs_baseline"]["Equities"] < 0
    assert "not investment advice" in body["disclaimer"].lower()


def test_tilts_are_damped_by_low_confidence(client, monkeypatch):
    """A Transition call must barely move the portfolio."""
    frame = regime_frame()
    frame.loc[frame.index[-1], "quadrant"] = "Transition"
    frame.loc[frame.index[-1], "confidence"] = 0.08
    monkeypatch.setattr(reads, "regime_history",
                        lambda limit=24: frame.iloc[-limit:])
    body = strict(client.get("/api/regime/tilts"))
    assert body["tilted"] == pytest.approx(body["baseline"])


def test_sentiment_returns_label_and_reading(client):
    body = strict(client.get("/api/sentiment"))
    assert body["composite"] == pytest.approx(29.6)
    assert body["label"] == "Fear"
    assert body["components"] == 5
    assert body["components_expected"] == 5
    assert "Most fearful" in body["reading"]


def test_sentiment_history_null_is_a_missing_component(client):
    body = strict(client.get("/api/sentiment/history?days=5"))
    assert body["days"] == 5
    assert body["points"][0]["breadth"] is None
    assert body["points"][0]["components"] == 4


def test_with_sentiment_falls_back_when_pg_wire_is_down(client):
    """8812 unreachable must degrade the response, not fail it."""
    body = strict(client.get("/api/regime/with_sentiment?months=6"))
    assert body["joined"] is False
    assert body["months"] == 6


def test_endpoints_return_503_with_an_actionable_message_when_empty(monkeypatch):
    empty = pd.DataFrame()
    monkeypatch.setattr(reads, "regime_history", lambda limit=24: empty)
    monkeypatch.setattr(reads, "sentiment_history", lambda limit=250: empty)
    monkeypatch.setattr(rest, "table_exists", lambda name: True)
    c = TestClient(app)
    for path in ("/api/regime", "/api/regime/history", "/api/regime/tilts",
                 "/api/sentiment", "/api/sentiment/history"):
        r = c.get(path)
        assert r.status_code == 503, path
        assert "backfill_history.py" in r.json()["detail"], path


def test_health_stays_200_when_questdb_is_unreachable(monkeypatch):
    """"Up but with no data" is recoverable; a 500 here would read as broken."""
    def boom(name):
        raise rest.QueryError("QuestDB unreachable at http://questdb:9000")
    monkeypatch.setattr(rest, "table_exists", boom)
    body = strict(TestClient(app).get("/health"))
    assert body["status"] == "degraded"
    assert body["reachable"] is False
    assert "unreachable" in body["error"]


# --------------------------------------------------------------------------
# integer fields must stay integers
# --------------------------------------------------------------------------

def test_component_counts_serialise_as_ints_not_floats(client):
    """`df.iloc[-1]` and `iterrows()` both collapse a mixed-dtype frame to a
    single dtype, which turns an int64 count into 5.0 and renders as "5.0 of 5
    components". Asserted with isinstance rather than ==, because 5.0 == 5."""
    body = strict(client.get("/api/sentiment"))
    assert isinstance(body["components"], int)
    assert not isinstance(body["components"], float)

    regime = strict(client.get("/api/regime"))
    for key in ("growth_components", "inflation_components"):
        assert isinstance(regime[key], int), key


def test_history_component_counts_are_ints_too(client):
    hist = strict(client.get("/api/sentiment/history?days=5"))
    assert isinstance(hist["points"][-1]["components"], int)
    reg = strict(client.get("/api/regime/history?months=6"))
    assert isinstance(reg["points"][-1]["growth_components"], int)


def test_floats_stay_floats(client):
    """The fix must not go the other way and integerise a round confidence."""
    body = strict(client.get("/api/regime"))
    assert isinstance(body["confidence"], float)
