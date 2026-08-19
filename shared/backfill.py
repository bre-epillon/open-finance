import os
import time
import logging
import datetime
import requests
import yfinance as yf
import pandas as pd
from questdb.ingress import Sender

logger = logging.getLogger(__name__)

QUESTDB_HOST = os.getenv("QUESTDB_HOST", "localhost")
QUESTDB_ILP_PORT = int(os.getenv("QUESTDB_ILP_PORT", 9009))
QUESTDB_REST_PORT = int(os.getenv("QUESTDB_REST_PORT", 9000))

# Distinct from None (= ticker genuinely has no rows yet): a query/connection failure must
# never be treated as "new ticker", or a transient DB hiccup triggers a full redundant
# historical backfill instead of just being retried next cycle.
DB_CHECK_FAILED = object()


def get_latest_timestamp_db(ticker: str):
    url = f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exec"
    query = f"SELECT max(timestamp) FROM equity_prices WHERE ticker = '{ticker}'"
    try:
        response = requests.get(url, params={"query": query}, timeout=15)
        if response.status_code == 200:
            data = response.json()
            if (
                data.get("dataset")
                and len(data["dataset"]) > 0
                and data["dataset"][0][0]
            ):
                latest_ts = data["dataset"][0][0]
                return datetime.datetime.fromisoformat(latest_ts[:10]).date()
            return None  # ticker genuinely has no rows yet
    except Exception as e:
        logger.error(f"Database check failed for {ticker}: {e}")
    return DB_CHECK_FAILED


def _row_columns(row):
    def scalar(v):
        return v.iloc[0] if isinstance(v, pd.Series) else v

    return {
        "open": float(scalar(row["Open"])),
        "high": float(scalar(row["High"])),
        "low": float(scalar(row["Low"])),
        "close": float(scalar(row["Close"])),
        "volume": int(scalar(row["Volume"])),
    }


def _ingest(ticker, data):
    with Sender.from_conf(f"tcp::addr={QUESTDB_HOST}:{QUESTDB_ILP_PORT};") as sender:
        for timestamp, row in data.dropna().iterrows():
            sender.row(
                "equity_prices",
                symbols={"ticker": ticker},
                columns=_row_columns(row),
                at=timestamp.to_pydatetime(),
            )
        sender.flush()


def execute_historical_backfill(ticker: str):
    start_date = get_latest_timestamp_db(ticker)
    if start_date is DB_CHECK_FAILED:
        logger.warning(f"Skipping backfill for {ticker} this cycle -- DB check failed.")
        return
    today = datetime.date.today()

    if start_date:
        # A 1-day-old gap is normal (today's close isn't published until markets shut),
        # not a real gap worth spending a yfinance call on.
        if (today - start_date).days <= 1:
            logger.info(f"Ticker {ticker} is up to date. {start_date=} to {today=}")
            return

        logger.info(f"Backfilling {ticker} from {start_date} to {today}")
        try:
            data = yf.download(
                ticker,
                start=start_date.strftime("%Y-%m-%d"),
                end=today.strftime("%Y-%m-%d"),
                interval="1d",
                progress=False,
            )
            if data.empty:
                return
            _ingest(ticker, data)
            logger.info(f"Backfill complete for {ticker}.")
        except Exception as e:
            logger.error(f"Backfill failed for {ticker}: {e}")
    else:
        # Full historical backfill in 5-year chunks going backwards to 1970. yfinance's
        # period="max" is flaky for some exchanges/tickers; bounded start/end requests
        # are reliable, so that's what's used even though it costs more requests.
        logger.info(f"Starting chunked historical backfill for new ticker {ticker}")
        end_date = today
        while True:
            chunk_start = end_date - datetime.timedelta(days=365 * 5)
            if chunk_start.year < 1970:
                chunk_start = datetime.date(1970, 1, 1)

            logger.info(f"Downloading {ticker} chunk from {chunk_start} to {end_date}")
            try:
                data = yf.download(
                    ticker,
                    start=chunk_start.strftime("%Y-%m-%d"),
                    end=end_date.strftime("%Y-%m-%d"),
                    interval="1d",
                    progress=False,
                )
                if data.empty:
                    logger.info(f"No more historical data found for {ticker} before {end_date}.")
                    break

                _ingest(ticker, data)
                logger.info(f"Chunk backfill complete for {ticker} ({chunk_start} to {end_date}).")

                if chunk_start.year <= 1970:
                    break

                end_date = chunk_start
                time.sleep(2)  # brief pause to avoid overusing the yfinance API

            except Exception as e:
                logger.error(f"Chunked backfill failed for {ticker}: {e}")
                break
