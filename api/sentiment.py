import os
import requests
import datetime
import pandas as pd
import numpy as np

QUESTDB_HOST = os.getenv("QUESTDB_HOST", "questdb")
QUESTDB_REST_PORT = int(os.getenv("QUESTDB_REST_PORT", 9000))

def fetch_questdb_data(query: str):
    url = f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exec"
    response = requests.get(url, params={'query': query})
    if response.status_code == 200:
        data = response.json()
        if 'dataset' in data:
            columns = [c['name'] for c in data['columns']]
            df = pd.DataFrame(data['dataset'], columns=columns)
            if 'timestamp' in df.columns:
                df['timestamp'] = pd.to_datetime(df['timestamp'])
                df.set_index('timestamp', inplace=True)
                df.sort_index(inplace=True)
            return df
    return pd.DataFrame()

def normalize_score(value, min_val, max_val, invert=False):
    """Normalize value to a 0-100 scale."""
    if pd.isna(value) or pd.isna(min_val) or pd.isna(max_val) or max_val == min_val:
        return 50.0
    score = ((value - min_val) / (max_val - min_val)) * 100
    score = max(0, min(100, score))
    if invert:
        score = 100 - score
    return float(score)

def calculate_fear_and_greed():
    query = """
    SELECT timestamp, momentum, volatility, safe_haven, junk_bond, put_call, composite
    FROM sentiment_history
    ORDER BY timestamp ASC
    """
    df = fetch_questdb_data(query)
    
    if df.empty:
        # Fallback to neutrals if no data
        return {
            "current_score": 50.0,
            "sentiment_label": "Neutral",
            "timestamp": datetime.datetime.utcnow().isoformat() + "Z",
            "sub_components": {
                "momentum": 50.0,
                "volatility": 50.0,
                "safe_haven": 50.0,
                "junk_bond": 50.0,
                "put_call": 50.0
            },
            "historical_series": []
        }
    
    # Get latest row
    latest = df.iloc[-1]
    
    components = {
        "momentum": float(latest['momentum']),
        "volatility": float(latest['volatility']),
        "safe_haven": float(latest['safe_haven']),
        "junk_bond": float(latest['junk_bond']),
        "put_call": float(latest['put_call'])
    }
    current_score = float(latest['composite'])
    
    # Generate historical series for chart
    # To avoid returning 20k rows, let's limit to the last year (250 trading days roughly)
    df_recent = df.tail(250)
    
    hist_series = []
    for idx, row in df_recent.iterrows():
        hist_series.append({
            "date": idx.strftime("%Y-%m-%d"),
            "score": float(row['composite']),
            "momentum": float(row['momentum']),
            "volatility": float(row['volatility']),
            "safe_haven": float(row['safe_haven']),
            "junk_bond": float(row['junk_bond']),
            "put_call": float(row['put_call'])
        })
        
    def get_sentiment_label(score):
        if score < 25: return "Extreme Fear"
        elif score < 50: return "Fear"
        elif score <= 54: return "Neutral"
        elif score < 75: return "Greed"
        else: return "Extreme Greed"
        
    return {
        "current_score": current_score,
        "sentiment_label": get_sentiment_label(current_score),
        "timestamp": latest.name.isoformat() + "Z",
        "sub_components": components,
        "historical_series": hist_series
    }