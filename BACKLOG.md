# Backlog

Working notes for the next session, written 2026-08-18 after the portfolio
performance/chart work, updated 2026-08-19 after clearing the "do first"
items. Grouped by priority, not by when it was found. Line counts and facts
below were verified against the actual repo state, not memory — re-check
anything before acting on it if much time has passed.

## Done (2026-08-19)

- Personal financial data (`transactions/*.json`, `frontend/src/*.json`
  seed files, both raw Trade Republic CSVs, `tickers.json`/`api/tickers.json`)
  is now gitignored and untracked (`git rm --cached`) so future commits won't
  include it. **Important caveat, left for you to act on:** these files were
  already pushed to `origin/main` on GitHub (`bre-epillon/open-finance`) —
  untracking only stops *future* commits, it does not remove the data from
  existing git history or from GitHub. You said you'd check the repo's
  visibility yourself; if it needs scrubbing from history that's a separate,
  more invasive `git filter-repo`/force-push job that needs your explicit
  go-ahead. The untracking changes are staged locally, not committed.
- `execute_historical_backfill` (+ `get_latest_timestamp_db` + `DB_CHECK_FAILED`)
  deduplicated into `shared/backfill.py`, imported by both `api/api.py` and
  `worker/main.py`. The two copies had already drifted (`== 0` vs `<= 1` day
  staleness threshold) — standardized on `<= 1`, since a same-day gap before
  markets close isn't a real gap worth a wasted yfinance call. Verified both
  processes still import and run correctly after the change.
- Pruned the 24 duplicate ISIN entries from `api/tickers.json` (58 → 34
  tracked tickers). Before doing this, found and fixed a real dependency it
  would have broken: `usePortfolio.js`'s `applySplitsToTransactions` matched
  a split's `ticker` against `tx.isin` *only* when present, so a split
  recorded by `worker/corporate_actions.py` under the conventional ticker
  (the only form left tracked now) would never have matched. Fixed to check
  both `isin` and `ticker`, so split-matching no longer depends on which key
  form happens to be tracked.

## Correctness / data integrity

- `api.py`'s `startup_event()` still calls `execute_historical_backfill`
  synchronously for every tracked ticker (34 today, after pruning duplicates)
  before Uvicorn accepts requests. Harmless when QuestDB is warm and
  everything's already backfilled (fast skip-checks), but it's the reason a
  restart hung for minutes earlier this session when checks were slow. Move
  it to a background task so the API always comes up immediately regardless
  of backfill state.

- No test coverage anywhere in the repo, and `portfolioTimeSeries.js` in
  particular is exactly the kind of code that silently produces plausible
  wrong numbers — this session alone found three separate bugs there (SELL
  quantity sign, $0-instead-of-cost-basis on missing price data, bond
  realized-gain cost-basis) purely by manually diffing against expected
  totals. Worth a small Vitest/Jest suite for `buildValueSeries` and
  `buildPerformanceSeries` against fixed synthetic inputs, so the next change
  there doesn't need a fresh round of manual smoke-testing to trust.

- Several niche/recently-added tickers (`CBU8.DE`, `NAQ.DE`, `BKJ.F`,
  `85H1.DE`, `NOVA.F`, etc.) only have a handful of days of real price
  history in QuestDB; `buildValueSeries` falls back to cost basis for them
  for most of their holding period. That's a correct, documented
  approximation, not a bug — but it does mean the "Stocks" unrealized-gain
  component in the performance chart understates reality for these names
  until more history backfills in. Worth periodically checking
  `select ticker, count() from equity_prices group by ticker` and manually
  re-triggering `execute_historical_backfill` for anything still thin.

- The one `CORPORATE_ACTION / SPLIT` row that showed up in the Trade
  Republic CSV export is currently silently ignored by `parse_csv.py` — it's
  neither captured nor reconciled against `worker/corporate_actions.py`'s own
  independently-detected splits. Worth checking whether the two ever
  disagree.

- Haven't touched `fred_worker/` or `worker/corporate_actions.py` all
  session; worth a quick health check (`select count() from
  corporate_actions`, confirm the FRED daily job at 01:30 is still landing
  rows) now that `equity_prices` has been dropped and rebuilt twice.

## Architecture.md compliance (files over the 200-line cap)

Flagged repeatedly this session, never acted on. Current sizes:

| File | Lines |
|---|---|
| `api/api.py` | 290 (was 450 — shrank when the duplicated backfill logic moved to `shared/backfill.py`) |
| `frontend/src/components/ChartContainer.jsx` | 321 |
| `frontend/src/utils/portfolioTimeSeries.js` | 259 |
| `frontend/src/hooks/usePortfolio.js` | 251 |
| `frontend/src/App.jsx` | 249 |
| `transactions/parse_csv.py` | 246 |

`worker/main.py` dropped to 139 lines from the same refactor and is no
longer over the cap. `portfolioTimeSeries.js` is one cohesive sweep
algorithm — splitting it purely to hit a line count would likely hurt
readability more than it helps; if anything, split by extracting the
benchmark/shadow-portfolio logic into its own module. `api.py` is the most
defensible remaining split: DB schema/ingestion vs. HTTP route handlers are
already two distinct concerns living in one file. `ChartContainer.jsx`
likely splits cleanly into the chart itself vs. the time-window slider (the
mini-preview SVG + dual-range-input block is self-contained). Ask before
doing a big mechanical split — it touches a lot of surface for little
functional benefit.

## Stability / performance

- QuestDB has crashed twice this session under ingestion load (once
  immediately after an unrelated API restart, once mid-diagnosis). The
  `equity_prices` DAY→MONTH repartition fixed the dominant cause
  (11,513-partition blowup), but the crashes predate that full understanding
  — worth keeping an eye on `questdb.log` for OOM/O3-merge issues under the
  next heavy backfill, since the underlying "many small ILP commits into a
  DEDUPLICATE UPSERT table" pattern is still how ingestion works.

- `equity_prices_intraday`'s daily cleanup job (`scheduled_intraday_cleanup`,
  cron 00:07) has never actually been observed firing successfully — it was
  added and reasoned about but not watched through a real midnight run.
  Confirm it's dropping partitions older than 4 days as intended.

- Frontend production bundle is 530KB (gzip 170KB), over Vite's 500KB
  warning threshold, and will only grow as more chart components get added.
  Not urgent for a local single-user app, but `manualChunks` (splitting
  chart.js/react-chartjs-2 into its own chunk) would be a quick win if load
  time ever becomes noticeable.

## Developer experience

- Every Python process launch across this whole project needs
  `SSL_CERT_FILE` / `CURL_CA_BUNDLE` / `REQUESTS_CA_BUNDLE` set by hand (for
  the corporate TLS-interception workaround) plus `QUESTDB_HOST` /
  `QUESTDB_REST_PORT` / `QUESTDB_ILP_PORT`. `portfolio_app.sh` bakes these in
  for the managed start/stop/restart flow, but any one-off script (like the
  diagnostic backfill scripts from this session) needs them re-typed. A
  single `.env` file sourced by both `portfolio_app.sh` and ad-hoc scripts
  would remove a recurring source of "why is this failing with an SSL
  error" confusion.

- No README describing the overall architecture (QuestDB + FastAPI +
  APScheduler workers + React frontend, which service owns which table, how
  `transactions/parse_csv.py` feeds `frontend/src/*.json`). `Architecture.md`
  covers code-style philosophy but not the system shape. Worth a short
  top-level doc now that there are 4 backend processes and a non-trivial
  data pipeline — mainly for picking this back up after a longer gap.

## Nice to have

- Dead CSS: `.resolution-select` in `Header.css` is unused since the manual
  1d/1h dropdown was removed in favor of window-driven resolution.
- Consider whether `cash_deposits.json`/`interest_payments.json` need a
  dedicated "add manually" form the way transactions do, or whether they're
  meant to stay CSV-import-only.
