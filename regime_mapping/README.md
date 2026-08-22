# regime_mapping

A Ray Dalio 4-quadrant macro regime map and a Greed & Fear sentiment index,
computed from the QuestDB instance owned by `open-finance`, the parent
project this directory lives inside.

Python / FastAPI + plain JSX, matching `open-finance`'s stack rather than the
TypeScript the original spec called for — the two projects share a database and
a house style, and a second toolchain buys nothing.

---

## What it does

**Macro regime.** Builds a growth axis and an inflation axis from nine US FRED
series, measures each axis' 3-month momentum (Δ) and acceleration (Γ), and
names the quadrant from the two Δ signs:

|  | Inflation Δ falling | Inflation Δ rising |
|---|---|---|
| **Growth Δ rising** | Goldilocks | Reflation |
| **Growth Δ falling** | Deflation | Stagflation |

Below a minimum momentum the call is **Transition** rather than a quadrant —
about half of all months, because macro momentum is genuinely small most of the
time. A regime map that always names a regime is not being more useful, it is
being less honest.

**Sentiment.** A 0-100 composite of five percentile-ranked components: S&P 500
momentum, VIX against its own 50-day average, safe-haven demand, high-yield
credit spreads, and market breadth.

**Portfolio tilt.** The All Weather weights the regime implies, scaled by
confidence. Research output, not advice — and the code says so in every
response that carries the numbers.

---

## Where this lives

`regime_mapping/` is a subdirectory of the `open-finance` repository, not a
sibling. The two share a database, a house style, and (from Phase 2) an auth
service, so they are one repo with two deployables. `docker-compose.yml` here
still joins `open-finance_default` as an external network -- compose derives
that name from the *parent* directory, which is unaffected by this project
being nested.

## System shape

```
                       QuestDB (owned by open-finance)
                  9000 REST  ·  8812 pg-wire  ·  9009 ILP
                                    │
        ┌───────────────────────────┼───────────────────────────┐
        │                           │                           │
   equity_prices              macro_indicators        regime_history
   (open-finance)          (open-finance + us)        sentiment_index
                                                            (us)
        └───────────────────────────┼───────────────────────────┘
                                    │
   ┌────────────────┬───────────────┴────────┬───────────────────┐
   │ regime_worker  │      regime_api        │   mcp_server      │
   │ nightly 02:00  │      :8100 REST        │   stdio           │
   │ ingest + calc  │      read-only         │   read-only       │
   └────────────────┴───────────┬────────────┴───────────────────┘
                                │
                        regime_frontend :3100
```

| Table | Written by | Read by |
|---|---|---|
| `equity_prices`, `equity_prices_intraday`, `corporate_actions` | open-finance | both |
| `macro_indicators` | open-finance's `fred_worker` **and** our `worker/extra_series.py` | both |
| `regime_history`, `sentiment_index` | us only | us only |

Additive share on `macro_indicators`: we append new `indicator` symbols and
never touch the eight `fred_worker` owns.

`sentiment_index`, not `sentiment_history` — the parked
`open-finance/_to_delete/fear_and_greed/compute_sentiment.py` opens with
`DROP TABLE IF EXISTS sentiment_history`, and a different name means running
that old script can never destroy ours.

### Directories

| Path | What lives there |
|---|---|
| `core/` | The maths. Takes pandas objects in and out; talks to no database except through `core/db/`. |
| `core/db/` | QuestDB access: REST for bulk reads, pg-wire for the one `ASOF JOIN`, ILP for writes. |
| `api/` | FastAPI on :8100. Reads the computed tables; never recomputes. |
| `worker/` | Nightly FRED ingest and recompute. |
| `mcp_server/` | MCP tools for Claude Code. **Not** `mcp/` — that name shadows the installed SDK. |
| `frontend/` | Vite + React dashboard on :3100. |
| `scripts/` | `check_data.py`, `backfill_history.py`, `validate_history.py`. |
| `patches/` | Three fixes to `open-finance` that this project depends on. |
| `tests/` | 188 tests. `pytest` from the project root. |

---

## Setting it up

```bash
cp .env.example .env      # then put a NEW FRED key in it — see patches/README.md
pip install -r requirements-dev.txt
```

**1. Apply the backbone patches first.** `patches/README.md` has the detail.
In short: rotate the FRED key (the committed one is public), extend FRED
history from 5 years to 1960, and give `macro_indicators` deduplication keys.
Without the second of those, every trailing z-score is `NaN` and the regime
table comes out empty.

**2. Check what the database actually holds.**

```bash
python scripts/check_data.py        # read-only
```

**3. Populate the two computed tables.**

```bash
python scripts/backfill_history.py --register
```

`--register` also asks open-finance to track the All Weather sleeve proxies —
`GLD`, `DBC`, `IEF` and `^VIX3M` (`SPY` and `TLT` it already has) — which its
own chunked backfill then fills in.

**4. Check the model against history.** This is the step that decides whether
any of it is worth looking at:

```bash
python scripts/validate_history.py            # score the current settings
python scripts/validate_history.py --grid     # tune them
```

**5. Run it.**

```bash
docker network ls | grep default   # confirm the network name first
docker compose up -d --build
```

Then <http://localhost:3100>, with the API on <http://localhost:8100/health>.

### Seeing the dashboard before the database is ready

```bash
python scripts/demo_server.py          # API on :8100, synthetic data
cd frontend && npm install && npm run dev
```

Computes both tables in memory from `scripts/demo_data.py` and serves them
through the real API — every route, label, tilt and serialiser runs as it does
in production; only `core/db` is bypassed. `/health` reports `demo: true` and
the dashboard shows an orange banner saying so, because a screenshot outlives
the terminal it was taken from.

`python scripts/demo_server.py --print` dumps every endpoint's payload instead
of serving, which is the quickest way to see the response shapes.

**MCP:**

```bash
claude mcp add regime -- python /abs/path/to/regime_mapping/mcp_server/server.py
```

---

## Two things to know before reading the dashboard

**Quiet years get no call.** The framework classifies on *momentum*, which is
Dalio's framing — inflation at 2% and rising behaves like an inflationary
regime; 6% and collapsing behaves like a disinflationary one. A consequence
catches people out: "Goldilocks 2013-2015" is a statement about *levels*
(decent growth, inflation below target), not momentum. Those years were
becalmed, so the model reports Transition through most of them. That is
correct, and it is not what someone expecting a label per month will assume.

**Δ is not the difference of a z-score.** It looks like it should be, and it is
the first thing anyone would write. It also inverts the sign on any sustained
move: with both the mean and the standard deviation trailing, differencing the
z-score differences the normalisation too, and once a move occupies a
meaningful share of the window the growing denominator outruns the falling
numerator. Measured on the synthetic scenarios, `delta(zscore(x))` reports
growth *accelerating* through a collapse from +2% to −2%. `core/align.normalise`
divides an undifferenced scale into a differenced level instead, and
`tests/test_align.py::test_normalise_delta_keeps_the_sign_of_the_underlying_move`
guards the trap in both directions.

---

## Testing

```bash
python -m pytest tests/ -q      # 188 tests, ~17s, no database needed
```

Everything runs against fixtures: synthetic macro paths, a stub QuestDB REST
endpoint, and an in-memory table store behind the API and MCP layers. What the
suite verifies is that the machinery is sound — transforms, publication lags,
signs, quadrant logic, serialisation, error paths.

What it cannot verify is calibration against the real economy.
`tests/test_history_scenarios.py` drives 65 years of history-shaped synthetic
data through the whole chain and scores 91.9% on six windows where the regime
is not seriously disputed, but the inputs are built from the same anchors the
test asserts against. `scripts/validate_history.py` against live FRED data is
the check that means something.

The defaults in `core/transforms.py` and `core/regime.py` were tuned on
synthetic sweeps, which is better than round numbers and worse than real data.
Both places document the sweep that set them. Re-run `--grid` before trusting
them.

---

## Known open questions

- **Calibration is untuned against real data.** Everything above.
- **US only.** Every series is US. For a European book the growth and inflation
  axes should be euro-area — a second registry in `core/series.py` behind the
  same engine.
- **Coverage.** At the shipped `CALL_RADIUS` about half of all months get a
  quadrant. Whether that is the right trade against spurious calls is a
  judgement `--grid` informs but cannot make.
- **The volatility component measures momentum, not level.** VIX against its
  own 50-day average, at parity with CNN's index — so a market sitting at
  VIX 35 for six months reads as neutral. Intended, and surprising.
