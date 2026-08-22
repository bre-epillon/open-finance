-- 0003b — macro_indicators: rebuild instead of migrate
--
-- SUPERSEDES 0003-macro-dedup.sql. Read this one; keep 0003 only as the record
-- of what the problem was.
--
-- ---------------------------------------------------------------------------
-- WHY THIS REPLACES 0003
-- ---------------------------------------------------------------------------
-- 0003 assumed the only problem was duplicate rows, and solved it with a
-- careful copy-verify-swap. Two things turned out to be true that it did not
-- account for:
--
-- 1. The bigger problem is PARTITIONING, not duplication. macro_indicators was
--    never given a CREATE TABLE, so the ILP Sender auto-created it with
--    QuestDB's default PARTITION BY DAY. Measured 2026-08-22: 8,573 daily
--    partitions from 1970 to 2026, and a single out-of-order merge rewriting
--    8,354 of them one at a time. While that runs, `count()` still answers
--    instantly from metadata but anything that reads rows queues behind the
--    writer -- which is why 0003's second statement appeared to hang.
--
-- 2. Every row in this table is re-fetchable from FRED in about two minutes.
--    There is no unique data here to preserve. So the copy-verify-swap dance
--    buys nothing and has to read the very table that is contended.
--
-- Dropping and re-ingesting is faster, simpler, and cannot half-succeed.
--
-- The 0003 diagnostic query that hung --
--     SELECT count() FROM (SELECT DISTINCT timestamp, indicator FROM ...)
-- -- is also just a bad way to ask. Step 1 below uses a GROUP BY on the
-- indexed SYMBOL instead, which QuestDB serves happily and which tells you
-- *which* series is duplicated rather than only that something is.

-- ---------------------------------------------------------------------------
-- 0. PRECONDITIONS. Do not skip these.
-- ---------------------------------------------------------------------------
-- a) Stop every writer, leaving QuestDB up:
--        /c/ofvenvs/portfolio_app.sh quiet
--    fred_worker alone is not enough -- open-finance's api and worker, and
--    regime_worker, all write here or to equity_prices.
--
-- b) Wait for the in-flight O3 merge to drain:
--        /c/ofvenvs/portfolio_app.sh questdb-busy
--    Re-run until it reports idle. Dropping a table mid-merge is not worth
--    finding out about.

-- ---------------------------------------------------------------------------
-- 0c. IF QUESTDB IS DOWN (it fell over doing this merge on 2026-08-22)
-- ---------------------------------------------------------------------------
-- Symptom: the console will not load and `questdb-busy` reports DEAD. On disk,
-- db/macro_indicators~10 held 12,897 entries -- daily partition directories
-- from 1970-01-01.55 to 2026-08-21.49, where the numeric suffix is a rewrite
-- counter. The 1970 partition had been rewritten 55 times. equity_prices, which
-- is MONTH-partitioned, had 677.
--
--     /c/ofvenvs/portfolio_app.sh start questdb
--
-- QuestDB alone, no writers. It replays the table's WAL on startup (there is a
-- txn_seq under macro_indicators~10), which CAN drop it straight back into the
-- same merge. Watch:
--
--     /c/ofvenvs/portfolio_app.sh questdb-busy
--
-- If it comes up ALIVE and IDLE, go to step 1 immediately -- before starting any
-- writer, or ILP will recreate the table with DAY partitioning and you are back
-- where you started.
--
-- If it comes up and re-enters the merge, let it run with nothing else competing
-- (it has the whole machine this time). If it dies again, or never finishes:
--
--   LAST RESORT, with QuestDB STOPPED. Every row here is re-fetchable from
--   FRED, which is what makes this acceptable -- it would not be for
--   equity_prices.
--       1. ./portfolio_app.sh stop
--       2. delete the directory  C:\ofvenvs\questdb-data\db\macro_indicators~10
--          (and macro_indicators~10.lock beside it)
--       3. ./portfolio_app.sh start questdb
--       4. skip to step 3 below -- CREATE TABLE, then start the writers
--   QuestDB will log a warning about the missing table and carry on; the
--   registry entry in tables.d is rebuilt from the CREATE.

-- ---------------------------------------------------------------------------
-- 1. Look before you leap. One statement, safe while busy, tells you
--    everything: rows vs distinct timestamps per series, and the date span.
--    A rows/uniq_ts ratio near 1.0 means no duplication.
-- ---------------------------------------------------------------------------
SELECT indicator,
       count()                    AS rows,
       count_distinct(timestamp)  AS uniq_ts,
       min(timestamp)             AS first_obs,
       max(timestamp)             AS last_obs
FROM macro_indicators
GROUP BY indicator
ORDER BY indicator;

-- ---------------------------------------------------------------------------
-- 2. Drop it. Every row comes back from FRED on the next worker start.
-- ---------------------------------------------------------------------------
DROP TABLE macro_indicators;

-- ---------------------------------------------------------------------------
-- 3. Recreate it with the right shape.
--
-- PARTITION BY YEAR: ~14 low-frequency series over 55 years is 55 partitions,
-- against 8,573 under DAY. Out-of-order arrival then touches a handful of
-- partitions instead of thousands, which is what makes a deep-history ingest
-- finish in minutes rather than hours.
--
-- DEDUPLICATE UPSERT KEYS(timestamp, indicator): makes fred_worker's nightly
-- re-fetch an idempotent upsert. Without it the table grew by a full copy of
-- its window every night.
--
-- This same DDL now also lives in open-finance/api/api.py's init_db_schema(),
-- so a fresh QuestDB volume gets it automatically. Running it here is for the
-- existing volume; you could equally just restart the api and let it create it.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS macro_indicators (
    indicator SYMBOL INDEX,
    series_id SYMBOL,
    value DOUBLE,
    timestamp TIMESTAMP
) TIMESTAMP(timestamp) PARTITION BY YEAR WAL
  DEDUPLICATE UPSERT KEYS (timestamp, indicator);

-- ---------------------------------------------------------------------------
-- 4. Confirm the shape took. partitionBy must read YEAR, dedup must be true.
-- ---------------------------------------------------------------------------
SELECT * FROM tables() WHERE table_name = 'macro_indicators';

-- ---------------------------------------------------------------------------
-- 5. Refill, then verify.
--
--     /c/ofvenvs/portfolio_app.sh start
--
-- fred_worker ingests its eight series on startup, regime_worker its own six.
-- Both now start at 1970-01-01 (not 1960 -- QuestDB's ILP rejects a negative
-- designated timestamp, and a pre-epoch row aborts the whole series).
--
-- Give them a few minutes, then re-run step 1. Expect rows == uniq_ts for
-- every series, and first_obs at or after 1970-01-01. Then:
--
--     /c/ofvenvs/portfolio_app.sh regime-backfill --register
-- ---------------------------------------------------------------------------
SELECT indicator, count() AS rows, count_distinct(timestamp) AS uniq_ts,
       min(timestamp) AS first_obs, max(timestamp) AS last_obs
FROM macro_indicators
GROUP BY indicator
ORDER BY indicator;
