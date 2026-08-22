"""Nightly worker: ingest the extra FRED series, then recompute both tables.

Scheduling sits after open-finance's own jobs so it reads fresh data rather
than yesterday's. open-finance runs, in order:

    00:05  corporate actions        00:07  intraday partition cleanup
    00:10  daily equity backfill    01:30  FRED macro ingest

So this worker starts at 02:00, and the recompute at 02:30 once its own FRED
fetch has landed.
"""

import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from apscheduler.schedulers.blocking import BlockingScheduler

from worker import extra_series, recompute, tickers

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)

STARTUP_DELAY_SECONDS = 10


# The recompute reads the whole macro history in a handful of large queries, and
# it competes for QuestDB with open-finance's own ingestion. On a cold start that
# contention is guaranteed rather than unlucky: register_all() below asks
# open-finance to track the All Weather sleeve proxies, which kicks off several
# concurrent multi-decade yfinance backfills, and the recompute then runs
# straight into them. Observed on 2026-08-22 -- five tracks accepted at 15:19:44,
# read timeout at 15:20:44, recompute abandoned at 15:22:27.
#
# One attempt meant a single unlucky minute cost a whole day: the next run is
# 02:00 tomorrow, so both tables stay missing and the dashboard shows "No regime
# history yet" until then. Retrying costs nothing when it succeeds first time.
RECOMPUTE_ATTEMPTS = 4
RECOMPUTE_BACKOFF_SECONDS = (60, 180, 420)


def _recompute_with_retry() -> None:
    for attempt in range(1, RECOMPUTE_ATTEMPTS + 1):
        try:
            counts = recompute.run_all()
            logger.info("Recompute complete on attempt %d: %s", attempt, counts)
            return
        except Exception as e:
            if attempt == RECOMPUTE_ATTEMPTS:
                logger.error("Recompute failed after %d attempts: %s",
                             RECOMPUTE_ATTEMPTS, e)
                return
            wait = RECOMPUTE_BACKOFF_SECONDS[attempt - 1]
            logger.warning("Recompute attempt %d/%d failed (%s); retrying in %ds",
                           attempt, RECOMPUTE_ATTEMPTS, e, wait)
            time.sleep(wait)


def nightly() -> None:
    """Ingest, then recompute. One log line per stage, so a partial failure is
    visible in `docker compose logs` without needing the database."""
    try:
        written = extra_series.run_once()
        logger.info("FRED ingest complete: %s", written)
    except Exception as e:
        logger.error("FRED ingest failed: %s", e)

    _recompute_with_retry()


def main() -> None:
    logger.info("regime_mapping worker starting up")
    time.sleep(STARTUP_DELAY_SECONDS)

    # Registration is idempotent and cheap, and doing it on every start means
    # a fresh QuestDB volume recovers without a manual step.
    try:
        logger.info("Ticker registration: %s", tickers.register_all())
    except Exception as e:
        logger.error("Ticker registration failed: %s", e)

    nightly()

    scheduler = BlockingScheduler()
    scheduler.add_job(nightly, "cron", hour="2", minute="0",
                      id="ingest-and-recompute")
    logger.info("Worker scheduler active (nightly at 02:00)")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass


if __name__ == "__main__":
    main()
