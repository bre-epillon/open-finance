"""FastAPI app for the regime and sentiment engine. Port 8100.

Reads the computed tables only. The nightly worker owns all computation; a
route that recomputed on demand would reintroduce the slow-startup problem
BACKLOG.md records for open-finance's API.
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import reads
from api.routes import regime, sentiment
from core.config import (API_PORT, DEMO_MODE, REGIME_TABLE, REST_URL,
                         SENTIMENT_TABLE)
# Imported as a module, not by name: `from ... import table_exists` binds the
# function into this namespace, which makes it unpatchable in tests -- the
# health tests silently hit the real network instead of the fixture until this
# was changed.
from core.db import rest

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(
    title="Regime & Sentiment Engine",
    description="Dalio 4-quadrant macro regime map and a Greed & Fear index, "
                "computed from the QuestDB instance owned by open-finance.",
    version="0.1.0",
)

# Same permissive policy as open-finance's API: single-user, localhost-only.
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(regime.router)
app.include_router(sentiment.router)


@app.get("/health")
def health():
    """Reachability and freshness, in one call.

    Returns 200 even when the tables are empty -- "up but with no data yet" is
    a real and recoverable state, and a 500 here would make it look like the
    service is broken when it is only waiting for the first recompute.
    """
    out = {"status": "ok", "demo": DEMO_MODE,
           "questdb": REST_URL, "reachable": False,
           "regime_table": False, "sentiment_table": False,
           "last_regime": None, "last_sentiment": None, "regime_call": None}
    try:
        out["regime_table"] = rest.table_exists(REGIME_TABLE)
        out["sentiment_table"] = rest.table_exists(SENTIMENT_TABLE)
        out["reachable"] = True
    except rest.QueryError as e:
        out["status"] = "degraded"
        out["error"] = str(e)
        return out

    if out["regime_table"]:
        row = reads.latest_regime()
        if row is not None:
            out["last_regime"] = row.name.date().isoformat()
            out["regime_call"] = row["quadrant"]
    if out["sentiment_table"]:
        row = reads.latest_sentiment()
        if row is not None:
            out["last_sentiment"] = row.name.date().isoformat()
    return out


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=API_PORT)
