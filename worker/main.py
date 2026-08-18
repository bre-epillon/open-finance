import os
import time
import logging
import datetime
import requests
import yfinance as yf
import pandas as pd
from questdb.ingress import Sender
from apscheduler.schedulers.background import BlockingScheduler

import corporate_actions

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

# Distinct from None (= ticker genuinely has no rows yet): a query/connection failure must
# never be treated as "new ticker", or a transient DB hiccup triggers a full redundant
# historical backfill instead of just being retried next cycle.
DB_CHECK_FAILED = object()

def get_latest_timestamp_db(ticker: str):
    url = f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exec"
    query = f"SELECT max(timestamp) FROM equity_prices WHERE ticker = '{ticker}'"
    try:
        response = requests.get(url, params={'query': query}, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if data.get('dataset') and len(data['dataset']) > 0 and data['dataset'][0][0]:
                latest_ts = data['dataset'][0][0]
                return datetime.datetime.fromisoformat(latest_ts[:10]).date()
            return None  # ticker genuinely has no rows yet
    except Exception as e:
        logger.error(f"Database check failed for {ticker}: {e}")
    return DB_CHECK_FAILED

def execute_historical_backfill(ticker: str):
    start_date = get_latest_timestamp_db(ticker)
    if start_date is DB_CHECK_FAILED:
        logger.warning(f"Skipping backfill for {ticker} this cycle -- DB check failed.")
        return
    today = datetime.date.today()

    if start_date:
        if (today - start_date).days <= 1:
            logger.info(f"Ticker {ticker} is up to date historically.")
            return

        logger.info(f"Backfilling {ticker} from {start_date} to {today}")
        try:
            data = yf.download(ticker, start=start_date.strftime("%Y-%m-%d"), end=today.strftime("%Y-%m-%d"), interval="1d", progress=False)
            if data.empty: return

            with Sender.from_conf(f"tcp::addr={QUESTDB_HOST}:{QUESTDB_ILP_PORT};") as sender:
                for timestamp, row in data.dropna().iterrows():
                    sender.row(
                        'equity_prices',
                        symbols={'ticker': ticker},
                        columns={
                            'open': float(row['Open'].iloc[0] if isinstance(row['Open'], pd.Series) else row['Open']),
                            'high': float(row['High'].iloc[0] if isinstance(row['High'], pd.Series) else row['High']),
                            'low': float(row['Low'].iloc[0] if isinstance(row['Low'], pd.Series) else row['Low']),
                            'close': float(row['Close'].iloc[0] if isinstance(row['Close'], pd.Series) else row['Close']),
                            'volume': int(row['Volume'].iloc[0] if isinstance(row['Volume'], pd.Series) else row['Volume'])
                        },
                        at=timestamp.to_pydatetime()
                    )
                sender.flush()
            logger.info(f"Backfill complete for {ticker}.")
        except Exception as e:
            logger.error(f"Backfill failed for {ticker}: {e}")
    else:
        # Full historical backfill in chunks
        logger.info(f"Starting chunked historical backfill for new ticker {ticker}")
        end_date = today
        while True:
            chunk_start = end_date - datetime.timedelta(days=365 * 5)
            if chunk_start.year < 1970:
                chunk_start = datetime.date(1970, 1, 1)
                
            logger.info(f"Downloading {ticker} chunk from {chunk_start} to {end_date}")
            try:
                data = yf.download(ticker, start=chunk_start.strftime("%Y-%m-%d"), end=end_date.strftime("%Y-%m-%d"), interval="1d", progress=False)
                if data.empty:
                    break
                    
                with Sender.from_conf(f"tcp::addr={QUESTDB_HOST}:{QUESTDB_ILP_PORT};") as sender:
                    for timestamp, row in data.dropna().iterrows():
                        sender.row(
                            'equity_prices',
                            symbols={'ticker': ticker},
                            columns={
                                'open': float(row['Open'].iloc[0] if isinstance(row['Open'], pd.Series) else row['Open']),
                                'high': float(row['High'].iloc[0] if isinstance(row['High'], pd.Series) else row['High']),
                                'low': float(row['Low'].iloc[0] if isinstance(row['Low'], pd.Series) else row['Low']),
                                'close': float(row['Close'].iloc[0] if isinstance(row['Close'], pd.Series) else row['Close']),
                                'volume': int(row['Volume'].iloc[0] if isinstance(row['Volume'], pd.Series) else row['Volume'])
                            },
                            at=timestamp.to_pydatetime()
                        )
                    sender.flush()
                
                if chunk_start.year <= 1970:
                    break
                    
                end_date = chunk_start
                time.sleep(2) 
                
            except Exception as e:
                logger.error(f"Chunked backfill failed for {ticker}: {e}")
                break

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