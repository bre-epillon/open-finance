import os
import time
import logging
import datetime
import requests
from questdb.ingress import Sender
from apscheduler.schedulers.background import BlockingScheduler

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

QUESTDB_HOST = os.getenv("QUESTDB_HOST", "questdb")
QUESTDB_ILP_PORT = int(os.getenv("QUESTDB_ILP_PORT", 9009))
# No default. A committed key is what got the old one revoked; a silent
# fallback default is worse than a crash, because the worker would keep
# "succeeding" against a dead key and quietly stop updating the macro tables.
FRED_API_KEY = os.getenv("FRED_API_KEY")
if not FRED_API_KEY:
    raise SystemExit("FRED_API_KEY is not set -- put it in .env (see patches/README.md)")

# FRED returns the full series in a single call and the payload is a few
# hundred KB, so there is no reason to truncate. The previous 5-year window
# made every trailing z-score unusable: quarterly real GDP had ~20
# observations, which cannot support a percentile or a standard deviation.
# Safe only once macro_indicators has DEDUPLICATE UPSERT KEYS(timestamp,
# indicator) -- see patches/0003-macro-dedup.sql -- otherwise the nightly
# re-ingest appends 65 years of rows instead of upserting them.
# 1970, not 1960: QuestDB's ILP protocol rejects a negative designated
# timestamp, and a pre-epoch row aborts the entire series rather than being
# skipped. regime_mapping's worker hit exactly this at 1960 --
#   "Timestamp -315619200000000000 is negative. It must be >= 0"
# -- and here it would silently drop CPIAUCSL (from 1947), UNRATE (1948),
# FEDFUNDS (1954) and M2SL (1959), which is four of the eight series. 1970
# still leaves 55 years, far more than a 120-month trailing z-score needs.
EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
OBSERVATION_START = "1970-01-01"

MACRO_INDICATORS = {
    'GDP_Growth': 'A191RL1Q225SBEA', # Real GDP % Change
    'Inflation_CPI': 'CPIAUCSL',      # Consumer Price Index
    'Fed_Funds_Rate': 'FEDFUNDS',    # Central Bank Policy Rate
    'Unemployment': 'UNRATE',        # Labor Market Health
    'Yield_Curve': 'T10Y2Y',          # 10Y minus 2Y Treasury
    'M2_Money_Supply': 'M2SL',       # M2 Money Supply
    'Consumer_Sentiment': 'UMCSENT',  # University of Michigan: Consumer Sentiment
    'Junk_Bond_Spread': 'BAMLH0A0HYM2' # High Yield Index Option-Adjusted Spread
}

def fetch_and_ingest_fred_data():
    logger.info("Starting FRED data ingestion...")
    
    for name, series_id in MACRO_INDICATORS.items():
        url = f"https://api.stlouisfed.org/fred/series/observations"
        params = {
            "series_id": series_id,
            "api_key": FRED_API_KEY,
            "file_type": "json",
            "observation_start": OBSERVATION_START,
            "sort_order": "asc"
        }
        
        try:
            logger.info(f"Fetching data for {name} ({series_id})...")
            response = requests.get(url, params=params, timeout=15)
            if response.status_code == 200:
                data = response.json()
                observations = data.get("observations", [])
                
                if not observations:
                    logger.warning(f"No observations found for {name}.")
                    continue
                
                with Sender.from_conf(f"tcp::addr={QUESTDB_HOST}:{QUESTDB_ILP_PORT};") as sender:
                    valid_count = 0
                    for obs in observations:
                        value_str = obs.get("value")
                        date_str = obs.get("date")
                        
                        # Some values might be "." indicating missing data
                        if value_str == "." or not value_str:
                            continue
                            
                        value = float(value_str)
                        # Timezone-aware, so questdb 4.x does not warn about a
                        # naive datetime; FRED dates are UTC days.
                        timestamp = datetime.datetime.strptime(
                            date_str, "%Y-%m-%d").replace(tzinfo=datetime.timezone.utc)
                        # See EPOCH above. OBSERVATION_START already prevents
                        # this; the guard keeps one bad row from aborting the
                        # whole series if that constant is widened again.
                        if timestamp < EPOCH:
                            continue

                        sender.row(
                            'macro_indicators',
                            symbols={'indicator': name, 'series_id': series_id},
                            columns={'value': value},
                            at=timestamp
                        )
                        valid_count += 1
                    sender.flush()
                logger.info(f"Successfully ingested {valid_count} records for {name}.")
            else:
                logger.error(f"FRED API error for {name}: {response.status_code} - {response.text}")
        except Exception as e:
            logger.error(f"Failed to fetch or ingest data for {name}: {e}")
            
        # Small delay to respect rate limits (FRED allows 120 req/min)
        time.sleep(1)
        
    logger.info("FRED data ingestion complete.")

if __name__ == "__main__":
    logger.info("FRED Worker starting up...")
    
    # Wait briefly for QuestDB to be ready
    time.sleep(5)
    
    # Perform initial sync
    fetch_and_ingest_fred_data()

    scheduler = BlockingScheduler()
    # Macro data updates infrequently (monthly/quarterly/weekly). Once a day is more than enough.
    scheduler.add_job(fetch_and_ingest_fred_data, 'cron', hour='1', minute='30')
    
    logger.info("FRED Worker scheduler active.")
    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        pass