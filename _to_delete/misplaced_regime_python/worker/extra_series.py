"""Ingest the FRED series open-finance's fred_worker does not cover.

Writes new `indicator` symbols into the existing macro_indicators table. This
is an additive shared write: the eight symbols fred_worker owns are never
touched, and QuestDB's symbol column makes adding new ones free.

Incremental by design. fred_worker re-fetches its whole observation window
every night, which is why macro_indicators now holds every observation many
times over (see patches/0003-macro-dedup.sql). This worker asks the database
what it already has and fetches only from shortly before that point -- so it
stays correct whether or not the dedup patch has been applied, and picks up
FRED's back-revisions either way.
"""

import datetime
import logging

import requests
from questdb.ingress import Sender

from core.config import FRED_API_KEY, ILP_CONF, MACRO_TABLE
from core.db.rest import QueryError, query
from core.series import MacroSeries, ours_to_ingest

logger = logging.getLogger(__name__)

FRED_URL = "https://api.stlouisfed.org/fred/series/observations"
HISTORY_START = "1960-01-01"

# How far back to re-fetch on an incremental run. FRED revises recent
# observations for months after first publication -- payrolls and industrial
# production routinely -- so a window that only covers "since the last row"
# would ingest the first print and never the correction.
REVISION_WINDOW_DAYS = 400

# FRED allows 120 requests/minute. Six series is nowhere near that; the pause
# is politeness, not necessity.
REQUEST_PAUSE_SECONDS = 1


def _start_date(indicator: str) -> str:
    """Where to resume from for one indicator."""
    try:
        df = query(f"SELECT max(timestamp) AS last FROM {MACRO_TABLE} "
                   f"WHERE indicator = '{indicator}'")
    except QueryError as e:
        # Distinct from "no rows": a transient DB failure must not trigger a
        # full 65-year re-fetch. Same reasoning as open-finance's
        # DB_CHECK_FAILED sentinel in shared/backfill.py.
        logger.warning("Cannot read last timestamp for %s (%s); skipping this "
                       "cycle rather than re-fetching all history", indicator, e)
        return ""
    if df.empty or df["last"].isna().all():
        logger.info("%s has no rows yet -- fetching from %s",
                    indicator, HISTORY_START)
        return HISTORY_START
    last = df["last"].iloc[0].date()
    start = last - datetime.timedelta(days=REVISION_WINDOW_DAYS)
    logger.info("%s is current to %s -- fetching from %s", indicator, last, start)
    return start.isoformat()


def fetch(spec: MacroSeries, start: str) -> list[tuple[datetime.datetime, float]]:
    """FRED observations for one series, missing values dropped."""
    params = {
        "series_id": spec.fred_id,
        "api_key": FRED_API_KEY,
        "file_type": "json",
        "observation_start": start,
        "sort_order": "asc",
    }
    r = requests.get(FRED_URL, params=params, timeout=30)
    if r.status_code != 200:
        raise RuntimeError(f"FRED {spec.fred_id}: HTTP {r.status_code} "
                           f"{r.text[:200]}")

    out = []
    for obs in r.json().get("observations", []):
        value, date = obs.get("value"), obs.get("date")
        # FRED marks a missing observation with a literal ".".
        if not value or value == "." or not date:
            continue
        out.append((datetime.datetime.strptime(date, "%Y-%m-%d"), float(value)))
    return out


def ingest(spec: MacroSeries, rows) -> int:
    """Write one series' observations. One Sender, one flush."""
    if not rows:
        return 0
    with Sender.from_conf(ILP_CONF) as sender:
        for ts, value in rows:
            sender.row(MACRO_TABLE,
                       symbols={"indicator": spec.name,
                                "series_id": spec.fred_id},
                       columns={"value": value},
                       at=ts)
        sender.flush()
    return len(rows)


def run_once() -> dict[str, int]:
    """Ingest every series this project owns. Returns name -> rows written."""
    if not FRED_API_KEY:
        raise SystemExit("FRED_API_KEY is not set -- see .env.example")

    import time
    written = {}
    for spec in ours_to_ingest():
        start = _start_date(spec.name)
        if not start:
            continue
        try:
            rows = fetch(spec, start)
            written[spec.name] = ingest(spec, rows)
            logger.info("Ingested %d rows for %s (%s)",
                        written[spec.name], spec.name, spec.fred_id)
        except Exception as e:
            # One bad series must not abort the rest, exactly as
            # open-finance's startup backfill sweep handles a bad ticker.
            logger.error("Failed to ingest %s (%s): %s",
                         spec.name, spec.fred_id, e)
        time.sleep(REQUEST_PAUSE_SECONDS)
    return written
