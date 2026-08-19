import os
import sys
import time
import logging
import datetime
import requests
import yfinance as yf
import pandas as pd
from questdb.ingress import Sender
from apscheduler.schedulers.background import BlockingScheduler

import corporate_actions

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from shared.backfill import execute_historical_backfill

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

QUESTDB_HOST = os.getenv("QUESTDB_HOST", "questdb")
QUESTDB_ILP_PORT = int(os.getenv("QUESTDB_ILP_PORT", 9009))
QUESTDB_REST_PORT = int(os.getenv("QUESTDB_REST_PORT", 9000))
API_HOST = os.getenv("API_HOST", "financial_api:8000")

FX_BONDS_TICKERS = ['EURUSD=X', 'GBPUSD=X', 'JPY=X', 'INR=X', 'CHF=X', '^TNX', '^IRX', '^TYX', '^FVX', '^GSPC', '^VIX', 'TLT', 'HYG', 'LQD']

def get_api_tickers():
    try:
        response = requests.get(f"http://{API_HOST}/api/tickers", timeout=10)
        if response.status_code == 200:
            return response.json()
    except Exception as e:
        logger.error(f"Failed to fetch tickers from API: {e}")
    return []

def get_all_tickers():
    return list(set(get_api_tickers() + FX_BONDS_TICKERS))

# get_latest_timestamp_db, DB_CHECK_FAILED, and execute_historical_backfill live in
# shared/backfill.py -- this used to be a near-duplicate of api/api.py's copy, and the
# two had already drifted (different "is this ticker stale" thresholds).

INTRADAY_TABLE = "equity_prices_intraday"
INTRADAY_RETENTION_DAYS = 4

def scheduled_realtime_ingest():
    tickers = get_all_tickers()
    if not tickers:
        return
    # Written to a dedicated short-retention table, not equity_prices -- that table holds
    # full daily history, and mixing in hourly ticks there made resolution=1h ambiguous
    # (only ever true for the last ~2 days) and grew it without bound.
    logger.info(f"Running scheduled realtime (1h) ingest for {len(tickers)} assets.")
    try:
        data = yf.download(tickers, period="2d", interval="1h", progress=False)
        with Sender.from_conf(f"tcp::addr={QUESTDB_HOST}:{QUESTDB_ILP_PORT};") as sender:
            for ticker in tickers:
                if len(tickers) == 1:
                    ticker_df = data.dropna()
                else:
                    if ticker not in data['Close']: continue
                    ticker_df = pd.DataFrame({
                        'Open': data['Open'][ticker],
                        'High': data['High'][ticker],
                        'Low': data['Low'][ticker],
                        'Close': data['Close'][ticker],
                        'Volume': data['Volume'][ticker]
                    }).dropna()

                for timestamp, row in ticker_df.iterrows():
                    sender.row(
                        INTRADAY_TABLE,
                        symbols={'ticker': ticker},
                        columns={
                            'open': float(row['Open']), 'high': float(row['High']),
                            'low': float(row['Low']), 'close': float(row['Close']),
                            'volume': int(row['Volume'])
                        },
                        at=timestamp.to_pydatetime()
                    )
            sender.flush()
        logger.info("Realtime ingest complete.")
    except Exception as e:
        logger.error(f"Scheduled realtime ingestion error: {e}")

def scheduled_intraday_cleanup():
    # QuestDB has no row-level DELETE on WAL tables -- partition drop is the idiomatic
    # way to expire old data, which is exactly why this table is PARTITION BY DAY despite
    # equity_prices itself having moved away from DAY partitioning (unbounded retention
    # there is what caused the partition-count blowup; here retention is intentionally
    # short, so DAY partitions are the right granularity to drop by).
    cutoff = (datetime.date.today() - datetime.timedelta(days=INTRADAY_RETENTION_DAYS)).isoformat()
    query = f"ALTER TABLE {INTRADAY_TABLE} DROP PARTITION WHERE timestamp < '{cutoff}'"
    try:
        response = requests.get(f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exec", params={'query': query}, timeout=15)
        if response.status_code == 200:
            logger.info(f"Dropped {INTRADAY_TABLE} partitions older than {cutoff}.")
        else:
            logger.error(f"Intraday cleanup failed: {response.text}")
    except Exception as e:
        logger.error(f"Intraday cleanup error: {e}")

def scheduled_daily_backfill():
    tickers = get_all_tickers()
    logger.info(f"Running daily historical backfill for {len(tickers)} assets.")
    for t in tickers:
        execute_historical_backfill(t)

def scheduled_corporate_actions_check():
    tickers = get_all_tickers()
    logger.info(f"Checking {len(tickers)} assets for new stock splits.")
    corporate_actions.check_all(tickers)

if __name__ == "__main__":
    logger.info("Worker starting up...")

    # Wait briefly for API/QuestDB to be ready
    time.sleep(5)

    # Perform initial daily backfill for all FX and Bonds immediately on start
    scheduled_daily_backfill()

    # Catch any stock splits that occurred, so history stays on a single consistent basis
    scheduled_corporate_actions_check()

    scheduler = BlockingScheduler()
    # Real-time sync every hour
    scheduler.add_job(scheduled_realtime_ingest, 'cron', minute='0')
    # Check for new stock splits shortly before the daily historical backfill
    scheduler.add_job(scheduled_corporate_actions_check, 'cron', hour='0', minute='5')
    # Drop expired intraday partitions before the day's backfill runs
    scheduler.add_job(scheduled_intraday_cleanup, 'cron', hour='0', minute='7')
    # Historical backfill once daily at midnight
    scheduler.add_job(scheduled_daily_backfill, 'cron', hour='0', minute='10')
    
    logger.info("Worker scheduler active.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass