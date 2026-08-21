import os
import sys
import time
import threading
import json
import logging
import requests
import yfinance as yf
import pandas as pd
from typing import List
from fastapi import FastAPI, HTTPException, Query, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
import uvicorn

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from shared.backfill import execute_historical_backfill

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
        ) TIMESTAMP(timestamp) PARTITION BY MONTH WAL DEDUPLICATE UPSERT KEYS (ticker, timestamp);
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
        # Short-retention home for the worker's hourly "current price" ticks -- kept
        # separate from equity_prices so intraday rows never mix with full daily history
        # (that mixing is what made resolution=1h ambiguous beyond the last couple of
        # days) and so DAY partitioning here is actually appropriate, since old partitions
        # get dropped continuously instead of accumulating for decades.
        """
        CREATE TABLE IF NOT EXISTS equity_prices_intraday (
            ticker SYMBOL INDEX,
            open DOUBLE,
            high DOUBLE,
            low DOUBLE,
            close DOUBLE,
            volume LONG,
            timestamp TIMESTAMP
        ) TIMESTAMP(timestamp) PARTITION BY DAY WAL DEDUPLICATE UPSERT KEYS (ticker, timestamp);
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
# get_latest_timestamp_db, DB_CHECK_FAILED, and execute_historical_backfill live in
# shared/backfill.py -- this used to be a near-duplicate of worker/main.py's copy, and
# the two had already drifted (different "is this ticker stale" thresholds).

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

    # Auto-track and backfill requested tickers not in DB. This is a multi-ticker overlay
    # query, so it must not validate each ticker synchronously against yfinance here --
    # with a dozen+ never-seen tickers (e.g. a freshly imported portfolio) that serialized
    # network round-trip blew past this endpoint's own timeout before ever reaching
    # QuestDB. execute_historical_backfill already no-ops for an invalid ticker (empty
    # yf.download result), so tracking is safe to do unconditionally in the background.
    tracked = load_tracked_tickers()
    for t in ticker_list:
        if t not in tracked:
            save_tracked_ticker(t)
            background_tasks.add_task(execute_historical_backfill, t)

    ticker_filter = ",".join([f"'{t}'" for t in ticker_list])

    # Resolution picks the SAMPLE BY bucket: the caller (chart) knows its own zoom level
    # and asks for bars sized to it, same as TradingView/Polygon-style bar APIs -- this
    # endpoint just aggregates real OHLC bars at that size rather than the caller having
    # to fetch everything and thin it out client-side.
    sample_unit = {"1d": "1d", "1w": "1w", "1M": "1M"}.get(resolution, "1d")
    query = f"""
    SELECT timestamp, ticker, last(close) as close
    FROM equity_prices
    WHERE ticker IN ({ticker_filter})
    SAMPLE BY {sample_unit} ALIGN TO CALENDAR LIMIT -{limit};
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
def _backfill_all_tracked():
    """Backfill every tracked ticker. Runs off the request/serving path."""
    for t in load_tracked_tickers():
        try:
            execute_historical_backfill(t)
        except Exception as e:
            # One bad ticker must not abort the remaining backfills.
            logger.error(f"Startup backfill failed for {t}: {e}")


@app.on_event("startup")
def startup_event():
    # The schema check is fast and everything else depends on it, so it stays
    # synchronous.
    init_db_schema()

    # The backfill sweep does not. It used to run inline here, once per tracked
    # ticker (34 of them), before Uvicorn would accept a single request -- which
    # is why a restart could appear to hang for minutes whenever QuestDB's
    # staleness checks were slow. The API now comes up immediately and the sweep
    # catches up behind it.
    threading.Thread(target=_backfill_all_tracked, name="startup-backfill", daemon=True).start()


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
