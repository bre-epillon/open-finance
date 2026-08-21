#!/usr/bin/env python3
import os
import requests
import datetime
import pandas as pd
import numpy as np
from questdb.ingress import Sender

QUESTDB_HOST = os.getenv("QUESTDB_HOST", "localhost")
QUESTDB_REST_PORT = 9000
QUESTDB_ILP_PORT = 9009

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

def normalize_series(series, min_series, max_series, invert=False):
    # Normalize a whole series
    denom = max_series - min_series
    # Avoid division by zero
    denom = denom.replace(0, np.nan)
    score = ((series - min_series) / denom) * 100
    score = score.clip(lower=0, upper=100)
    if invert:
        score = 100 - score
    return score.fillna(50.0)

def main():
    print("Fetching historical data from QuestDB...")
    query_equity = """
    SELECT timestamp, ticker, close
    FROM equity_prices
    WHERE ticker IN ('^GSPC', '^VIX', 'TLT')
    """
    df_eq = fetch_questdb_data(query_equity)
    
    query_macro = """
    SELECT timestamp, indicator, value
    FROM macro_indicators
    WHERE indicator = 'Junk_Bond_Spread'
    """
    df_macro = fetch_questdb_data(query_macro)
    
    if df_eq.empty:
        print("No equity data found.")
        return

    df_eq_pivot = df_eq.pivot(columns='ticker', values='close').ffill().resample('D').last().ffill()
    
    components_df = pd.DataFrame(index=df_eq_pivot.index)
    
    # Momentum
    if '^GSPC' in df_eq_pivot:
        gspc = df_eq_pivot['^GSPC']
        ma125 = gspc.rolling(window=125).mean()
        momentum = ((gspc - ma125) / ma125)
        components_df['momentum'] = normalize_series(momentum, momentum.rolling(250).min(), momentum.rolling(250).max())
    else:
        components_df['momentum'] = 50.0
        
    # Volatility
    if '^VIX' in df_eq_pivot:
        vix = df_eq_pivot['^VIX']
        ma50 = vix.rolling(window=50).mean()
        volatility = vix - ma50
        components_df['volatility'] = normalize_series(volatility, volatility.rolling(250).min(), volatility.rolling(250).max(), invert=True)
    else:
        components_df['volatility'] = 50.0
        
    # Safe Haven Demand
    if '^GSPC' in df_eq_pivot and 'TLT' in df_eq_pivot:
        safe_haven = df_eq_pivot['^GSPC'].pct_change(periods=20) - df_eq_pivot['TLT'].pct_change(periods=20)
        components_df['safe_haven'] = normalize_series(safe_haven, safe_haven.rolling(250).min(), safe_haven.rolling(250).max())
    else:
        components_df['safe_haven'] = 50.0
        
    # Put/Call Ratio Proxy
    if '^VIX' in df_eq_pivot:
        vix_proxy = df_eq_pivot['^VIX']
        components_df['put_call'] = normalize_series(vix_proxy, vix_proxy.rolling(250).min(), vix_proxy.rolling(250).max(), invert=True)
    else:
        components_df['put_call'] = 50.0

    # Junk Bond Demand
    if not df_macro.empty:
        df_mac_pivot = df_macro.pivot(columns='indicator', values='value').ffill().resample('D').last().ffill()
        # align macro index with equity index
        components_df = components_df.join(df_mac_pivot, how='left').ffill()
        if 'Junk_Bond_Spread' in components_df:
            junk = components_df['Junk_Bond_Spread']
            components_df['junk_bond'] = normalize_series(junk, junk.rolling(250).min(), junk.rolling(250).max(), invert=True)
        else:
            components_df['junk_bond'] = 50.0
    else:
        components_df['junk_bond'] = 50.0
        
    # Composite Score
    valid_cols = ['momentum', 'volatility', 'safe_haven', 'junk_bond', 'put_call']
    # ensure all cols exist
    for col in valid_cols:
        if col not in components_df.columns:
            components_df[col] = 50.0
            
    components_df['composite'] = components_df[valid_cols].mean(axis=1)
    
    # Drop NAs
    components_df = components_df.dropna(subset=['composite'])
    
    if components_df.empty:
        print("No valid scores to compute.")
        return
        
    print(f"Calculated {len(components_df)} historical sentiment records. Dropping old table...")
    
    # Drop the existing table to do a full replace
    requests.get(f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exec", params={'query': 'DROP TABLE IF EXISTS sentiment_history'})
    
    print("Ingesting historical sentiment to QuestDB...")
    with Sender.from_conf(f"tcp::addr={QUESTDB_HOST}:{QUESTDB_ILP_PORT};") as sender:
        for timestamp, row in components_df.iterrows():
            sender.row(
                'sentiment_history',
                columns={
                    'momentum': float(row['momentum']),
                    'volatility': float(row['volatility']),
                    'safe_haven': float(row['safe_haven']),
                    'junk_bond': float(row['junk_bond']),
                    'put_call': float(row['put_call']),
                    'composite': float(row['composite'])
                },
                at=timestamp.to_pydatetime()
            )
        sender.flush()
        
    print("Historical sentiment ingestion complete!")

if __name__ == "__main__":
    main()