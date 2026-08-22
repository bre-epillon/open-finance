#!/usr/bin/env python3
"""Read-only pre-flight check for the regime & sentiment engine.

Answers the questions IMPLEMENTATION_PLAN.md Stage 0 depends on, none of which
can be determined without touching the live QuestDB:

  * is QuestDB reachable, and which tables exist
  * how badly is macro_indicators duplicated  (plan section 0.1)
  * how much history does each indicator actually have  (plan section 0.2)
  * which of the new series/tickers are missing  (plan section 2.2)
  * do the sentiment-input tickers have enough daily history

Touches nothing. No writes, no DDL. Needs only `requests`.

    python scripts/check_data.py
    python scripts/check_data.py --host localhost --port 9000
"""

import argparse
import sys

import requests

# --- what the engine needs -------------------------------------------------

# Already ingested by open-finance's fred_worker.
EXISTING_INDICATORS = [
    "GDP_Growth",
    "Inflation_CPI",
    "Fed_Funds_Rate",
    "Unemployment",
    "Yield_Curve",
    "M2_Money_Supply",
    "Consumer_Sentiment",
    "Junk_Bond_Spread",
]

# To be added by regime_mapping's worker (plan section 2.2).
NEW_INDICATORS = [
    "Industrial_Production",
    "Nonfarm_Payrolls",
    "Core_CPI",
    "Breakeven_10Y",
    "Real_Yield_10Y",
    "Retail_Sales",
]

# Sentiment inputs already tracked by open-finance's worker.
EXISTING_TICKERS = ["^GSPC", "^VIX", "TLT", "HYG", "LQD"]

# Needed for the tilt display and the breadth/term-structure component.
NEW_TICKERS = ["^VIX3M", "GLD", "DBC", "TIP"]

# A z-score over a 120-month window with min_periods=60 needs at least this
# many monthly observations before it produces anything but NaN.
MIN_MONTHLY_OBS = 60
# pct_rank over a 250-day window with min_periods=60.
MIN_DAILY_OBS = 250


def q(base, query):
    """Run one query. Returns (rows, error_or_None)."""
    try:
        r = requests.get(f"{base}/exec", params={"query": query}, timeout=30)
    except requests.exceptions.RequestException as e:
        return None, f"connection failed: {e}"
    if r.status_code != 200:
        return None, f"HTTP {r.status_code}: {r.text[:200]}"
    body = r.json()
    if "error" in body:
        return None, body["error"]
    return body.get("dataset", []), None


def section(title):
    print(f"\n{'=' * 68}\n{title}\n{'=' * 68}")


def check_tables(base):
    section("1. Connectivity and tables")
    rows, err = q(base, "SHOW TABLES")
    if err:
        print(f"  FAIL  cannot reach QuestDB at {base}\n        {err}")
        print("\n  Is the open-finance stack running?  docker compose ps")
        return None
    names = sorted(r[0] for r in rows)
    print(f"  OK    QuestDB reachable at {base}")
    print(f"        {len(names)} tables: {', '.join(names)}")
    for needed in ("equity_prices", "macro_indicators"):
        mark = "OK   " if needed in names else "FAIL "
        print(f"  {mark} required table `{needed}`")
    for ours in ("regime_history", "sentiment_index"):
        state = "exists already" if ours in names else "not yet created (expected)"
        print(f"  info  `{ours}`: {state}")
    if "sentiment_history" in names:
        print("  warn  `sentiment_history` exists -- left over from the parked "
              "_to_delete/fear_and_greed script, which DROPs it on each run. "
              "We use `sentiment_index` so that can never hit our table.")
    return names


def check_duplication(base):
    section("2. macro_indicators duplication  (plan section 0.1)")
    total, err = q(base, "SELECT count() FROM macro_indicators")
    if err:
        print(f"  FAIL  {err}")
        return
    distinct, err = q(
        base,
        "SELECT count() FROM (SELECT DISTINCT timestamp, indicator FROM macro_indicators)",
    )
    if err:
        print(f"  FAIL  {err}")
        return
    n_total, n_distinct = total[0][0], distinct[0][0]
    print(f"  rows total          : {n_total:>10,}")
    print(f"  distinct (ts, ind)  : {n_distinct:>10,}")
    if n_distinct == 0:
        print("  FAIL  table is empty -- has fred_worker ever run?")
        return
    factor = n_total / n_distinct
    if factor > 1.05:
        print(f"  CONFIRMED  every observation is stored ~{factor:.1f}x over. "
              "fred_worker re-ingests 5y daily into a table with no "
              "DEDUPLICATE UPSERT KEYS. Apply plan 0.1 before trusting any "
              "aggregate over this table.")
    else:
        print("  OK    no meaningful duplication")


def check_indicators(base):
    section("3. Macro indicator coverage  (plan sections 0.2, 2.2)")
    rows, err = q(
        base,
        "SELECT indicator, count(), min(timestamp), max(timestamp), "
        "count_distinct(timestamp) FROM macro_indicators GROUP BY indicator",
    )
    if err:
        print(f"  FAIL  {err}")
        return
    found = {r[0]: r for r in rows}

    print(f"  {'indicator':<24}{'uniq obs':>9}  {'from':<11}{'to':<11} status")
    print(f"  {'-' * 66}")
    for name in EXISTING_INDICATORS + NEW_INDICATORS:
        if name not in found:
            tag = "MISSING (to add, plan 2.2)" if name in NEW_INDICATORS else "MISSING -- unexpected!"
            print(f"  {name:<24}{'-':>9}  {'-':<11}{'-':<11} {tag}")
            continue
        _, _, tmin, tmax, uniq = found[name]
        if uniq >= MIN_MONTHLY_OBS:
            tag = "ok"
        else:
            tag = f"THIN (<{MIN_MONTHLY_OBS} obs -- z-scores will be NaN)"
        print(f"  {name:<24}{uniq:>9,}  {str(tmin)[:10]:<11}{str(tmax)[:10]:<11} {tag}")

    extras = sorted(set(found) - set(EXISTING_INDICATORS) - set(NEW_INDICATORS))
    if extras:
        print(f"\n  info  other indicators present: {', '.join(extras)}")

    print("\n  Note: 'from' dates clustered ~5 years back confirm plan 0.2 -- "
          "fred_worker caps observation_start at today-365*5. Quarterly "
          "GDP_Growth cannot support a z-score on 5 years of data.")


def check_tickers(base):
    section("4. Equity/ETF history for sentiment inputs  (plan section 2.2)")
    rows, err = q(
        base,
        "SELECT ticker, count(), min(timestamp), max(timestamp) "
        "FROM equity_prices GROUP BY ticker",
    )
    if err:
        print(f"  FAIL  {err}")
        return
    found = {r[0]: r for r in rows}

    print(f"  {'ticker':<12}{'bars':>9}  {'from':<11}{'to':<11} status")
    print(f"  {'-' * 58}")
    for t in EXISTING_TICKERS + NEW_TICKERS:
        if t not in found:
            tag = "MISSING (POST /api/track)" if t in NEW_TICKERS else "MISSING -- unexpected!"
            print(f"  {t:<12}{'-':>9}  {'-':<11}{'-':<11} {tag}")
            continue
        _, n, tmin, tmax = found[t]
        tag = "ok" if n >= MIN_DAILY_OBS else f"THIN (<{MIN_DAILY_OBS} bars)"
        print(f"  {t:<12}{n:>9,}  {str(tmin)[:10]:<11}{str(tmax)[:10]:<11} {tag}")

    print(f"\n  info  {len(found)} distinct tickers in equity_prices in total.")

    # Breadth component needs a decent population of tickers with >125 bars.
    deep = [t for t, r in found.items() if r[1] >= 125]
    print(f"  info  {len(deep)} have >=125 bars -- that is the constituent "
          "count available to the breadth component (plan 4.2).")
    if len(deep) < 15:
        print("  warn  <15 usable constituents makes breadth noisy; consider "
              "the ^VIX3M/^VIX term-structure alternative instead.")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="localhost")
    p.add_argument("--port", type=int, default=9000)
    a = p.parse_args()
    base = f"http://{a.host}:{a.port}"

    print("regime_mapping -- data pre-flight check (read-only)")
    if check_tables(base) is None:
        return 1
    check_duplication(base)
    check_indicators(base)
    check_tickers(base)
    section("Done")
    print("  Paste this output back and I'll size Stage 0 against it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
