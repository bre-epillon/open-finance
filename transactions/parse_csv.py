import os
import re
import csv
import glob
import json
import time
import yfinance as yf
import requests
from datetime import datetime
import uuid

# Trade Republic's export puts the ISIN in the "symbol" column, but ISINs don't reliably
# resolve to price data on Yahoo Finance and never match the ticker other apps display.
# Manual pins for cases where the automatic OpenFIGI lookup below ever needs overriding.
# Anything not listed here is resolved automatically; if that also fails, it falls back
# to the ISIN itself, which yfinance can often resolve on its own.
ISIN_TICKER_OVERRIDES = {}

OPENFIGI_URL = "https://api.openfigi.com/v3/mapping"
OPENFIGI_API_KEY = os.getenv("OPENFIGI_API_KEY")  # optional, raises the rate limit

# Bloomberg exchange code -> Yahoo Finance suffix, tried in this priority order.
# GR = Xetra (most liquid, checked first), GF = Frankfurt floor (fallback).
GERMAN_EXCHANGES = [("GR", "DE"), ("GF", "F")]


def _openfigi_lookup(isins):
    """Batch-resolves ISINs to their German-exchange ticker root via OpenFIGI.
    Returns {isin: {exchCode: ticker}}. Never raises -- a failed lookup just means
    those ISINs fall through to the ISIN-as-ticker fallback."""
    results = {}
    headers = {"Content-Type": "application/json"}
    if OPENFIGI_API_KEY:
        headers["X-OPENFIGI-APIKEY"] = OPENFIGI_API_KEY

    # OpenFIGI's documented cap is 100 jobs/request, but that requires an API key --
    # anonymous requests 413 well before that (empirically fine at 10, fails at 15+).
    batch_size = 100 if OPENFIGI_API_KEY else 10

    isins = list(isins)
    for i in range(0, len(isins), batch_size):
        chunk = isins[i:i + batch_size]
        payload = [{"idType": "ID_ISIN", "idValue": isin} for isin in chunk]
        try:
            resp = requests.post(OPENFIGI_URL, json=payload, headers=headers, timeout=20)
            resp.raise_for_status()
            for isin, entry in zip(chunk, resp.json()):
                by_exchange = {}
                for d in entry.get("data", []):
                    by_exchange.setdefault(d["exchCode"], d["ticker"])
                results[isin] = by_exchange
        except Exception as e:
            print(f"OpenFIGI lookup failed for a batch of {len(chunk)} ISINs: {e}")
        if i + batch_size < len(isins):
            time.sleep(2.5)  # stay well under the anonymous rate limit
    return results


def _has_price_data(ticker):
    try:
        return not yf.Ticker(ticker).history(period="5d").empty
    except Exception:
        return False


def build_ticker_map(isins):
    """Resolves each ISIN to the best available ticker: a manual override, then the
    verified Xetra/Frankfurt listing from OpenFIGI, then the ISIN itself."""
    isins = set(isins)
    to_lookup = [isin for isin in isins if isin not in ISIN_TICKER_OVERRIDES]
    figi_data = _openfigi_lookup(to_lookup)

    ticker_map = dict(ISIN_TICKER_OVERRIDES)
    for isin in to_lookup:
        by_exchange = figi_data.get(isin, {})
        resolved = isin
        for exch_code, yahoo_suffix in GERMAN_EXCHANGES:
            root = by_exchange.get(exch_code)
            if not root:
                continue
            candidate = f"{root}.{yahoo_suffix}"
            if _has_price_data(candidate):
                resolved = candidate
                break
        ticker_map[isin] = resolved
    return ticker_map


def find_latest_csv(directory="."):
    """Trade Republic re-exports are named transactions_<start>_<end>.csv each time; pick
    the one with the latest end date so a fresh export is picked up automatically. Falls
    back to the legacy 'Transaction export.csv' if no dated export exists."""
    dated = []
    for path in glob.glob(os.path.join(directory, "transactions_*.csv")):
        m = re.search(r"transactions_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})\.csv$", os.path.basename(path))
        if m:
            dated.append((m.group(2), path))
    if dated:
        return max(dated)[1]
    legacy = os.path.join(directory, "Transaction export.csv")
    return legacy if os.path.exists(legacy) else None


def parse_transactions(csv_path):
    transactions = []
    state_bonds = []
    cash_deposits = []
    interest_payments = []
    failed_imports = set()

    with open(csv_path, mode="r", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))

    trading_rows = [
        r for r in rows
        if r["category"] == "TRADING" and r["type"] in ["BUY", "SELL"] and r["asset_class"] != "BOND"
    ]
    bond_rows = [
        r for r in rows
        if r["category"] == "TRADING" and r["type"] in ["BUY", "SELL"] and r["asset_class"] == "BOND"
    ]
    deposit_rows = [r for r in rows if r["category"] == "CASH" and r["type"] == "CUSTOMER_INBOUND"]
    interest_rows = [r for r in rows if r["category"] == "CASH" and r["type"] == "INTEREST_PAYMENT"]

    state_bonds.extend(bond_rows)

    for row in deposit_rows:
        cash_deposits.append({
            "id": row["transaction_id"] or str(uuid.uuid4()),
            "date": row["date"],
            "amount": float(row["amount"]) if row["amount"] else 0.0,
            "currency": row["currency"],
            "description": row["description"],
        })

    # Bond coupons (asset_class == BOND, tied to an ISIN) and Trade Republic's own
    # interest on idle cash (asset_class empty, no instrument) both come through as
    # CASH/INTEREST_PAYMENT rows -- only the presence of a symbol tells them apart.
    for row in interest_rows:
        is_bond = row["asset_class"] == "BOND"
        amount = float(row["amount"]) if row["amount"] else 0.0
        tax = float(row["tax"]) if row["tax"] else 0.0
        interest_payments.append({
            "id": row["transaction_id"] or str(uuid.uuid4()),
            "date": row["date"],
            "source": "bond" if is_bond else "cash",
            "isin": row["symbol"] if is_bond else None,
            "name": row["name"] if is_bond else None,
            "amount": amount,
            "tax": tax,
            "net_amount": round(amount + tax, 6),
            "currency": row["currency"],
            "description": row["description"],
        })

    ticker_map = build_ticker_map(r["symbol"] for r in trading_rows)

    for row in trading_rows:
        isin = row["symbol"]
        ticker = ticker_map[isin]

        # Check yfinance
        try:
            ticker_data = yf.Ticker(ticker)
            hist = ticker_data.history(period="1d")
            if hist.empty:
                failed_imports.add(ticker)
                continue
        except Exception as e:
            failed_imports.add(ticker)
            continue

        transactions.append({
            "id": row["transaction_id"] or str(uuid.uuid4()),
            "isin": isin,
            "ticker": ticker,
            "name": row["name"],
            "date": row["date"],
            "quantity": float(row["shares"]) if row["shares"] else 0.0,
            "price": float(row["price"]) if row["price"] else 0.0,
            "type": row["type"],
        })

    # Save parsed equity/funds transactions
    with open("parsed_transactions.json", "w") as f:
        json.dump(transactions, f, indent=2)

    # Save state bonds separately
    with open("state_bonds.json", "w") as f:
        json.dump(state_bonds, f, indent=2)

    # Save cash deposits and interest payments (bond coupons + idle-cash interest)
    with open("cash_deposits.json", "w") as f:
        json.dump(cash_deposits, f, indent=2)

    with open("interest_payments.json", "w") as f:
        json.dump(interest_payments, f, indent=2)

    # Write failed imports
    with open("failed_imports.txt", "w") as f:
        for imp in failed_imports:
            f.write(imp + "\n")

    print(f"Successfully parsed {len(transactions)} transactions.")
    print(f"Saved {len(state_bonds)} state bonds separately.")
    print(f"Saved {len(cash_deposits)} cash deposits.")
    bond_interest = sum(1 for p in interest_payments if p["source"] == "bond")
    cash_interest = len(interest_payments) - bond_interest
    print(f"Saved {len(interest_payments)} interest payments ({bond_interest} bond coupons, {cash_interest} cash interest).")
    if failed_imports:
        print(
            f"Failed to import {len(failed_imports)} tickers. They have been saved to failed_imports.txt:"
        )
        for imp in failed_imports:
            print(f"- {imp}")
    else:
        print("No failed imports.")


if __name__ == "__main__":
    csv_path = find_latest_csv()
    if not csv_path:
        raise SystemExit("No transactions CSV found in this directory.")
    print(f"Parsing {csv_path}")
    parse_transactions(csv_path)
