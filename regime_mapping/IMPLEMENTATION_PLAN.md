# Regime & Sentiment Engine — Implementation Plan

**Project:** `regime_mapping` — a standalone service that reads the QuestDB
instance owned by `open-finance` and adds two quantitative modules on top of it:
a Ray Dalio 4-quadrant macro regime map, and a Greed & Fear sentiment index.

**Status:** plan only. No code written yet. Written 2026-08-21 against the
`open-finance` repo state of the same date.

**Decisions already taken** (from the kickoff conversation):

| Decision | Choice |
|---|---|
| Location | Standalone project in `regime_mapping`, consuming the shared QuestDB |
| Stack | Python / FastAPI + plain JSX / Vite — matching `open-finance`, **not** the TypeScript in the original spec |
| First deliverable | This document |

---

## 0. What the backbone already gives us

Read before planning, so the plan builds on facts rather than the spec's
assumptions. Verified against the repo, not memory.

### Already in place and reusable

| Asset | Where | Why it matters |
|---|---|---|
| QuestDB (9000 REST / 8812 pg-wire / 9009 ILP) | `docker-compose.yml` | The whole storage layer. We add tables, we do not add a database. |
| `macro_indicators` table | written by `fred_worker/main.py` | Already carries **all eight** FRED series the quadrant maths needs as a starting point. |
| `equity_prices` (daily OHLCV, MONTH partitions, dedup upsert on `(ticker, timestamp)`) | `api/api.py:init_db_schema` | Daily history for the sentiment inputs. |
| `^GSPC`, `^VIX`, `TLT`, `HYG`, `LQD`, `^TNX`, `^IRX`, `^TYX`, `^FVX` | `worker/main.py:FX_BONDS_TICKERS` | Every market series the sentiment index needs is *already being ingested daily*. |
| Chunked historical backfill | `shared/backfill.py` | Battle-tested yfinance ingestion (5-year chunks back to 1970) we can call for any new ticker. |
| Chart.js theme | `frontend/src/utils/chartTheme.js` | Dark palette, 8-colour series ramp, tooltip/axis conventions. Copy it so both dashboards look like one product. |
| A working Greed & Fear implementation | `_to_delete/fear_and_greed/` | ~80% of the sentiment module, in Python, plus a Chart.js doughnut gauge with a custom needle plugin. Parked, not deleted. Port it — with the three fixes in §4.2. |
| Code philosophy | `Architecture.md` | *Boring, explicit, feature-first, no magic. No file >200 lines. No abstraction "for future use."* This plan is written to comply. |

### Where the original spec is wrong about the repo

These are not nitpicks — each one would have produced code that does not run.

1. **The backend is Python/FastAPI, not TypeScript/Node.** The frontend is
   plain `.jsx`, not TS (`@types/react` is present but nothing is typed).
   Resolved: we match the repo.
2. **There is no `assets` table.** Prices live in `equity_prices` and
   `equity_prices_intraday`. Any query written against `assets` fails.
3. **`ASOF JOIN` is a tool, not a requirement.** It is genuinely right for
   aligning daily equity data against monthly macro data in a single
   point-in-time query. It is the wrong tool for the regime maths, which needs
   rolling z-scores, YoY transforms and multi-period differences — those belong
   in pandas where they can be unit-tested. Plan: pandas for the maths,
   `ASOF JOIN` over pg-wire for the aligned read the API serves.

### Three defects in the backbone that block this project

These need fixing **before** the regime maths can be trusted. They are cheap.

#### 0.1 `macro_indicators` accumulates duplicate rows daily — blocking

`fred_worker/main.py` was never given a `CREATE TABLE`; the table is
auto-created by the ILP `Sender`, so it has **no `DEDUPLICATE UPSERT KEYS`**.
The worker then re-fetches *five years* of observations for all eight series
every day at 01:30 and re-inserts them.

Every observation is therefore duplicated once per day the worker has been
running. Any `avg()`, `count()` or `SAMPLE BY` over this table is already
wrong, and a naive `pivot` in pandas will raise on the duplicate index.

Fix, in order:

```sql
-- 1. confirm the damage
SELECT indicator, count() FROM macro_indicators GROUP BY indicator;
SELECT count() FROM (SELECT DISTINCT timestamp, indicator FROM macro_indicators);

-- 2. enable dedup so future ingests upsert instead of append
ALTER TABLE macro_indicators DEDUPLICATE UPSERT KEYS(timestamp, indicator);
```

`ALTER ... DEDUPLICATE` requires a WAL table and only applies to *new* writes,
so step 3 is a one-off rebuild of the existing rows:

```sql
CREATE TABLE macro_clean AS (
  SELECT timestamp, indicator, series_id, value FROM macro_indicators
) TIMESTAMP(timestamp) PARTITION BY YEAR WAL
  DEDUPLICATE UPSERT KEYS(timestamp, indicator);
-- verify counts, then swap
DROP TABLE macro_indicators;
RENAME TABLE macro_clean TO macro_indicators;
```

Until this is done, every read must defend itself with `LATEST ON timestamp
PARTITION BY indicator` or a pandas `drop_duplicates`. Our DB layer will do
that anyway (§3.2) — but the table should still be fixed.

#### 0.2 FRED history is capped at 5 years — blocking

`observation_start` is `today - 365*5`. For a rolling 10-year z-score that is
not enough data; for **quarterly** real GDP it is **20 observations total**,
which cannot support any percentile or z-score worth reporting.

Fix: change `observation_start` to `1960-01-01` for the macro series. FRED
returns the full series in one call, the payload is a few hundred KB, and with
dedup enabled (0.1) the daily re-ingest becomes an idempotent upsert instead of
unbounded growth. This is the single highest-value change to the backbone.

#### 0.3 The FRED API key is committed in plaintext — security

`05f6f0ba0a0347f8cb544300570ad8de` appears as a literal in **both**
`docker-compose.yml` and `fred_worker/main.py` (as the `os.getenv` default).
`BACKLOG.md` records that this repo was already pushed to
`github.com/bre-epillon/open-finance`.

Action, independent of this project: **rotate the key at FRED**, move it to a
gitignored `.env`, and change the `os.getenv` default to `None` with a loud
failure — a silently-wrong default is worse than a crash. `regime_mapping` will
read it from `.env` from day one and never hold a default.

---

## 1. Architecture

```
                    ┌──────────────────────────────┐
                    │  QuestDB  (existing, shared) │
                    │  9000 REST · 8812 pg · 9009   │
                    └──────┬───────────────┬────────┘
        writes             │               │            writes
   ┌───────────────────────┘               └──────────────────────┐
   │                                                             │
┌──┴──────────────────┐                            ┌─────────────┴──────────┐
│ open-finance        │                            │ regime_mapping         │
│ (unchanged)         │                            │ (this project)         │
│                     │                            │                        │
│ api      :8000      │                            │ api        :8100       │
│ worker   (equities) │                            │ worker  (nightly calc) │
│ fred_worker (macro) │                            │ mcp     (stdio)        │
│ frontend :3000      │                            │ frontend   :3100       │
└─────────────────────┘                            └────────────────────────┘
```

**Ownership rule, to keep the two projects from fighting:**

| Table | Written by | Read by |
|---|---|---|
| `equity_prices`, `equity_prices_intraday`, `corporate_actions` | open-finance | both |
| `macro_indicators` | open-finance's `fred_worker` **+ regime_mapping's `worker/extra_series.py`** | both |
| `regime_history` | regime_mapping only | regime_mapping |
| `sentiment_index` | regime_mapping only | regime_mapping |

Two notes on that table:

- **`macro_indicators` is a shared write.** Additive only: we append *new
  `indicator` symbols* (§2.2), never touch the eight that `fred_worker` owns.
  ILP with a symbol key makes this safe. The alternative — a separate
  `macro_indicators_regime` table — costs us a `UNION` in every macro query for
  no real isolation benefit. Recommending the shared write; say so if you
  disagree, it is a one-line change either way.
- **`sentiment_index`, not `sentiment_history`.** The parked script in
  `_to_delete/` writes `sentiment_history` and begins with
  `DROP TABLE IF EXISTS sentiment_history`. A different name means that if
  anyone ever runs the old script again it cannot destroy our table.

### Docker networking

`regime_mapping/docker-compose.yml` joins the existing network as external
rather than starting its own QuestDB:

```yaml
networks:
  default:
    external: true
    name: open-finance_default   # VERIFY: docker network ls
```

Compose derives that name from the directory, so confirm it locally before
relying on it. Services then reach the DB at `questdb:9000` exactly as
open-finance's do.

---

## 2. Data

### 2.1 Already ingested — usable as-is

| Indicator | FRED ID | Native freq | Used for |
|---|---|---|---|
| `GDP_Growth` | `A191RL1Q225SBEA` | quarterly | growth axis |
| `Inflation_CPI` | `CPIAUCSL` | monthly | inflation axis (needs YoY transform) |
| `Fed_Funds_Rate` | `FEDFUNDS` | monthly | policy context |
| `Unemployment` | `UNRATE` | monthly | growth axis (inverted) |
| `Yield_Curve` | `T10Y2Y` | daily | policy context |
| `M2_Money_Supply` | `M2SL` | monthly | liquidity context (needs YoY) |
| `Consumer_Sentiment` | `UMCSENT` | monthly | growth axis (soft) |
| `Junk_Bond_Spread` | `BAMLH0A0HYM2` | daily | sentiment: junk-bond demand |

### 2.2 To add — `worker/extra_series.py`

Rationale for each, because adding series without one is how a model becomes
unfalsifiable.

| Indicator | FRED ID | Freq | Why |
|---|---|---|---|
| `Industrial_Production` | `INDPRO` | monthly | The workhorse monthly growth proxy. Quarterly GDP alone cannot drive a monthly regime series. |
| `Nonfarm_Payrolls` | `PAYEMS` | monthly | Second independent monthly growth read; labour and output rarely turn together, which is informative. |
| `Core_CPI` | `CPILFESL` | monthly | Headline CPI is energy-driven and noisy; core is what policy reacts to. |
| `Breakeven_10Y` | `T10YIE` | daily | Market-implied forward inflation. The only *forward-looking* input on the inflation axis — everything else is backward-looking. |
| `Real_Yield_10Y` | `DFII10` | daily | Real rates separate "growth repricing" from "inflation repricing" when nominals move. |
| `Retail_Sales` | `RSAFS` | monthly | Demand-side growth read, complements the supply-side `INDPRO`. |

New equity tickers to track (via `open-finance`'s `POST /api/track`, which
already triggers the chunked backfill — no new ingestion code needed):

| Ticker | Why |
|---|---|
| `^VIX3M` | 3-month VIX. `^VIX3M / ^VIX` term structure is a real fear signal and replaces the fake put/call component (§4.2). |
| `GLD` | Gold. Needed for the All Weather tilt display, and a stagflation confirmer. |
| `DBC` | Broad commodities. Same. |
| `TIP` | TIPS. Same. |

### 2.3 Frequency alignment

The single most important modelling decision, and the one most likely to
produce quietly wrong numbers if fudged.

**Regime engine works at monthly frequency.** Reasons: the slowest input that
matters (GDP) is quarterly; a daily regime series would be 95% interpolation
noise; and Dalio's framework is a quarters-to-years framework, not a daily one.

Rules, applied in `engine/align.py`:

1. Resample every series to **month-end** using the **last observation in the
   month**. Never `mean()` — averaging a month of daily breakevens against a
   single monthly CPI print mixes two different things.
2. **Forward-fill only, never backward-fill.** Backfilling leaks future
   information into the past and will make any historical validation (§7) look
   better than the model is.
3. **Respect publication lag.** CPI for month *M* is published mid-*M+1*; GDP
   for a quarter lands a month after it ends. If we stamp a value at its
   *reference* date and then claim the regime was knowable then, we are
   backtesting with tomorrow's newspaper. Plan: store at the reference date
   (matching FRED and `fred_worker`), and apply an explicit **1-month shift on
   monthly series and 2-month shift on quarterly** when building the
   as-of-date view. One constant per series in the registry, `publication_lag_months`.
4. Daily series (`T10YIE`, `DFII10`, `T10Y2Y`) get lag 0 — they are market
   prices, known in real time.

**Sentiment engine works at daily (trading-day) frequency** — it is a
market-psychology gauge and daily is the point. It must *not* resample to
calendar days (see §4.2, defect 3).

---

## 3. Project structure

Every file below is targeted under the 200-line cap from `Architecture.md`.
Where a module looks likely to exceed it, the split is already shown.

```
regime_mapping/
├─ README.md                     system shape: what runs where, which table who owns
├─ Architecture.md               copy of open-finance's philosophy — same rules apply here
├─ IMPLEMENTATION_PLAN.md        this document
├─ .env.example                  FRED_API_KEY, QUESTDB_HOST, ports — no real secrets
├─ .gitignore                    .env, __pycache__, node_modules, dist
├─ docker-compose.yml            api + worker + frontend, external questdb network
│
├─ api/
│  ├─ Dockerfile
│  ├─ requirements.txt           fastapi, uvicorn, pandas, numpy, requests, psycopg[binary], questdb
│  ├─ main.py                    app factory, CORS, router registration, /health   (~60 lines)
│  └─ routes/
│     ├─ regime.py               GET /api/regime, /api/regime/history, /api/regime/tilts
│     └─ sentiment.py            GET /api/sentiment, /api/sentiment/history
│
├─ core/                         pure, importable by api + worker + mcp. No I/O above db/.
│  ├─ db/
│  │  ├─ rest.py                 /exec → DataFrame, with de-dup defence (§0.1)
│  │  ├─ pg.py                   pg-wire (8812) for the ASOF JOIN point-in-time read
│  │  └─ schema.py               CREATE TABLE IF NOT EXISTS for the two tables we own
│  ├─ series.py                  registry: name → {fred_id, freq, transform, publication_lag_months, axis}
│  ├─ transforms.py              yoy, delta, gamma, zscore, pct_rank — pure functions on Series
│  ├─ align.py                   to_monthly, apply_publication_lag, composite
│  ├─ regime.py                  growth/inflation composites → quadrant + confidence
│  ├─ tilts.py                   quadrant + confidence → All Weather weight deltas
│  └─ sentiment.py               five components → 0-100 composite + label
│
├─ worker/
│  ├─ Dockerfile
│  ├─ requirements.txt
│  ├─ main.py                    APScheduler: extra-series ingest 02:00, recompute 02:30
│  └─ extra_series.py            the §2.2 FRED series → macro_indicators
│
├─ mcp/
│  ├─ requirements.txt           mcp
│  └─ server.py                  get_regime, get_sentiment over stdio
│
├─ frontend/
│  ├─ package.json               react 18, chart.js, react-chartjs-2, lucide-react, vite
│  ├─ vite.config.js             port 3100, host 0.0.0.0, usePolling (copy open-finance's)
│  └─ src/
│     ├─ main.jsx
│     ├─ App.jsx                 two panels; no router until there is a third view
│     ├─ theme.js                copied from open-finance chartTheme.js
│     ├─ components/
│     │  ├─ RegimeScatter.jsx     2D quadrant scatter + trajectory
│     │  ├─ RegimeScatter.css
│     │  ├─ QuadrantLegend.jsx    quadrant names, current call, confidence
│     │  ├─ TiltTable.jsx         baseline vs tilted All Weather weights
│     │  ├─ SentimentGauge.jsx    ported from _to_delete/fear_and_greed
│     │  ├─ SentimentGauge.css
│     │  └─ ComponentBars.jsx     the five sub-scores
│     └─ hooks/
│        └─ useEngine.js          one fetch hook, both endpoints, 5-min poll
│
├─ scripts/
│  ├─ check_data.py              pre-flight: does the DB actually have what we need
│  └─ backfill_history.py        one-off: recompute regime_history + sentiment_index from scratch
│
└─ tests/
   ├─ test_transforms.py         yoy/delta/gamma/pct_rank against hand-computed fixtures
   ├─ test_align.py              publication lag + ffill-only, on synthetic dates
   ├─ test_regime.py             quadrant assignment incl. the near-origin ambiguous case
   └─ test_sentiment.py          composite from known components, label boundaries
```

Note `core/` sits above `api/` rather than inside it, so `worker/` and `mcp/`
import the same maths rather than reimplementing it. That is exactly the
duplication that bit open-finance's backfill logic (two copies that drifted to
different staleness thresholds) — worth not repeating.

### 3.2 The de-dup defence in `core/db/rest.py`

Until §0.1 is fixed, and cheap insurance afterwards:

```python
def macro_series(indicator: str) -> pd.Series:
    """One macro indicator as a clean, sorted, unique-indexed Series."""
    df = query(f"""
        SELECT timestamp, value FROM macro_indicators
        WHERE indicator = '{indicator}' ORDER BY timestamp
    """)
    if df.empty:
        return pd.Series(dtype float)
    s = df.set_index("timestamp")["value"]
    # macro_indicators has no dedup keys and fred_worker re-ingests the full
    # history daily, so identical (timestamp, indicator) rows are the norm.
    # keep="last" also gives us free correct handling of genuine FRED revisions.
    return s[~s.index.duplicated(keep="last")].sort_index()
```

---

## 4. The maths

### 4.1 Dalio 4-quadrant regime

**Framing.** Bridgewater's framework classifies on *growth and inflation
surprising relative to expectations* — i.e. on **change**, not level. An
economy with 2% inflation that is rising behaves like an inflationary regime;
one with 6% inflation that is collapsing behaves like a disinflationary one.
So the quadrant is decided by the **sign of the Delta**, and the levels are
carried alongside as context.

**Step 1 — per-series stationary transform.** From the registry:

| Series type | Transform | Applies to |
|---|---|---|
| Index level | YoY % change | `CPIAUCSL`, `CPILFESL`, `INDPRO`, `PAYEMS`, `M2SL`, `RSAFS` |
| Already a rate | none | `A191RL1Q225SBEA`, `FEDFUNDS`, `T10Y2Y`, `T10YIE`, `DFII10`, `UNRATE` |
| Diffusion index | none | `UMCSENT` |

`A191RL1Q225SBEA` is already an annualised percent change — differencing it
again would yield acceleration, not growth. Easy and common mistake; the
registry's `transform: none` is what prevents it.

**Step 2 — z-score** each transformed series over a trailing **120-month**
window, `min_periods=60`. Trailing (not full-sample) because a full-sample
z-score is look-ahead: it scores 1995 using 2026's variance. This is where
§0.2 bites — with 5 years of FRED history every z-score is `NaN`.

**Step 3 — composites** (mean of available z-scores; explicit equal weights,
tunable in `series.py`):

```
growth_z    = mean(z[INDPRO_yoy], z[PAYEMS_yoy], z[GDP_growth],
                   z[RSAFS_yoy], -z[UNRATE], z[UMCSENT])
inflation_z = mean(z[CPI_yoy], z[CORE_CPI_yoy], z[T10YIE])
```

`UNRATE` enters negated — high unemployment is weak growth. Signs get their own
unit test; a flipped sign here produces a plausible-looking, entirely wrong map.

**Step 4 — Delta and Gamma** (the spec's directive #2):

```
Delta_x = x_z(t) − x_z(t−3)          # 3-month momentum
Gamma_x = Delta_x(t) − Delta_x(t−3)  # acceleration
```

Three months, not one: monthly macro prints are noisy enough that a 1-month
difference flips sign on revisions alone. Three months is short enough to turn
before the regime is over. This is a tunable, and §7 is how we tune it.

**Step 5 — quadrant** from the sign pair:

| Growth Δ | Inflation Δ | Regime | Character |
|---|---|---|---|
| ↑ | ↓ | **Goldilocks** | disinflationary expansion |
| ↑ | ↑ | **Reflation** | inflationary expansion |
| ↓ | ↑ | **Stagflation** | inflationary contraction |
| ↓ | ↓ | **Deflation** | disinflationary contraction |

**Step 6 — confidence, and a fifth label.** A point at
(Δg=+0.04, Δi=−0.02) is *technically* Goldilocks and *actually* undetermined.
Reporting it as a regime call is the main way this kind of dashboard misleads.

```
confidence = min(1.0, hypot(Delta_g, Delta_i) / 1.5)
regime     = "Transition" if confidence < 0.25 else quadrant
```

`1.5` (in composite-z units) and `0.25` are both tunables to be set in §7, not
guessed. The UI renders low confidence as a desaturated marker so "we don't
know" is visually distinct from "we know it's Goldilocks."

**Step 7 — trajectory.** The scatter plots the last 24 monthly points, x=Δg,
y=Δi, connected oldest→newest, opacity ramping with recency, arrowhead at now.
Marker size encodes `hypot(Gamma_g, Gamma_i)` — big marker = the move is
accelerating, small = decaying. That is what Gamma is *for*; a number in a
table would waste it.

**Output row** written to `regime_history`, one per month-end:

```
timestamp, growth_z, inflation_z, growth_delta, inflation_delta,
growth_gamma, inflation_gamma, quadrant SYMBOL, confidence
```

### 4.1b All Weather tilts

Baseline is the published All Weather shape:

| Sleeve | Baseline |
|---|---|
| Equities | 30% |
| Long Treasuries (20y+) | 40% |
| Intermediate Treasuries (7-10y) | 15% |
| Gold | 7.5% |
| Commodities | 7.5% |

The regime applies **± deltas scaled by confidence**, so a Transition call
barely moves the portfolio:

| Sleeve | Goldilocks | Reflation | Stagflation | Deflation |
|---|---|---|---|---|
| Equities | +10 | +2 | −10 | −8 |
| Long Treasuries | −5 | −12 | −10 | +15 |
| Intermediate Treasuries | −2 | −3 | 0 | +5 |
| Gold | −2 | +6 | +10 | −4 |
| Commodities | −1 | +7 | +10 | −8 |

`tilt = baseline + delta × confidence`, renormalised to 100%. Every sleeve
floored at 0.

**This is a research output, not advice.** The UI must say so on the panel, not
in a footnote — the numbers look actionable and that is the risk.

### 4.2 Greed & Fear index

Port from `_to_delete/fear_and_greed/compute_sentiment.py`, fixing three real
defects. Each one currently biases the score in a knowable direction.

**Defect 1 — VIX is double-counted, so it carries ~40% of the score.**
The parked code computes `volatility` from `^VIX` and then `put_call` from
`^VIX` again (labelled "Put/Call Ratio Proxy", and it is not a proxy for the
put/call ratio — it is the same series with a different lookback). With five
equal-weighted components, VIX gets two of the five votes.

Fix: replace `put_call` with **market breadth** — the share of `open-finance`'s
tracked equity tickers trading above their own 125-day moving average,
computed straight from `equity_prices`. Breadth is genuinely independent of
VIX, it is the component CNN's index calls "stock price breadth", and we
already have the data. (Alternative if breadth proves too thin for the European
tickers in `tickers.json`: `^VIX3M / ^VIX` term structure — but that is still
VIX-family, so breadth is preferred.)

**Defect 2 — rolling min/max is not a percentile.**
`normalize_series` scales by `rolling(250).min()` and `.max()`. One outlier
pins the range for a full year: after March 2020, every subsequent VIX reading
looked calm by comparison, so the index read "greed" through a bear market.
The spec asks for *percentiles*; use one.

```python
def pct_rank(s: pd.Series, window: int = 250) -> pd.Series:
    """Percentile rank of each value within its own trailing window, 0-100."""
    return s.rolling(window, min_periods=60).apply(
        lambda w: (w < w.iloc[-1]).mean(), raw=False
    ) * 100
```

**Defect 3 — `resample('D')` counts weekends.**
`.resample('D').last().ffill()` turns 250 trading days into 250 *calendar*
days ≈ 8 months, and forward-fills Saturday and Sunday into the window as
duplicate values, damping every rolling statistic. Fix: stay on the native
trading-day index; no calendar resampling anywhere in the sentiment path.

**Final component set**, all → `pct_rank`, then equal-weighted mean:

| Component | Input | Formula | Inverted |
|---|---|---|---|
| Momentum | `^GSPC` | `(px − MA125) / MA125` | no |
| Volatility | `^VIX` | `vix − MA50(vix)` | **yes** |
| Safe-haven demand | `^GSPC`, `TLT` | `ret20(SPX) − ret20(TLT)` | no |
| Junk-bond demand | `BAMLH0A0HYM2` | OAS level | **yes** |
| Breadth | tracked tickers | `% above own MA125` | no |

Missing component → dropped from the mean, not defaulted to 50. The parked code
substitutes `50.0` on failure, which silently drags the composite toward
neutral and is indistinguishable in the output from a genuinely neutral market.
Return the component count alongside the score instead.

Labels: `<25` Extreme Fear · `<45` Fear · `45–55` Neutral · `<75` Greed ·
`≥75` Extreme Greed. (The parked code used a 50–54 neutral band, which is
oddly asymmetric around 50.)

Written to `sentiment_index`, one row per trading day.

---

## 5. API surface

Port **8100**. CORS open to localhost, as open-finance does.

| Method | Path | Returns |
|---|---|---|
| GET | `/health` | `{status, questdb: bool, last_regime_ts, last_sentiment_ts}` |
| GET | `/api/regime` | current quadrant, confidence, growth/inflation z + Δ + Γ, as-of date |
| GET | `/api/regime/history?months=24` | trajectory points for the scatter |
| GET | `/api/regime/tilts` | baseline weights, deltas, tilted weights, disclaimer string |
| GET | `/api/sentiment` | composite, label, five sub-scores, component count, as-of date |
| GET | `/api/sentiment/history?days=250` | daily composite + sub-scores |

Endpoints only *read* `regime_history` / `sentiment_index`; the worker computes.
No compute on the request path — that is what made open-finance's API restart
hang for minutes (`BACKLOG.md`, "Correctness / data integrity").

`GET /api/regime` is where **`ASOF JOIN`** earns its place (spec directive #1),
over pg-wire on 8812:

```sql
SELECT r.timestamp, r.quadrant, r.confidence,
       r.growth_delta, r.inflation_delta, s.composite AS sentiment
FROM regime_history r
ASOF JOIN sentiment_index s
ORDER BY r.timestamp DESC LIMIT 1;
```

Monthly regime rows against daily sentiment rows, each regime point matched to
the most recent sentiment at or before it — exactly the semantics `ASOF JOIN`
exists for, and awkward to express any other way.

---

## 6. MCP server

`mcp/server.py`, stdio transport, Python `mcp` SDK. Thin: it calls the same
`core/` functions the API does — no third copy of the maths.

| Tool | Args | Returns |
|---|---|---|
| `get_regime` | `as_of?: str` | Quadrant, confidence, both axes with Δ/Γ, and a short prose reading ("growth decelerating, inflation rising — Stagflation, moderate confidence") |
| `get_sentiment` | `as_of?: str` | Composite 0-100, label, five sub-scores, component count |

The prose field matters: an LLM consuming raw z-scores will invent an
interpretation. Better we supply a deterministic one generated from the same
thresholds the UI uses.

Optional later, not in v1: `get_regime_history`, `get_tilts`, `explain_series`.

---

## 7. Validation — the step that decides whether any of this is real

Everything above produces plausible-looking numbers whether or not it is
correct. This stage is not optional, and `BACKLOG.md` makes the case better
than I can: three separate bugs in `portfolioTimeSeries.js` were found only by
manually diffing against expected totals, in code with no tests.

**7.1 Unit tests** on `transforms.py`, `align.py`, `regime.py`,
`sentiment.py` — synthetic inputs, hand-computed expected outputs. Specifically
covering: YoY on a known series, Δ/Γ sign, the `UNRATE` negation, `pct_rank`
against `scipy.stats.percentileofscore`, quadrant assignment at all four sign
combinations, the near-origin Transition case, label boundary values.

**7.2 Historical face validity.** Run the classifier over full FRED history
and check it against periods no reasonable framework should get wrong:

| Period | Expected | Test |
|---|---|---|
| 2008-09 → 2009-06 | Deflation | majority of months |
| 2020-03 → 2020-05 | Deflation | growth Δ deeply negative |
| 2020-09 → 2021-12 | Reflation | majority of months |
| 2022-03 → 2022-12 | Stagflation | growth Δ < 0, inflation Δ > 0 |
| 2013 → 2015 | Goldilocks | majority of months |
| 1979-1981 | Stagflation | if history extends that far |

If the classifier calls 2022 "Goldilocks", the window lengths or the composite
weights are wrong — and this table is how we find out, not the dashboard.
**This is also how §4.1's tunables (3-month Δ window, 120-month z-window, the
1.5 and 0.25 confidence constants) get set** — grid-search them against this
table rather than picking round numbers, which is what I have done above.

**7.3 Sentiment sanity.** Composite should sit below 20 in Mar 2020, Oct 2008
and Mar 2009, and above 80 in late 2017 and late 2021. And it should *not*
read "greed" through H2 2020 — that specific failure is what defect 2 causes.

---

## 8. Build order

Each stage ends somewhere you can stop and see something real.

| Stage | Work | Done when |
|---|---|---|
| **0** | Backbone prerequisites: rotate FRED key → `.env`; dedup `macro_indicators`; extend FRED history to 1960; run `scripts/check_data.py` | `check_data.py` reports every required series present with sufficient history |
| **1** | Project skeleton, `.env`, compose on the external network, `core/db/*`, `core/series.py`, `core/transforms.py`, `core/align.py`, tests 7.1 | `pytest` green; a script prints growth/inflation composites for the last 24 months |
| **2** | `worker/extra_series.py` — the six new FRED series + four new tickers | new indicators queryable in QuestDB |
| **3** | `core/regime.py`, `core/db/schema.py`, `scripts/backfill_history.py` | `regime_history` populated back to the 1960s; §7.2 table passes |
| **4** | `api/main.py` + `routes/regime.py`; worker's nightly recompute | `curl :8100/api/regime` returns the current call |
| **5** | `core/sentiment.py` + `routes/sentiment.py`, ported with the three fixes | §7.3 passes; `sentiment_index` populated |
| **6** | Frontend: scatter, quadrant legend, gauge, component bars, tilt table | dashboard on :3100, styled consistently with :3000 |
| **7** | `mcp/server.py`, both tools | `get_regime` / `get_sentiment` callable from Claude Code |
| **8** | `README.md` system-shape doc | someone (you, in three months) can pick it up cold |

Stages 0-3 are the substance. If the regime series does not pass §7.2, nothing
downstream is worth building, so the ordering front-loads the risk deliberately.

---

## 9. Open questions

1. **`macro_indicators` shared write** — recommending we append new
   `indicator` symbols to open-finance's table (§1). Say the word and it
   becomes a separate table instead.
2. **Country scope.** Every series above is US. Barents is a European
   reinsurer; if the intended use is European exposure, the inflation and
   growth axes should be euro-area (`CP0000EZ19M086NEST`, euro-area IP, ECB
   deposit facility rate) — a different series registry, same engine. Worth
   deciding before Stage 2, cheap now and annoying later. A two-region version
   (US + EA, side-by-side quadrants) is also viable if you want both.
3. **The four new tickers** (`GLD`, `DBC`, `TIP`, `^VIX3M`) will be tracked in
   open-finance's `api/tickers.json`, so they will appear in its portfolio UI
   ticker list. Acceptable, or should regime_mapping keep its own registry?
4. **Publication lag** (§2.3, rule 3) adds real complexity for the sake of
   honest historical validation. Confirm you want it — the alternative is
   reference-date stamping with a clear "not point-in-time" caveat on the
   history chart, which is simpler and fine if §7.2 is the only backtest we
   ever run.
5. **Is `regime_mapping` a git repo of its own?** The folder is currently
   empty and untracked. Assuming yes, with its own `.gitignore` — and given
   §0.3, a private repo.

---

## 10. Immediate next step

Run `scripts/check_data.py` (delivered alongside this plan) against your local
QuestDB. It is read-only and needs nothing built. It reports:

- whether QuestDB is reachable and which tables exist
- row counts and **duplicate counts** per macro indicator (confirming §0.1)
- earliest and latest observation per indicator (confirming §0.2)
- which of the §2.2 series and tickers are missing
- history depth per sentiment-input ticker

Its output tells us whether Stage 0 is an afternoon or a day, and it is the
one thing I cannot determine from here — this session's network sandbox blocks
the bridge to your QuestDB.


---

# Appendix — what changed during the build

Written 2026-08-21, after Stages 0-8. The plan above is left as written; this
records where the build diverged from it and why, so the two can be read
together.

## Corrections to the plan's own maths

**1. `Delta` cannot be the difference of the z-score.** Section 4.1 step 4
specified `Delta_x = x_z(t) − x_z(t−3)`. That is wrong, and wrong in the worst
way — it inverts the sign on any sustained move. With both the mean and the
standard deviation trailing, differencing the z-score differences the
normalisation too; once a move occupies a meaningful share of the window the
growing denominator outruns the falling numerator. Measured on the synthetic
scenarios, it reports growth **accelerating** through a collapse from +2% to
−2%.

The build divides an undifferenced scale into a differenced level instead:

```
Delta_x = (x(t) − x(t−3)) / rolling_std(x)(t)
```

Units become "standard deviations of the axis' own level, per quarter", which
is also more interpretable than the plan's version. `core/align.normalise`
carries the full reasoning and
`tests/test_align.py::test_normalise_delta_keeps_the_sign_of_the_underlying_move`
guards it in both directions — it asserts both that the fix works and that the
naive version still fails, so if the trap ever stops being a trap the test
says so rather than quietly passing.

Four independent scenario families across five noise seeds each, plus 65 years
of history-shaped synthetic data, all classify correctly under the fix and
mis-classify under the plan's version.

**2. The confidence threshold needed splitting in two.** Section 4.1 step 6
had `FULL_CONFIDENCE_RADIUS = 1.5` and `CONFIDENCE_FLOOR = 0.25`, which made
the real decision boundary — how big a move counts as a regime — an implicit
product of two constants. The build uses `CALL_RADIUS = 0.30` (the actual
boundary, in axis sd per quarter) and `FULL_CONFIDENCE_RADIUS = 1.2`, with the
floor derived. Two sweeps set it, and they pull in opposite directions; the
comment block in `core/regime.py` has both tables.

**3. "Goldilocks 2013-2015" is a level claim, not a momentum claim.** Section
7.2 listed 2013-2015 as a Goldilocks window. On a momentum reading those years
were becalmed — median momentum radius 0.19 on the historical fixture, below
`CALL_RADIUS` — so the model correctly declines to call them. The window in
`scripts/validate_history.py` is now the 2014-15 oil crash, where inflation
genuinely fell fast while growth firmed. The same correction narrows two other
windows: H2 2022 was disinflationary by momentum (CPI peaked in June), and 1981
was disinflationary despite a high level.

This is a property of the framework worth stating plainly to anyone reading the
dashboard, so it is in `README.md` rather than only here.

## Structural changes

- **`mcp/` renamed to `mcp_server/`.** The server puts the project root on
  `sys.path`, so a directory called `mcp` shadows the installed MCP SDK and the
  import fails with `'mcp.server' is not a package`.
- **`core/` sits above `api/`**, as planned, and `worker/recompute.py` is the
  single entry point both the nightly job and `scripts/backfill_history.py`
  call — no second copy of the orchestration.
- **`worker/extra_series.py` ingests incrementally**, asking the database what
  it already has and re-fetching a 400-day revision window. The plan implied a
  full re-fetch. Incremental keeps it correct whether or not patch 0003 has
  been applied, and picks up FRED back-revisions either way.
- **`scripts/validate_history.py --grid` ranks on `hit_rate × decided`,** not
  hit rate alone. Ranking on accuracy alone recommends a setting that calls
  only the two obvious crises and stays silent for 70% of history — accurate,
  and not a regime map.

## Design decisions the plan left open

- **Quadrant colour.** Section 3 assumed a categorical palette per quadrant. No
  four-hue set passes an all-pairs colour-blindness check against this dark
  surface — not even the four hues `open-finance` already ships, nor the
  reference palette's own first four slots. Since a quadrant *is* a region of
  the plane, position already carries the identity: the build uses labelled
  background regions and a single-series trajectory on a one-hue recency ramp.
- **The fear/greed scale is blue-to-orange, not red-to-green.** Emerald against
  rose scores ΔE 5.5 under deuteranopia, below even the
  with-secondary-encoding floor. Blue-to-orange scores 30.5.
- **The sentiment `put_call` component is gone**, replaced by real market
  breadth as planned — but note the remaining volatility component measures VIX
  against its own 50-day average, so it reads volatility *momentum*, not level.
  That is parity with CNN's index and with the parked code, and it means a
  market sitting at VIX 35 for six months reads neutral.

## Found by actually running the frontend

Three bugs the test suite could not have caught, all fixed:

- **Integers were being serialised as floats.** `df.iloc[-1]` and
  `iterrows()` both collapse a mixed-dtype frame to a single dtype, so an
  int64 component count came back as `5.0` and the UI would have read "5.0 of
  5 components". `tests/test_api.py` had asserted `== 5`, which `5.0`
  satisfies — the replacement asserts `isinstance(..., int)`.
  `api/reads.last_row` and `api/serialise.frame` now preserve per-column types.
- **`/health` was fetched as `/api/health`.** The health route sits at the
  root, and the frontend's one fetch helper prefixed everything with `/api`.
  404 in the console, no visible symptom until the demo banner needed it.
- **A globally registered Chart.js plugin drew on every chart.**
  `Chart.register(quadrantBackground)` is global, so the regime scatter's
  quadrant tints and a stray "REFLATION" label rendered across the sentiment
  history panel. Both custom plugins are now passed per-chart via
  react-chartjs-2's `plugins` prop.

The first two were only visible in a browser; the third was only visible in a
screenshot. Worth remembering the next time a change here looks safe because
`pytest` is green.

## What is still not verified

Calibration. Every number in this project has been checked against synthetic
data and none against the real economy, because this session had no network
route to FRED or to the QuestDB instance. `scripts/validate_history.py` is the
check that matters and it needs to be run locally. Until it has been, treat the
tuned constants as placeholders that pass their own tests.
