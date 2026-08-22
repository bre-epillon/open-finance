"""Register the extra tickers this project needs with open-finance's API.

POST /api/track validates the symbol against yfinance and queues
shared/backfill.py's chunked historical backfill in the background, so there
is no ingestion code to write here -- only the registration.

Side effect worth knowing about: these symbols land in open-finance's
api/tickers.json and will show up in its portfolio UI ticker list. That is the
trade for not running a second price-ingestion pipeline.
"""

import logging

import requests

from core.config import OPEN_FINANCE_API
from core.tilts import PROXY_TICKERS

logger = logging.getLogger(__name__)

# ^VIX3M is a fallback for the breadth component if open-finance's tracked
# universe turns out too thin for it (scripts/check_data.py reports the
# constituent count). The rest are the All Weather sleeve proxies the
# dashboard charts against.
EXTRA_TICKERS = sorted(set(PROXY_TICKERS.values()) | {"^VIX3M"})


def register_all(tickers: list[str] | None = None) -> dict[str, str]:
    """Ask open-finance to track and backfill each ticker. Idempotent."""
    results = {}
    for t in tickers or EXTRA_TICKERS:
        try:
            r = requests.post(f"{OPEN_FINANCE_API}/api/track",
                              params={"ticker": t}, timeout=30)
            if r.status_code == 200:
                results[t] = r.json().get("status", "ok")
            else:
                results[t] = f"http_{r.status_code}"
        except requests.exceptions.RequestException as e:
            results[t] = f"unreachable: {e}"
        logger.info("track %s -> %s", t, results[t])
    return results
