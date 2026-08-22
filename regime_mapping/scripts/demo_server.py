#!/usr/bin/env python3
"""Run the real API on synthetic data, with no database.

    python scripts/demo_server.py            # http://localhost:8100
    python scripts/demo_server.py --print    # dump the payloads and exit

For frontend work and for showing the dashboard to someone before QuestDB is
populated. It computes the regime and sentiment frames from
scripts/demo_data.py at startup and swaps them in behind api.reads, so every
route, serialiser, label and tilt runs exactly as it does in production --
`core/db` is the only layer bypassed.

EVERY NUMBER IT SERVES IS INVENTED. Nothing here touches FRED, yfinance or
QuestDB. Do not read the output as a statement about the economy.
"""

import argparse
import json
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Before importing core.config, which reads it once at module load. The flag
# reaches the dashboard through /health, which is how the UI knows to say the
# numbers are invented.
os.environ["REGIME_DEMO"] = "1"

from api import reads
from core import regime, sentiment
from core.config import API_PORT
from core.db import rest
from scripts import demo_data

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

BANNER = """
================================================================
  DEMO MODE -- SYNTHETIC DATA
  No FRED, no yfinance, no QuestDB. Every figure is invented.
================================================================"""


def build_frames():
    """Compute both tables in memory."""
    regime_frame = regime.build(demo_data.macro())
    prices = demo_data.prices()
    sentiment_frame = sentiment.build(
        prices,
        junk=demo_data.junk_spread(),
        universe=demo_data.universe(),
    )
    logger.info("Regime: %d months, %s to %s, latest %s",
                len(regime_frame), regime_frame.index[0].date(),
                regime_frame.index[-1].date(), regime_frame.iloc[-1]["quadrant"])
    logger.info("Sentiment: %d days, latest %.1f (%s)",
                len(sentiment_frame), sentiment_frame.iloc[-1]["composite"],
                sentiment.classify(sentiment_frame.iloc[-1]["composite"]))
    return regime_frame, sentiment_frame


def install(regime_frame, sentiment_frame):
    """Serve the in-memory frames through api.reads.

    Patching the two read functions rather than stubbing QuestDB's SQL: the
    frontend does not care which layer the rows came from, and matching
    QuestDB's dialect in a fake would be a second implementation to keep in
    step with the first.
    """
    reads.regime_history = lambda limit=24: regime_frame.iloc[-int(limit):]
    reads.sentiment_history = lambda limit=250: sentiment_frame.iloc[-int(limit):]
    rest.table_exists = lambda name: True


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--port", type=int, default=API_PORT)
    p.add_argument("--print", action="store_true", dest="dump",
                   help="print each endpoint's payload and exit")
    a = p.parse_args()

    print(BANNER)
    regime_frame, sentiment_frame = build_frames()
    install(regime_frame, sentiment_frame)

    from fastapi.testclient import TestClient
    from api.main import app

    if a.dump:
        client = TestClient(app)
        for path in ("/health", "/api/regime", "/api/regime/tilts",
                     "/api/sentiment", "/api/regime/history?months=6",
                     "/api/sentiment/history?days=5"):
            print(f"\n--- GET {path} ---")
            print(json.dumps(client.get(path).json(), indent=2)[:1400])
        return 0

    import uvicorn
    logger.info("Serving the demo API on http://0.0.0.0:%d", a.port)
    logger.info("Point the frontend at it: cd frontend && npm run dev")
    uvicorn.run(app, host="0.0.0.0", port=a.port, log_level="warning")
    return 0


if __name__ == "__main__":
    sys.exit(main())
