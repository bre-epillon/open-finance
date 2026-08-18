import os
import logging
import datetime
import requests
import yfinance as yf

logger = logging.getLogger(__name__)

QUESTDB_HOST = os.getenv("QUESTDB_HOST", "questdb")
QUESTDB_REST_PORT = int(os.getenv("QUESTDB_REST_PORT", 9000))

ACTIONS_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS corporate_actions (
    ticker SYMBOL,
    action_type SYMBOL,
    effective_date TIMESTAMP,
    ratio DOUBLE,
    status SYMBOL,
    applied_at TIMESTAMP
) TIMESTAMP(applied_at) PARTITION BY MONTH WAL;
"""


def _exec(query: str, timeout: int = 30):
    url = f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}/exec"
    response = requests.get(url, params={"query": query}, timeout=timeout)
    result = response.json()
    if "error" in result:
        raise RuntimeError(result["error"])
    return result


def ensure_schema():
    _exec(ACTIONS_TABLE_SQL)


def _has_price_history(ticker: str) -> bool:
    result = _exec(f"SELECT count() FROM equity_prices WHERE ticker = '{ticker}'")
    dataset = result.get("dataset")
    return bool(dataset) and dataset[0][0] > 0


def _known_split_dates(ticker: str) -> set:
    result = _exec(
        f"SELECT effective_date FROM corporate_actions "
        f"WHERE ticker = '{ticker}' AND action_type = 'SPLIT'"
    )
    return {row[0][:10] for row in result.get("dataset", [])}


def _record_action(ticker: str, effective_date: datetime.date, ratio: float, status: str):
    now = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S.%fZ")
    eff = effective_date.strftime("%Y-%m-%dT00:00:00.000000Z")
    _exec(
        "INSERT INTO corporate_actions (ticker, action_type, effective_date, ratio, status, applied_at) "
        f"VALUES ('{ticker}', 'SPLIT', '{eff}', {ratio}, '{status}', '{now}')"
    )


def _apply_retroactive_split(ticker: str, effective_date: datetime.date, ratio: float):
    eff = effective_date.strftime("%Y-%m-%dT00:00:00.000000Z")
    _exec(
        "UPDATE equity_prices SET "
        f"open = open / {ratio}, high = high / {ratio}, low = low / {ratio}, close = close / {ratio}, "
        f"volume = cast(volume * {ratio} as long) "
        f"WHERE ticker = '{ticker}' AND timestamp < '{eff}'"
    )


def check_and_apply_splits(ticker: str):
    """
    Splits come straight from Yahoo Finance's own corporate-actions feed (yf.Ticker.splits) --
    no manual news-watching required. The first time a ticker is checked, any split it already
    carries is only logged as a BASELINE: a full historical backfill downloads via yfinance's
    auto_adjust, which already back-adjusts the whole series for every split known at download
    time, so nothing needs rescaling yet. Only a split discovered on a *later* check --
    i.e. one that happened after the ticker's history was already sitting in QuestDB --
    triggers an actual retroactive rescale, which is what prevents double-adjustment.
    """
    if not _has_price_history(ticker):
        return

    try:
        splits = yf.Ticker(ticker).splits
    except Exception as e:
        logger.warning(f"Could not fetch split history for {ticker}: {e}")
        return

    if splits.empty:
        return

    known = _known_split_dates(ticker)
    is_baseline_pass = len(known) == 0

    for ts, ratio in splits.items():
        eff_date = ts.date()
        eff_date_str = eff_date.isoformat()
        if eff_date_str in known:
            continue

        ratio = float(ratio)
        if ratio <= 0 or ratio == 1.0:
            continue

        if is_baseline_pass:
            _record_action(ticker, eff_date, ratio, "BASELINE")
            logger.info(
                f"Baselined pre-existing split for {ticker}: {ratio}x effective {eff_date_str} "
                "(already reflected by yfinance's own adjustment, no rescale needed)."
            )
        else:
            try:
                _apply_retroactive_split(ticker, eff_date, ratio)
                _record_action(ticker, eff_date, ratio, "APPLIED")
                logger.info(
                    f"Applied retroactive split correction for {ticker}: {ratio}x effective {eff_date_str}."
                )
            except Exception as e:
                logger.error(f"Failed to apply split correction for {ticker} ({eff_date_str}): {e}")


def check_all(tickers):
    try:
        ensure_schema()
    except Exception as e:
        logger.error(f"Could not ensure corporate_actions schema, skipping this cycle: {e}")
        return
    for ticker in tickers:
        try:
            check_and_apply_splits(ticker)
        except Exception as e:
            logger.error(f"Corporate action check failed for {ticker}: {e}")
