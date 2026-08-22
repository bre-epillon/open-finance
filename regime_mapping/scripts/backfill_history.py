#!/usr/bin/env python3
"""One-off: ingest the extra FRED series and rebuild both computed tables.

Safe to re-run. Both tables declare DEDUPLICATE UPSERT KEYS(timestamp), so a
second run upserts rather than appends.

    python scripts/backfill_history.py              # ingest + recompute
    python scripts/backfill_history.py --no-fetch    # recompute only
    python scripts/backfill_history.py --register    # also register tickers
"""

import argparse
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from worker import extra_series, recompute, tickers

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--no-fetch", action="store_true",
                   help="skip the FRED ingest, recompute from what is in the DB")
    p.add_argument("--register", action="store_true",
                   help="also ask open-finance to track the extra tickers")
    a = p.parse_args()

    if a.register:
        logger.info("Ticker registration: %s", tickers.register_all())

    if not a.no_fetch:
        logger.info("FRED ingest: %s", extra_series.run_once())
    else:
        logger.info("Skipping FRED ingest (--no-fetch)")

    counts = recompute.run_all()
    logger.info("Wrote %d regime rows and %d sentiment rows",
                counts["regime"], counts["sentiment"])

    if counts["regime"] == 0:
        logger.error(
            "No regime rows. Almost always one of: (a) FRED history is still "
            "capped at 5 years, so every trailing z-score is NaN -- apply "
            "patches/0002; (b) the growth or inflation axis has fewer than 2 "
            "usable series. Run scripts/check_data.py.")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
