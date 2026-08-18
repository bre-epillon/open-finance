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
FRED_API_KEY = os.getenv("FRED_API_KEY", "05f6f0ba0a0347f8cb544300570ad8de")

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
            # Get data for the last 5 years to ensure we have recent history
            "observation_start": (datetime.date.today() - datetime.timedelta(days=365*5)).strftime("%Y-%m-%d"),
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
                        timestamp = datetime.datetime.strptime(date_str, "%Y-%m-%d")
                        
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