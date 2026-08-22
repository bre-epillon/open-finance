-- SUPERSEDED 2026-08-22 by 0003b-macro-rebuild.sql. RUN THAT INSTEAD.
--
-- Two things this script got wrong:
--   * It treats duplication as the problem. The bigger problem is that the
--     table is PARTITION BY DAY -- 8,573 daily partitions, and an O3 merge
--     rewriting 8,354 of them. That is what makes reads here appear to hang.
--   * Statement 2 below, `SELECT count() FROM (SELECT DISTINCT ...)`, is a
--     pathological shape for QuestDB and is the statement that blocked. Use
--     the per-indicator GROUP BY in 0003b step 1 instead.
--
-- Kept for the record of the diagnosis. Do not run.
--
-- 0003 — macro_indicators: stop duplicating every row daily
--
-- RUN ONE STATEMENT AT A TIME in the QuestDB console (http://localhost:9000).
-- There is a DROP TABLE at step 5; step 4 is the check that makes it safe.
-- Stop fred_worker first:  docker compose stop fred_worker

-- ---------------------------------------------------------------------------
-- 1. Measure the damage. If total / distinct is ~1.0 you can stop here.
-- ---------------------------------------------------------------------------
SELECT count() AS rows_total FROM macro_indicators;

SELECT count() AS rows_distinct
FROM (SELECT DISTINCT timestamp, indicator FROM macro_indicators);

SELECT indicator, count() AS rows, count_distinct(timestamp) AS uniq_ts,
       min(timestamp) AS first_obs, max(timestamp) AS last_obs
FROM macro_indicators
GROUP BY indicator
ORDER BY indicator;

-- ---------------------------------------------------------------------------
-- 2. Enable deduplication for FUTURE writes.
--
-- This is worth doing even on its own: from here on, fred_worker's nightly
-- re-ingest becomes an idempotent upsert instead of an append. It does NOT
-- retroactively collapse the rows already there — steps 3-6 do that.
--
-- Requires a WAL table. ILP-created tables are WAL by default; if this errors
-- with "table is not a WAL table", skip to step 3 (the rebuilt table gets the
-- keys at CREATE time anyway).
-- ---------------------------------------------------------------------------
ALTER TABLE macro_indicators DEDUPLICATE UPSERT KEYS(timestamp, indicator);

-- ---------------------------------------------------------------------------
-- 3. Rebuild the historical rows into a clean table.
--
-- PARTITION BY YEAR, not MONTH: this table holds ~8-14 low-frequency series
-- over 65 years. MONTH partitioning would create ~780 near-empty partitions,
-- which is the same partition-count problem BACKLOG.md records for
-- equity_prices (11,513 partitions, and QuestDB crashing under it).
--
-- The GROUP BY is what collapses the duplicates. max(value) over an identical
-- (timestamp, indicator) group is just that value; where FRED has revised a
-- figure it takes the larger, which is arbitrary but only reachable if the
-- revision was ingested under the same reference timestamp — and step 2 makes
-- future revisions a clean upsert instead.
-- ---------------------------------------------------------------------------
CREATE TABLE macro_clean (
    indicator SYMBOL INDEX,
    series_id SYMBOL,
    value DOUBLE,
    timestamp TIMESTAMP
) TIMESTAMP(timestamp) PARTITION BY YEAR WAL
  DEDUPLICATE UPSERT KEYS(timestamp, indicator);

INSERT INTO macro_clean
SELECT indicator, first(series_id) AS series_id, max(value) AS value, timestamp
FROM macro_indicators
GROUP BY indicator, timestamp;

-- ---------------------------------------------------------------------------
-- 4. VERIFY BEFORE DROPPING. macro_clean's count must equal the
--    rows_distinct figure from step 1, and every indicator must survive.
-- ---------------------------------------------------------------------------
SELECT count() AS clean_rows FROM macro_clean;

SELECT indicator, count() AS rows, min(timestamp) AS first_obs,
       max(timestamp) AS last_obs
FROM macro_clean
GROUP BY indicator
ORDER BY indicator;

-- Spot-check one series against the original. Values must match.
SELECT timestamp, value FROM macro_clean
WHERE indicator = 'Inflation_CPI' ORDER BY timestamp DESC LIMIT 5;

SELECT DISTINCT timestamp, value FROM macro_indicators
WHERE indicator = 'Inflation_CPI' ORDER BY timestamp DESC LIMIT 5;

-- ---------------------------------------------------------------------------
-- 5. Swap. Only run this once step 4 looks right.
-- ---------------------------------------------------------------------------
DROP TABLE macro_indicators;

RENAME TABLE macro_clean TO macro_indicators;

-- ---------------------------------------------------------------------------
-- 6. Confirm, then restart the worker:  docker compose up -d fred_worker
--    Re-run scripts/check_data.py afterwards; section 2 should report
--    "no meaningful duplication".
-- ---------------------------------------------------------------------------
SELECT count() AS rows_total FROM macro_indicators;

SELECT indicator, count() AS rows FROM macro_indicators
GROUP BY indicator ORDER BY indicator;
