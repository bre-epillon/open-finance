import os
import time
import json
import logging
import datetime
import requests
import yfinance as yf
import pandas as pd
from typing import List
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from questdb.ingress import Sender
import uvicorn

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

QUESTDB_HOST = os.getenv("QUESTDB_HOST", "localhost")
QUESTDB_ILP_PORT = int(os.getenv("QUESTDB_ILP_PORT", 9009))
QUESTDB_REST_PORT = int(os.getenv("QUESTDB_REST_PORT", 9000))
TICKERS_FILE = "tickers.json"

app = FastAPI(
    title="LiteFi Data API",
    description="Microsecond time-series financial ingestion engine",
)

# Allow the local frontend to communicate with this API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# --- DATABASE INITIALIZATION ---
def init_db_schema():
    """Automatically creates the required tables if they don't exist."""
    url = f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exec"
    queries = [
        """
        CREATE TABLE IF NOT EXISTS equity_prices (
            ticker SYMBOL INDEX,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume LONG,
            timestamp TIMESTAMP
        ) TIMESTAMP(timestamp) PARTITION BY DAY WAL DEDUPLICATE UPSERT KEYS (ticker, timestamp);
        """,
        """
        CREATE TABLE IF NOT EXISTS corporate_actions (
            ticker SYMBOL,
            action_type SYMBOL,
            effective_date TIMESTAMP,
            ratio DOUBLE,
            status SYMBOL,
            applied_at TIMESTAMP
        ) TIMESTAMP(applied_at) PARTITION BY MONTH WAL;
        """,
    ]
    for q in queries:
        max_retries = 15
        for attempt in range(max_retries):
            try:
                response = requests.get(url, params={"query": q}, timeout=10)
                if response.status_code == 200:
                    logger.info("Database schema validated.")
                    break
                else:
                    logger.error(f"Schema error: {response.text}")
                    break
            except requests.exceptions.RequestException as e:
                logger.warning(
                    f"Waiting for QuestDB to start (attempt {attempt + 1}/{max_retries})..."
                )
                time.sleep(2)
        else:
            logger.error("Failed to connect to QuestDB after multiple retries.")


# --- TICKER TRACKING ---
def load_tracked_tickers() -> List[str]:
    if not os.path.exists(TICKERS_FILE):
        default_tickers = ["SPY", "AAPL", "MSFT"]
        with open(TICKERS_FILE, "w") as f:
            json.dump(default_tickers, f)
        return default_tickers
    with open(TICKERS_FILE, "r") as f:
        return json.load(f)


def save_tracked_ticker(ticker: str):
    tickers = load_tracked_tickers()
    if ticker not in tickers:
        tickers.append(ticker)
        with open(TICKERS_FILE, "w") as f:
            json.dump(tickers, f)


# --- INGESTION LOGIC ---
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


def execute_historical_backfill(ticker: str):
    start_date = get_latest_timestamp_db(ticker)
    if start_date is DB_CHECK_FAILED:
        logger.warning(f"Skipping backfill for {ticker} this cycle -- DB check failed.")
        return
    today = datetime.date.today()

    if start_date:
        if (today - start_date).days == 0:
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

            with Sender.from_conf(
                f"tcp::addr={QUESTDB_HOST}:{QUESTDB_ILP_PORT};"
            ) as sender:
                for timestamp, row in data.dropna().iterrows():
                    sender.row(
                        "equity_prices",
                        symbols={"ticker": ticker},
                        columns={
                            "open": float(
                                row["Open"].iloc[0]
                                if isinstance(row["Open"], pd.Series)
                                else row["Open"]
                            ),
                            "high": float(
                                row["High"].iloc[0]
                                if isinstance(row["High"], pd.Series)
                                else row["High"]
                            ),
                            "low": float(
                                row["Low"].iloc[0]
                                if isinstance(row["Low"], pd.Series)
                                else row["Low"]
                            ),
                            "close": float(
                                row["Close"].iloc[0]
                                if isinstance(row["Close"], pd.Series)
                                else row["Close"]
                            ),
                            "volume": int(
                                row["Volume"].iloc[0]
                                if isinstance(row["Volume"], pd.Series)
                                else row["Volume"]
                            ),
                        },
                        at=timestamp.to_pydatetime(),
                    )
                sender.flush()
            logger.info(f"Backfill complete for {ticker}.")
        except Exception as e:
            logger.error(f"Backfill failed for {ticker}: {e}")
    else:
        # Full historical backfill in chunks going backwards
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
                    logger.info(
                        f"No more historical data found for {ticker} before {end_date}."
                    )
                    break

                with Sender.from_conf(
                    f"tcp::addr={QUESTDB_HOST}:{QUESTDB_ILP_PORT};"
                ) as sender:
                    for timestamp, row in data.dropna().iterrows():
                        sender.row(
                            "equity_prices",
                            symbols={"ticker": ticker},
                            columns={
                                "open": float(
                                    row["Open"].iloc[0]
                                    if isinstance(row["Open"], pd.Series)
                                    else row["Open"]
                                ),
                                "high": float(
                                    row["High"].iloc[0]
                                    if isinstance(row["High"], pd.Series)
                                    else row["High"]
                                ),
                                "low": float(
                                    row["Low"].iloc[0]
                                    if isinstance(row["Low"], pd.Series)
                                    else row["Low"]
                                ),
                                "close": float(
                                    row["Close"].iloc[0]
                                    if isinstance(row["Close"], pd.Series)
                                    else row["Close"]
                                ),
                                "volume": int(
                                    row["Volume"].iloc[0]
                                    if isinstance(row["Volume"], pd.Series)
                                    else row["Volume"]
                                ),
                            },
                            at=timestamp.to_pydatetime(),
                        )
                    sender.flush()
                logger.info(
                    f"Chunk backfill complete for {ticker} ({chunk_start} to {end_date})."
                )

                if chunk_start.year <= 1970:
                    break

                end_date = chunk_start
                time.sleep(2)  # brief pause to avoid overusing the yfinance API

            except Exception as e:
                logger.error(f"Chunked backfill failed for {ticker}: {e}")
                break


from sentiment import calculate_fear_and_greed

@app.get("/api/v1/sentiment/fear-and-greed")
def get_fear_and_greed():
    try:
        return calculate_fear_and_greed()
    except Exception as e:
        logger.error(f"Error calculating fear and greed: {e}")
        raise HTTPException(status_code=500, detail="Internal server error calculating sentiment.")

# --- API ENDPOINTS ---
@app.get("/api/tickers")
def get_tickers():
    return load_tracked_tickers()


@app.get("/api/latest_prices")
def get_latest_prices(tickers: str = Query(...)):
    ticker_list = [t.strip().upper() for t in tickers.split(",")]
    try:
        data = yf.download(ticker_list, period="1d", progress=False)
        if data.empty:
            raise HTTPException(status_code=404, detail="No price data found.")

        prices = {}
        if len(ticker_list) == 1:
            prices[ticker_list[0]] = float(
                data["Close"].iloc[-1].item()
                if isinstance(data["Close"].iloc[-1], pd.Series)
                else data["Close"].iloc[-1]
            )
        else:
            for t in ticker_list:
                if t in data["Close"] and not pd.isna(data["Close"][t].iloc[-1]):
                    prices[t] = float(
                        data["Close"][t].iloc[-1].item()
                        if isinstance(data["Close"][t].iloc[-1], pd.Series)
                        else data["Close"][t].iloc[-1]
                    )
        return prices
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to fetch latest prices: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/data")
def get_financial_data(
    background_tasks: BackgroundTasks,
    tickers: str = Query(...),
    limit: int = 100,
    resolution: str = "1d",
):
    # Accepts comma separated tickers e.g., ?tickers=AAPL,SPY
    ticker_list = [t.strip().upper() for t in tickers.split(",")]

    # Auto-track and backfill requested tickers not in DB
    tracked = load_tracked_tickers()
    for t in ticker_list:
        if t not in tracked:
            try:
                # Basic validation that it's a real ticker
                if yf.Ticker(t).history(period="1d").empty:
                    raise HTTPException(
                        status_code=404, detail=f"Ticker {t} not found on yfinance."
                    )
                save_tracked_ticker(t)
                background_tasks.add_task(execute_historical_backfill, t)
            except HTTPException:
                raise
            except Exception as e:
                logger.error(f"Failed to auto-track {t}: {e}")
                raise HTTPException(
                    status_code=404, detail=f"Ticker {t} not found or invalid."
                )

    ticker_filter = ",".join([f"'{t}'" for t in ticker_list])

    sample_clause = "SAMPLE BY 1d" if resolution == "1d" else "SAMPLE BY 1h"
    query = f"""
    SELECT timestamp, ticker, last(close) as close
    FROM equity_prices 
    WHERE ticker IN ({ticker_filter}) 
    {sample_clause} ALIGN TO CALENDAR LIMIT -{limit};
    """

    try:
        response = requests.get(
            f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exec", params={"query": query}
        )
        db_result = response.json()
        if "error" in db_result:
            raise HTTPException(status_code=400, detail=db_result["error"])
        columns = [col["name"] for col in db_result.get("columns", [])]
        records = [dict(zip(columns, row)) for row in db_result.get("dataset", [])]
        return {"data": records}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/corporate_actions")
def get_corporate_actions(ticker: str = Query(None)):
    filter_clause = f"WHERE ticker = '{ticker.upper()}'" if ticker else ""
    query = (
        "SELECT ticker, action_type, effective_date, ratio, status, applied_at "
        f"FROM corporate_actions {filter_clause} ORDER BY applied_at DESC"
    )
    try:
        response = requests.get(
            f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exec", params={"query": query}
        )
        db_result = response.json()
        if "error" in db_result:
            raise HTTPException(status_code=400, detail=db_result["error"])
        columns = [col["name"] for col in db_result.get("columns", [])]
        records = [dict(zip(columns, row)) for row in db_result.get("dataset", [])]
        return {"data": records}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/track")
def track_new_ticker(ticker: str, background_tasks: BackgroundTasks):
    ticker_upper = ticker.upper().strip()

    if ticker_upper in load_tracked_tickers():
        return {"status": "already_tracked"}

    try:
        if yf.Ticker(ticker_upper).history(period="1d").empty:
            raise HTTPException(
                status_code=404, detail=f"Ticker {ticker_upper} not found on yfinance."
            )
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to validate {ticker_upper}: {e}")
        raise HTTPException(
            status_code=404, detail=f"Ticker {ticker_upper} not found or invalid."
        )

    save_tracked_ticker(ticker_upper)
    background_tasks.add_task(execute_historical_backfill, ticker_upper)
    return {
        "status": "accepted",
        "message": f"Backfilling {ticker_upper} in background.",
    }


# --- LIFECYCLE ---
@app.on_event("startup")
def startup_event():
    # 1. Init Database Schema
    init_db_schema()

    # 2. Trigger initial backfill for existing tickers
    for t in load_tracked_tickers():
        execute_historical_backfill(t)


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
