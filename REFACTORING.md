# Refactoring backlog

Written 2026-08-21, after the frontend/visualisation cleanup. Everything here is
**still open** — the "Done in this pass" section at the bottom records what was
changed so you can tell the two apart. Items are ordered by priority within each
group, and each one says *why* it matters, so you can drop the ones you disagree
with without having to re-derive the reasoning.

`BACKLOG.md` (2026-08-18/19) is still valid for the backend/data items it lists;
this file supersedes it for anything frontend or visualisation, and carries its
still-open backend items forward below so there is one list to work from.

---

## P0 — Do before the app leaves this laptop

These are all fine on a single-user localhost box and all wrong on a server with
a public IP. Group them into one "hardening" session.

- [ ] **The FRED API key is committed in plaintext** in `docker-compose.yml`
      (`FRED_API_KEY=05f6f0...`) *and* hardcoded as the default in
      `fred_worker/main.py`. It is in git history and was pushed to
      `origin/main`. Rotate the key, move it to a `.env` file (gitignored) read
      via `env_file:` in compose, and leave no default in the code — a missing
      secret should crash loudly at startup, not silently fall back to a leaked
      one.

- [ ] **`allow_origins=["*"]` on the API** (`api/api.py`) with no auth of any
      kind. Any page in the browser can read the whole portfolio, and any client
      that can reach port 8000 can `POST /api/track`. Before deploying: pin
      `allow_origins` to the frontend's real origin, and put the whole thing
      behind a reverse proxy with basic auth or an mTLS/VPN boundary. There is no
      user model to build on here, so network-level auth is the cheap correct
      answer.

- [ ] **Personal financial data is in git history on GitHub.** `BACKLOG.md`
      flagged this: the seed JSONs, both Trade Republic CSVs and the tickers
      files are now gitignored and untracked, but untracking does not rewrite
      history and they were already pushed to `bre-epillon/open-finance`. Decide
      explicitly: make the repo private and accept the history, or
      `git filter-repo` + force-push. Nothing else in this list matters as much.

- [ ] **`f`-string SQL interpolation into QuestDB** in
      `/api/data`, `/api/corporate_actions`. Ticker strings go straight into the
      query text. On localhost with only your own frontend calling it, this is
      theoretical; the moment the API is reachable it is an injection endpoint.
      Validate tickers against `^[A-Z0-9.\-^]{1,12}$` before interpolating (QuestDB's
      REST API has no parameter binding, so validation *is* the fix).

- [ ] **No healthcheck or restart semantics for the local (non-Docker) path.**
      `portfolio_app.sh` starts the processes; nothing notices when the API dies.
      Before the server deployment, decide whether you are running compose there
      (in which case add `healthcheck:` blocks) or systemd units.

---

## P1 — Correctness and trust in the numbers

- [ ] **No tests anywhere, and `portfolioTimeSeries.js` is the highest-risk file
      in the repo.** It silently produces plausible-but-wrong numbers; three
      separate bugs were found there by hand-diffing totals. It now has two more
      consumers (`RiskPanel` and `AllocationPanel` both read its output), so the
      blast radius grew. Add Vitest with fixed synthetic inputs covering:
      `buildValueSeries` (BUY/SELL sign handling, missing-price fallback to cost
      basis, the `totalValue === netContributions + cashInterestCum + dividendsCum
      + bondsIncomeCum + selloffGainsCum + stocksUnrealizedGain` identity),
      `buildPerformanceSeries` (a deposit must not register as a gain; all
      components on must reproduce the value curve), and the new
      `computeRiskStats` / `computeAllocation`. This is the single highest-value
      item on the list.

- [ ] **Mixed currencies are labelled as EUR.** The whole UI now formats as EUR,
      which is right for transactions, deposits and coupons. But yfinance closes
      for US-listed tickers are USD, so `AAPL`'s "last close" and its unrealised
      P&L are USD numbers wearing a € sign. Two options: ingest an FX series
      (ECB daily reference rates are free and need no key) and convert at the
      close date, or display a per-position currency badge and stop summing
      across currencies. The FX route is more work but is the only one that makes
      "net worth" a real number. `utils/format.js` has a `formatPrice` alias
      marking every affected call site.

- [ ] **`Date.now()` inside `usePortfolio`'s `handleAddTransaction`** is the
      transaction id. Two entries added in the same millisecond collide, and more
      importantly the id is the key the bundled-JSON reconciliation uses to tell
      "manual" from "imported" — use `crypto.randomUUID()`.

- [ ] **Sharpe uses a hardcoded 2% risk-free rate** (`RISK_FREE_RATE` in
      `utils/portfolioStats.js`). Deliberate — a stable comparable ratio beats a
      live rate — but if you would rather it track reality, `fred_worker` already
      ingests `FEDFUNDS`; an ECB deposit-rate series would be the right one for a
      EUR portfolio.

- [ ] **Bonds are held at cost, everywhere.** Correct given no bond price feed,
      documented in every panel that shows it, and it means the "Bonds"
      contribution to performance is income only, never price movement. If bond
      mark-to-market matters, that is a data-ingestion project, not a frontend
      one.

- [ ] **Volatility treats consecutive series points as consecutive days.** The
      value series is built on event-and-price days, so a gap over a long weekend
      is one "day". The annualisation factor of sqrt(252) is therefore slightly
      off. Immaterial at this scale, worth knowing before quoting the number
      anywhere that matters.

- [ ] **The `CORPORATE_ACTION / SPLIT` row in the Trade Republic export is still
      silently ignored** by `parse_csv.py`, and is never reconciled against
      `worker/corporate_actions.py`'s independently-detected splits. Worth
      checking whether the two ever disagree. (Carried from BACKLOG.md.)

- [ ] **Thin price history for recently-added tickers** (`CBU8.DE`, `NAQ.DE`,
      `BKJ.F`, `85H1.DE`, `NOVA.F`) means `buildValueSeries` falls back to cost
      basis for most of their holding period, understating unrealised gains.
      Periodically `select ticker, count() from equity_prices group by ticker` and
      re-trigger the backfill for anything thin. (Carried from BACKLOG.md.)

---

## P2 — Structure (Architecture.md compliance)

Current files over the 200-line cap, verified against the repo as of this
writing:

| File | Lines | Note |
|---|---|---|
| `frontend/src/components/PortfolioManager.css` | 440 | Mechanical split by section (summary / forms / tables / ledger). Lowest-risk item here. |
| `frontend/src/App.css` | 350 | Grew in this pass: it is now the design-token sheet *and* the utility layer. Arguably exempt -- it is one declaration list, not logic -- but splitting into `tokens.css` + `utilities.css` + `layout.css` would be clean and zero-risk. |
| `api/api.py` | 295 | The most defensible split: DB schema + ingestion vs. HTTP routes are already two concerns in one file. |
| `frontend/src/hooks/usePortfolio.js` | 264 | Split candidate: the split/ISIN reconciliation is separable from the holdings calculation, and both are already exported pure functions. |
| `frontend/src/utils/portfolioTimeSeries.js` | 259 | One cohesive sweep algorithm. Splitting purely to hit a line count would hurt readability; if anything, extract the benchmark/shadow-portfolio logic. |
| `transactions/parse_csv.py` | 246 | Untouched this pass. |
| `frontend/src/utils/portfolioStats.js` | 212 | New in this pass, marginally over. Splits cleanly into `risk.js` + `allocation.js` if you want it under. |

- [ ] Split `api/api.py` into `api/db.py` (schema + ingestion) and `api/routes.py`.
- [ ] Split `usePortfolio.js`: move `reconcileTickers` / `applySplitsToTransactions`
      into `utils/corporateActions.js` (they are already exported and pure, so
      this is a move plus an import, and it makes them testable in isolation).
- [ ] Split `PortfolioManager.css` by section.

---

## P3 — Visualisation and analytics still worth adding

The two you picked (allocation/concentration, drawdown/risk) are in. These are
the ones deliberately left out:

- [ ] **Return attribution waterfall.** Where the total return came from:
      contributions → stock unrealised → dividends → bond income → selloff gains →
      cash interest. Every input is already computed in `buildValueSeries`
      (`netContributions`, `stocksUnrealizedGain`, `dividendsCum`, `bondsIncomeCum`,
      `selloffGainsCum`, `cashInterestCum`) and the accounting identity means the
      bars are guaranteed to reconcile to the total. Probably the highest-value
      remaining chart: it answers "am I actually good at picking stocks, or is this
      just deposits and dividends".

- [ ] **Per-position P&L contribution bar.** Horizontal bars of each holding's
      contribution to total P&L in euros (not percent) — a 2% gain on your largest
      position matters more than a 40% gain on your smallest, and nothing in the
      UI currently shows that.

- [ ] **Monthly income calendar.** Bar chart of dividends + coupons + cash
      interest per month, with trailing-12-month income and yield-on-cost.
      `utils/portfolioStats.js` already exports `groupByMonth` for exactly this;
      it is currently unused. Would slot naturally into `CashFlowView`.

- [ ] **Benchmark-relative rolling return.** The performance chart shows two
      absolute curves; a single "excess return vs benchmark" line is easier to
      read for the "am I beating the index" question, and removes the need to
      eyeball a gap between two wiggly lines.

- [ ] **Correlation / overlap warning.** `SXR8.DE` (S&P 500), `EUNL.DE` (MSCI
      World) and `VWCE.DE` (FTSE All-World) are ~60% the same underlying
      companies. Concentration measured per-ticker (as it is now) understates
      true exposure considerably. Even a static hand-maintained map of
      fund → region/index would let the panel say "your effective US large-cap
      exposure is X%", which is the number that actually matters.

- [ ] **Terminal window vs. StatsGrid range mismatch.** `ChartContainer` slices to
      the selected window client-side, while `StatsGrid` summarises everything
      loaded. The labels now say "loaded history" so nothing is *wrong*, but
      lifting the window into `ResearchView` state and passing it to both would be
      better. Small, self-contained.

---

## P4 — Developer experience and deployment prep

- [ ] **A single `.env`, sourced by both `portfolio_app.sh` and ad-hoc scripts.**
      Every Python process needs `SSL_CERT_FILE` / `CURL_CA_BUNDLE` /
      `REQUESTS_CA_BUNDLE` (the corporate TLS-interception workaround) plus
      `QUESTDB_HOST` / `QUESTDB_REST_PORT` / `QUESTDB_ILP_PORT`. `portfolio_app.sh`
      bakes these in for the managed flow; every one-off script needs them
      retyped, which is a recurring source of confusing SSL errors. This gets more
      important, not less, once there is a second environment.

- [ ] **A real README describing the system shape**: QuestDB + FastAPI +
      APScheduler workers + React frontend, which service owns which table, and
      how `transactions/parse_csv.py` feeds `frontend/src/*.json`.
      `Architecture.md` covers code-style philosophy, not the system. Four backend
      processes and a non-trivial data pipeline deserve one page.

- [ ] **`frontend/Dockerfile` runs the Vite dev server** (`docker-compose.yml`
      maps port 3000 and sets `NODE_ENV=development`). For the server deployment
      you want a two-stage build — `vite build` then serve `dist/` from nginx or
      Caddy — not a dev server with HMR polling exposed.

- [ ] **`equity_prices_intraday` cleanup has never been observed running.**
      `scheduled_intraday_cleanup` (cron 00:07) was added and reasoned about but
      never watched through a real midnight. Confirm it drops partitions older
      than 4 days. (Carried from BACKLOG.md.)

- [ ] **QuestDB stability under ingestion load.** It crashed twice in an earlier
      session. The `equity_prices` DAY→MONTH repartition fixed the dominant cause
      (an 11,513-partition blowup), but the "many small ILP commits into a
      DEDUPLICATE UPSERT table" pattern is still how ingestion works. Watch
      `questdb.log` for OOM / O3-merge issues under the next heavy backfill.
      (Carried from BACKLOG.md.)

- [ ] **Health-check `fred_worker` and `worker/corporate_actions.py`.** Neither
      has been touched in a while; confirm `select count() from corporate_actions`
      is sane and that the FRED daily job at 01:30 is still landing rows.
      (Carried from BACKLOG.md.)

- [ ] **`fred_worker` may now be orphaned.** It ingests eight macro series into
      `macro_indicators`, and the only consumer was the Fear & Greed calculation
      that was removed in this pass (`scripts/ingestion_status.py` reads the table
      but only to report row counts). Either keep it running as data collection
      for the later sentiment project — it is cheap and the history is worth
      accumulating — or stop the process and drop it from compose. Decide
      deliberately rather than leaving it as a mystery container.

- [ ] **`_to_delete/` needs your review.** `device_bash` cannot delete files, so
      the removed code was moved, not deleted:
      `_to_delete/fear_and_greed/` (`FearAndGreed.jsx`, `FearAndGreed.css`,
      `api/sentiment.py`, `scripts/compute_sentiment.py`) and
      `_to_delete/scratch/` (`test_browser.js`, `test_browser.cjs`,
      `failed_imports.txt`, `dashboard.html`). The Fear & Greed files are the ones
      you said you want for a later project — move them somewhere you will find
      them, then delete the folder. Note the API side also created a
      `sentiment_history` table; `DROP TABLE sentiment_history` when you are sure
      you do not want the computed history.

---

## Done in this pass (2026-08-21)

For reference, so the next session does not redo it.

**Removed**
- Fear & Greed, end to end: component + CSS, the `/sentiment` route, nav tab and
  landing-page card, `api/sentiment.py`, the `/api/v1/sentiment/fear-and-greed`
  endpoint and its import, `scripts/compute_sentiment.py`. Moved to
  `_to_delete/fear_and_greed/`, not deleted.
- `ChartContainer`'s dual-range window slider and its mini-preview SVG. It
  duplicated the time-window buttons, and was the reason the component (321
  lines) and its stylesheet (212) were both over the cap. Now 193 / 105.
- Scratch files: `test_browser.js`, `test_browser.cjs`, `failed_imports.txt`,
  `dashboard.html` (a redirect stub to `index.html`).
- The `puppeteer` dependency — pulled in only for those two throwaway scripts,
  and it downloads a whole Chromium.
- Dead CSS: `.resolution-select` (unused since the manual 1d/1h dropdown was
  removed), `.portfolio-main-grid` (declared, never used), and the duplicate
  copies of `.positive` / `.negative` / `.align-right` / `.truncate` / `.text-xs`
  / `.w-10` / `.max-w-xs` that had drifted between stylesheets.
- The second y-axis on the composition chart. "Cumulative interest" was plotted
  against its own right-hand scale, which makes two curves look comparable when
  they are not — and the interest was already counted inside the cash band, so it
  was double-drawn as well as mis-scaled.

**Fixed**
- **The utility-class layer did not exist.** `font-mono` (33 uses), `text-muted`
  (11), `text-sm`, `flex`, `flex-col`, `gap-6`, `mt-4`, `mb-2`, `ml-2`, `p-0` and
  the `text-*-500` colour helpers were all referenced in JSX with no Tailwind
  installed and no definitions anywhere — so every "monospace" figure rendered in
  Inter and every "muted" caption at full-strength white. Defined as a closed,
  documented layer at the bottom of `App.css`.
- `--text-muted` was `#64748b`: 3.6:1 on the card surface, under the 4.5:1
  body-text floor. Now `#7c8ba1`.
- The chart palette was re-stepped into the dark lightness band and re-ordered so
  no two adjacent series slots collapse under deuteranopia or protanopia (blue
  beside purple measured ΔE 0.9 — indistinguishable). Same eight hues; validated
  against the actual card surface: worst adjacent CVD ΔE 13.9, worst
  normal-vision ΔE 29.1, every slot ≥3:1 contrast.
- `.panel-header` is a flex *row*, so two `.panel-header-row` children laid out
  side by side instead of stacking — which is what collided the benchmark toggles
  with the "Include in return" label. Added `.panel-header.stacked`.
- The summary row's `auto-fit` grid wrapped the fourth card onto its own line
  (and a stale `@media` rule later in the file forced 3 columns regardless). Now
  explicitly 4-up, with a `.cols-3` variant.
- `ChartContainer` called `rawData.find()` once per point per series inside the
  render path — O(points × series × rows), millions of comparisons per re-render
  with 5,000 rows. One pass builds a `ticker → timestamp → close` Map instead.
- `App.jsx`'s `fetchTickers` closed over `selectedTickers`, so it was rebuilt on
  every sidebar click, and the 5-minute background poller was torn down and
  restarted each time. The selection rule is a functional update now, and the
  poller holds the fetch in a ref.
- `PortfolioManager` refetched the whole price history whenever the transactions
  *array identity* changed (split adjustment, localStorage rehydrate, one manual
  entry). The effect keys on the request URL string now.
- `api.py`'s startup ran `execute_historical_backfill` synchronously for all 34
  tracked tickers before Uvicorn accepted a request — the reason a restart could
  hang for minutes. Now a daemon thread, with per-ticker error isolation.
- Currency was `$` in the tables and stat cards, `€` in the charts and cash-flow
  view, on EUR data. Single `utils/format.js`, EUR throughout, de-DE grouping,
  `tabular-nums` so columns align. (See the mixed-currency caveat in P1.)
- Intl's `notation: 'compact'` does nothing useful in de-DE — CLDR has no German
  thousands abbreviation, so 60000 came back as "60.000,0 €", longer than the
  plain form. Hand-rolled compact formatter.
- The allocation panel's total used a clamped non-negative cash figure while the
  summary card used the raw one, so the two disagreed on a negative cash balance.
  Both tie now, and when cash is negative the weights switch denominator to
  invested assets and the panel says so, rather than printing 109%.
- "Net Portfolio Value" showed equity-at-market only — cash and bonds excluded —
  so the headline was smaller than the account and did not tie to the composition
  chart's total height. Net worth is its own tile now.
- The tracked-asset list's `max-height: 250px` sliced the sixth row in half,
  which read as a rendering bug. Sized to whole rows with a fade affordance.
- Chart legends used `rectRounded` + `usePointStyle`, which draws an empty
  outline for datasets with a transparent background. Line charts get a stroke
  swatch (which reproduces the dash pattern, so the benchmark is identifiable by
  more than colour); stacked areas get a filled box.
- `prefers-reduced-motion` is respected.
- Focus-visible outlines on the button groups (they had none).

**Added**
- `utils/format.js` — one place that decides how a number renders.
- `utils/chartTheme.js` — one Chart.js theme. The three chart components each
  carried their own ~50-line options object, near-identical and drifting.
- `utils/portfolioStats.js` — drawdown, risk stats, allocation, month bucketing.
  Pure functions, no React, same contract as `portfolioTimeSeries.js`.
- **Allocation & Concentration panel** — asset-class share bar, per-position
  weight bars (top 12, then "Other"), effective-position count (HHI reciprocal),
  top-5 weight, largest position.
- **Drawdown & Risk panel** — underwater curve plus max drawdown with its
  peak/trough dates, current drawdown, annualised volatility, Sharpe, best/worst
  month, positive-month rate, annualised return. All measured on the
  time-weighted return index, not on total value — a deposit lifts value without
  being a gain, so a value-based drawdown curve would "recover" every payday.
- A `% change` / `Price` toggle on the research chart, defaulting to `% change`
  whenever more than one asset is selected. Overlaying a €5 stock and a €500 one
  on a shared price axis flattens both into straight lines.
- `ResearchView.jsx`, extracted from `App.jsx` so `App` is routing and fetching
  only (and both land under the 200-line cap).
- Vite `manualChunks`: the 530KB single bundle (over Vite's warning threshold) is
  now app 104KB / vendor 178KB / charts 210KB, so the chart library is cached
  across deploys instead of redownloaded with every frontend change.
- Method notes under each chart, replacing the collapsed `<details>` nobody
  opens. Every approximation the numbers rest on (bonds at cost, cost-basis
  fallback for thin price history, deposits removed before measuring return) is
  now stated where the number is shown.

**Reordered**
- The portfolio page follows the order the questions get asked: net worth →
  allocation → composition over time → performance vs benchmark → drawdown &
  risk → holdings → closed positions → cash flow → manual entry form. The entry
  form used to sit between the charts and the tables, pushing the holdings table
  below the fold for no reason. The cash-flow ledger is collapsed by default —
  several hundred rows, open by default, was adding thousands of pixels of page
  height.
- Nav is two tabs: "Portfolio" (first — it is what the app is for) and
  "Research". The container widened from 1200px to 1520px; the wide stacked-area
  and performance charts were cramped at ~1100px of plot width on any real
  monitor.
- De-jargoned the chrome: "Live Terminal" → "Research", "Ingest New Node" →
  "Track a New Asset", "Node Connected" → "API connected", "High-frequency
  timeseries node visualizer" → "Portfolio & market data".

**Verified**
- `vite build` clean, no orphaned imports.
- Rendered against a synthetic 20-month, 10-position portfolio and screenshotted
  every page; the layout and formatting fixes above are all things that showed up
  in those screenshots rather than in the source.
