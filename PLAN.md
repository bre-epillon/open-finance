# Plan — auth, per-user data, and the instrument catalogue

Written 2026-08-22. Covers the work agreed after `regime_mapping` landed:
a shared auth service, per-user transaction storage, demo data for anonymous
visitors, and a real instrument search to replace the exact-ticker text box.

Companion documents:

| File | Scope |
|---|---|
| `REFACTORING.md` | Open items from the frontend cleanup. Its **P0** section is still the thing to read before anything is exposed to a network. |
| `BACKLOG.md` | Historical record, 2026-08-18/19. Superseded where the two overlap. |
| `regime_mapping/README.md` | The regime engine, end to end. Accurate; read it before touching `core/`. |
| `regime_mapping/patches/README.md` | The three backbone patches. **0002 is now applied** (see Phase 0). |

Decisions already made, so they are not re-litigated below: own FastAPI auth
service (not an off-the-shelf IdP, not a managed provider); Postgres for
relational data; the two frontends stay separate apps with synced tokens
rather than a shared package.

---

## Phase 0 — done 2026-08-22

- **`regime_mapping` is a subdirectory of `open-finance`, deliberately.** Two
  deployables, one repo: they share a database, a house style, and from Phase 2
  an auth service. `regime_mapping/docker-compose.yml` still joins
  `open-finance_default` as an external network, which is unaffected by the
  nesting because compose derives that name from the parent directory.

- **Nine files from `regime_mapping` had leaked into `open-finance/frontend/src`**
  — `theme.js`, `hooks/useEngine.js`, and seven components (`RegimeCall`,
  `RegimeScatter`, `SentimentGauge`, `SentimentHistory`, `ComponentBars`,
  `TiltTable`, `quadrantPlugin`). All byte-identical to the regime copies and
  all dead: `theme.js` was imported only by the other leaked files, so the
  cluster referenced nothing outside itself. Moved to
  `_to_delete/misplaced_regime_components/`. Proof they were dead: the
  open-finance bundle is byte-identical before and after removal — same 1558
  modules, same hashes.

- **Eleven more `regime_mapping` files had leaked into `open-finance`'s Python
  tree** -- `api/__init__.py`, `api/main.py`, `api/reads.py`, `api/serialise.py`,
  the three files under `api/routes/`, and `worker/__init__.py`,
  `worker/extra_series.py`, `worker/recompute.py`, `worker/tickers.py`. All
  byte-identical to the regime copies. This set was worse than the frontend one:
  regime's `api/main.py` sitting beside open-finance's `api/api.py` invites
  `uvicorn api.main:app` in the wrong tree, and the stray `__init__.py` files
  turn `api/` and `worker/` into packages, which changes how their own modules
  resolve imports. Moved to `_to_delete/misplaced_regime_python/`.
  open-finance's own `api/api.py`, `worker/main.py` and
  `worker/corporate_actions.py` were verified untouched.

- **Design tokens synced.** `regime_mapping`'s `--surface-0/1/2`,
  `--ink-1/2/3`, `--line`, `--sans`, `--mono` were renamed to open-finance's
  vocabulary (`--bg-base/surface/card`, `--text-primary/secondary/muted`,
  `--border-color`, `--font-sans/mono`) and two values that had already drifted
  were corrected (`--bg-card` was `#151d31` against `#121a30`; the border alpha
  was `0.08` against `0.07`). Both sheets now name
  `open-finance/frontend/src/App.css` as the authority in a comment. The seven
  `INK` values in `regime_mapping/frontend/src/theme.js` were verified equal to
  those in `open-finance/frontend/src/utils/chartTheme.js`.

- **Backbone patch 0002 applied.** The FRED key is out of both
  `fred_worker/main.py` and `docker-compose.yml`; the worker now refuses to
  start without `FRED_API_KEY` rather than falling back to a committed
  credential; `observation_start` moved from *today − 5 years* to `1960-01-01`,
  which is what makes a trailing 120-month z-score possible at all. Added
  `.env.example` at the repo root (verified `.env` is gitignored and
  `.env.example` is not).

- **`mcp` pinned below 2.0** in `regime_mapping/requirements.txt`. A fresh
  `pip install -r` resolved to `mcp` 2.0.0, which removed
  `mcp.server.fastmcp`; `mcp_server/server.py` then failed to import and took
  the whole suite down at collection. Verified: 191 tests pass on 1.29.0, hard
  collection error on 2.0.0. Migrating to the 2.x API is a follow-up, not a
  reason to remove the pin.

- **Amended 2026-08-22 (same day): the 1960 start date was wrong.** QuestDB's
  ILP protocol rejects a negative designated timestamp, and a pre-epoch row
  aborts the *entire* series rather than being skipped. `regime_worker`'s first
  run proved it: `Timestamp -315619200000000000 is negative. It must be >= 0`
  killed `PAYEMS` and `CPILFESL` outright. Left as-is, patch 0002 would have
  done the same to four of `fred_worker`'s eight series — `CPIAUCSL` (1947),
  `UNRATE` (1948), `FEDFUNDS` (1954), `M2SL` (1959). Both workers now start at
  `1970-01-01`, skip any pre-epoch row defensively, and pass timezone-aware UTC
  timestamps (which also clears a questdb 4.x naive-datetime warning). 1970 still
  leaves 55 years against a 120-month window. Guarded by
  `tests/test_worker_resilience.py`.

- **`regime_worker` no longer abandons the recompute after one failure.** Its
  own `register_all()` asks open-finance to track the All Weather sleeve proxies,
  which starts several concurrent multi-decade yfinance backfills; the recompute
  then runs straight into them and lost — five tickers accepted at 15:19:44, read
  timeout at 15:20:44, recompute abandoned at 15:22:27, next attempt 02:00 the
  following day. Now 4 attempts with 60s/180s/420s backoff.

### Still manual, still outstanding

- [ ] **Rotate the FRED key.** Patch 0002 removed it from the code; it is still
      live and still in git history and on GitHub. Revoke at
      <https://fredaccount.stlouisfed.org/apikeys>, create a new one, put it in
      `.env`. Nothing else in this plan depends on it, and it takes two minutes.
- [ ] **Apply patch 0003** (`macro_indicators` deduplication) *before* the
      first `fred_worker` run after 0002. Without it, the widened history
      appends ~65 years of rows per night instead of upserting. It contains a
      `DROP TABLE`; run it statement by statement in the QuestDB console with
      the verification step in between, exactly as `patches/README.md` says.
- [ ] **Two empty directories** could not be removed from this side (the bridge
      cannot delete, only move): `regime_mapping/_to_delete/` and
      `open-finance/api/routes/`. Delete both locally -- the second one
      especially, since an `api/routes/` in open-finance implies a route package
      that does not exist there.
- [ ] **`_to_delete/`** now also holds `misplaced_regime_components/` and
      `regime_zips/`. Review and delete.

---

## Phase 1 — Postgres, running without Docker

Docker is unavailable on the current machine, so Postgres has to run natively
here and in a container on the server. Both are supported from one
`DATABASE_URL`.

### Getting Postgres up locally

The recommended route is the official Windows installer — it runs as a service,
survives reboots, and matches the server exactly:

1. Install PostgreSQL 16 (<https://www.postgresql.org/download/windows/>),
   accepting the default port 5432.
2. Create the database and role:

   ```sql
   CREATE ROLE litefi WITH LOGIN PASSWORD 'change-me';
   CREATE DATABASE litefi OWNER litefi;
   \c litefi
   CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()
   CREATE EXTENSION IF NOT EXISTS pg_trgm;    -- instrument search
   ```
3. `DATABASE_URL=postgresql://litefi:change-me@localhost:5432/litefi` in `.env`.

A `postgres:16` service goes into `docker-compose.yml` for the server, with a
named volume and the same two extensions created by an init script.

**On a SQLite fallback:** it is tempting and it is a trap. The schema below uses
`UUID`, `JSONB`, `NUMERIC`, `TEXT[]`, `TIMESTAMPTZ`, real foreign keys and a
trigram index. Supporting SQLite means either giving all of that up or
maintaining two DDL files that will drift — which is the failure mode this repo
has already been bitten by twice (the duplicated backfill logic, and the design
tokens fixed in Phase 0). One dialect. Install Postgres.

### New files

```
core_db/                    shared by every service that touches Postgres
  __init__.py
  pool.py                   psycopg3 connection pool, read DATABASE_URL once
  migrate.py                applies numbered .sql files, records them
  migrations/
    001_auth.sql
    002_portfolio.sql
    003_instruments.sql
scripts/
  init_db.py                idempotent: create extensions, run migrations
  run_local.py              start every service with uvicorn, no Docker
```

`core_db/` sits at the repo root, not inside either project — `open-finance`'s
API, the auth service and (later) `regime_mapping` all import it. Plain SQL
through psycopg3; no ORM. `migrate.py` is ~60 lines: read `migrations/*.sql` in
order, skip what `schema_migrations` already records, run the rest in one
transaction each.

`scripts/run_local.py` is the answer to "no Docker here": one plain Python
process that reads `.env` and supervises `uvicorn` for the auth service,
open-finance's API and regime's API, restarting any that die and prefixing their
logs. It replaces the parts of `C:\ofvenvs\portfolio_app.sh` that start Python
services; QuestDB and Postgres stay as they are, started independently.

---

## Phase 2 — the auth service

A new `auth/` FastAPI app on **:8200**. It owns identity and nothing else.

### Token design

Access tokens are **RS256 JWTs**, 15-minute lifetime, never stored. Refresh
tokens are opaque 256-bit random strings, 30-day lifetime, stored **as a
SHA-256 hash** so a database read cannot mint a session.

RS256 rather than a shared HS256 secret, because it is the difference between
"the other services can *verify* a token" and "the other services can *issue*
one". The auth service holds the private key; open-finance's API and regime's
API get only the public key, from `/auth/.well-known/jwks.json`, cached. That
matters more once these are separate containers on a server.

Both tokens travel as cookies: `HttpOnly`, `SameSite=Lax`, `Secure` in
production, `Path=/`. Not `localStorage` — a single XSS in either dashboard
would otherwise hand over a bearer token.

Cookies are scoped by **host**, not port, so `localhost:3000` and
`localhost:3100` share a session automatically: logging into one dashboard logs
you into the other, locally, with no extra work. On the server, put both apps
under one parent domain and set `Domain=.your-host` to keep that property.

Because sessions ride on cookies, every state-changing request needs CSRF
protection: a `csrf` cookie (readable) plus an `X-CSRF-Token` header the
frontend echoes back, compared server-side. `SameSite=Lax` alone is not enough
for a POST from a third-party page.

### Schema — `001_auth.sql`

```sql
CREATE TABLE users (
  id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  email          TEXT        NOT NULL UNIQUE,   -- stored lowercased
  email_verified BOOLEAN     NOT NULL DEFAULT FALSE,
  password_hash  TEXT,                          -- NULL for Google-only accounts
  display_name   TEXT,
  created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  last_login_at  TIMESTAMPTZ,
  disabled_at    TIMESTAMPTZ
);

-- One row per federated login. Separate from users so one person can have both
-- a password and Google on the same account, and so a second provider later is
-- an INSERT and not a migration.
CREATE TABLE identities (
  id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id       UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider      TEXT NOT NULL,                  -- 'google'
  subject       TEXT NOT NULL,                  -- provider's stable 'sub'
  email_at_link TEXT,
  created_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (provider, subject)
);

-- Refresh sessions. Access tokens are stateless and absent here by design.
CREATE TABLE sessions (
  id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id      UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  refresh_hash TEXT NOT NULL UNIQUE,            -- sha256(refresh token)
  issued_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at   TIMESTAMPTZ NOT NULL,
  revoked_at   TIMESTAMPTZ,
  rotated_from UUID REFERENCES sessions(id),
  user_agent   TEXT,
  ip           INET
);
CREATE INDEX sessions_user_active ON sessions (user_id) WHERE revoked_at IS NULL;

-- Single-use tokens for email verification and password reset, hashed.
CREATE TABLE one_time_tokens (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  purpose    TEXT NOT NULL CHECK (purpose IN ('verify_email','reset_password')),
  token_hash TEXT NOT NULL UNIQUE,
  expires_at TIMESTAMPTZ NOT NULL,
  used_at    TIMESTAMPTZ
);

-- Login throttling. Cheap, and it lives with the data it protects.
CREATE TABLE login_attempts (
  id         BIGSERIAL PRIMARY KEY,
  email      TEXT,
  ip         INET,
  succeeded  BOOLEAN NOT NULL,
  at         TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX login_attempts_recent ON login_attempts (email, at DESC);
```

Passwords are hashed with **Argon2id** (`argon2-cffi`), not bcrypt: no 72-byte
truncation, and memory-hard. Parameters go in one named constant with the
tuning noted beside them.

### Endpoints

| Method | Path | Notes |
|---|---|---|
| POST | `/auth/signup` | email + password. Always returns 201, even if the email exists — otherwise the endpoint is an account-enumeration oracle. Sends a verification mail if SMTP is configured. |
| POST | `/auth/login` | Sets both cookies. Throttled per email and per IP. Timing-equalised so a missing user and a wrong password take the same time. |
| POST | `/auth/refresh` | Rotates: old session revoked, new issued, `rotated_from` set. Reuse of an already-rotated token revokes the whole chain — that is how stolen-refresh-token replay is detected. |
| POST | `/auth/logout` | Revokes the current session, clears cookies. |
| GET | `/auth/me` | The current user, or 401. |
| GET | `/auth/google/start` | 302 to Google with PKCE + `state` in a short-lived cookie. |
| GET | `/auth/google/callback` | Verifies `state` and the ID token, links or creates, sets cookies, redirects back to the app. |
| POST | `/auth/password/forgot` | Always 202. |
| POST | `/auth/password/reset` | Consumes a one-time token. |
| GET | `/auth/.well-known/jwks.json` | Public key for the other services. |

**Google setup** (yours to do, ~5 minutes): create an OAuth 2.0 Client ID
(type: Web application) at <https://console.cloud.google.com/apis/credentials>,
authorised redirect URI `http://localhost:8200/auth/google/callback`, then put
`GOOGLE_CLIENT_ID` / `GOOGLE_CLIENT_SECRET` in `.env`. The email/password path
works without them; the Google button renders disabled with a tooltip when they
are absent, rather than failing on click.

An important account-linking rule: a Google login whose verified email matches
an existing password account **links to it**. Matching on an *unverified* email
would let anyone who can create a Google account with your address take over
your account, so the `email_verified` claim is checked, not just `email`.

### Frontend — both apps

Kept as duplicated-but-synced code, consistent with the Phase 0 decision. In
each app:

```
src/auth/
  AuthProvider.jsx      context: user, loading, login, signup, logout
  useAuth.js
  AuthButton.jsx        header: "Sign in" or the user's initials + a menu
  AuthDialog.jsx        modal: email/password tabs + "Continue with Google"
  auth.css
```

`AuthProvider` is the one exception to "no Context until three components need
it" in `Architecture.md`: the header, the route guards and the data hooks all
need the session, which is three.

Design comes from the existing token set — `.panel`, `.form-input`,
`.form-submit-btn` and the `--series-*` palette already carry it, so the dialog
should need almost no new CSS. The Google button follows Google's branding
requirements (their mark, correct wording, minimum size); those rules are
enforced at review time for published apps, so it is worth getting right once.

---

## Phase 3 — per-user data, uploads, and demo mode

Today `frontend/src/parsed_transactions.json` and its three siblings are
**bundled into the JavaScript at build time**. That is both the blocker for
multi-user and an unresolved P0 in `REFACTORING.md`: the built bundle contains
real transaction history, so anyone served the app is served the data.

### Schema — `002_portfolio.sql`

```sql
CREATE TABLE uploads (
  id         UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id    UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  filename   TEXT NOT NULL,
  sha256     TEXT NOT NULL,
  bytes      INTEGER NOT NULL,
  status     TEXT NOT NULL CHECK (status IN ('pending','parsed','failed')),
  row_counts JSONB,
  error      TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  -- Re-uploading a file already imported is a no-op rather than a duplicate.
  UNIQUE (user_id, sha256)
);

CREATE TABLE transactions (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id     UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  upload_id   UUID REFERENCES uploads(id) ON DELETE SET NULL,  -- NULL = manual
  external_id TEXT,                       -- Trade Republic's own id
  isin        TEXT,
  ticker      TEXT NOT NULL,
  name        TEXT,
  trade_date  DATE NOT NULL,
  side        TEXT NOT NULL CHECK (side IN ('BUY','SELL')),
  quantity    NUMERIC(24,10) NOT NULL CHECK (quantity > 0),
  price       NUMERIC(24,10) NOT NULL CHECK (price >= 0),
  fee         NUMERIC(18,4)  NOT NULL DEFAULT 0,
  currency    TEXT NOT NULL DEFAULT 'EUR',
  created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (user_id, external_id)            -- idempotent re-import
);
CREATE INDEX transactions_user_date ON transactions (user_id, trade_date);

-- Splits already applied, per transaction. Was an `adjustedSplits` array on the
-- localStorage object; a table means the tagging survives a re-import.
CREATE TABLE transaction_splits_applied (
  transaction_id UUID NOT NULL REFERENCES transactions(id) ON DELETE CASCADE,
  effective_date DATE NOT NULL,
  PRIMARY KEY (transaction_id, effective_date)
);
```

`bond_transactions`, `cash_movements` and `income_payments` mirror the shapes
of `state_bonds.json`, `cash_deposits.json` and `interest_payments.json`. Note
that `quantity` is `CHECK (quantity > 0)` with the direction carried by `side`:
the Trade Republic export uses a negative quantity on sells, and
`portfolioTimeSeries.js` and `usePortfolio.js` both defend against that with
`Math.abs()` in two places. Normalising at the boundary removes a whole class
of sign bug — one of the three that `BACKLOG.md` records finding by hand.

### `parse_csv.py` becomes a library

Today it is a script that writes four JSON files into `frontend/src/`. It keeps
that CLI, but the parsing moves into a function that returns records, so the
upload endpoint and the CLI share one implementation. Splitting it is also
already on the list — 246 lines, over the cap.

### Endpoints (open-finance API, :8000)

| Method | Path | Notes |
|---|---|---|
| POST | `/api/portfolio/uploads` | multipart CSV. Validates, hashes, parses, inserts, returns per-category counts and anything skipped. |
| GET | `/api/portfolio/uploads` | Import history. |
| GET | `/api/portfolio/transactions` | The caller's own rows. Demo rows when anonymous. |
| POST/PATCH/DELETE | `/api/portfolio/transactions[/{id}]` | Manual entry, replacing the localStorage path. |
| GET | `/api/portfolio/summary` | Optional later: move the heavy series work server-side. |

Every one of these filters by `user_id` taken **from the verified token**, never
from a request parameter. That single rule is the whole of the authorisation
model, and it is worth a test per endpoint asserting that user A cannot read
user B's rows by any combination of arguments.

### Demo mode

Anonymous visitors get a committed synthetic portfolio — `api/demo/*.json`,
generated once by a script, ~20 months and ~10 positions, shaped to exercise
every panel (a closed position, a partial sell, bonds, dividends, a drawdown).
Not a copy of anyone's real data.

The frontend shows a persistent banner while unauthenticated: *"Sample data —
sign in to see your own portfolio."* `regime_mapping` already does exactly this
for `demo: true` in `/health`, and its reasoning applies here verbatim: a
screenshot outlives the terminal it was taken from, so the page should say on
its face whether the figures are real.

`usePortfolio` stops importing JSON and fetches instead. localStorage drops to
a cache with the user id in the key — otherwise signing out and in as someone
else on a shared machine shows the previous person's positions.

---

## Phase 4 — the instrument catalogue and ticker UX

The current box needs an exact Yahoo symbol, gives no confirmation of what was
matched, and reports nothing while a backfill runs. Three separate problems.

Good news: `transactions/parse_csv.py` already resolves ISINs through
**OpenFIGI** and probes Yahoo for price coverage (`_openfigi_lookup`,
`build_ticker_map`, `_has_price_data`). The catalogue is that logic, promoted
from a one-shot import step to a queryable table. No new dependency.

### Schema — `003_instruments.sql`

```sql
CREATE TABLE instruments (
  ticker         TEXT PRIMARY KEY,        -- Yahoo symbol, e.g. 'SXR8.DE'
  isin           TEXT,
  figi           TEXT,
  name           TEXT NOT NULL,           -- 'iShares Core S&P 500 UCITS ETF'
  short_name     TEXT,
  share_class    TEXT,                    -- 'Acc' / 'Dist' / 'Class A'
  exchange       TEXT,                    -- 'XETRA'
  exchange_name  TEXT,                    -- 'Xetra (Frankfurt)'
  currency       TEXT,                    -- 'EUR'
  country        TEXT,
  asset_class    TEXT,                    -- equity|etf|bond|crypto|index
  tracked        BOOLEAN NOT NULL DEFAULT FALSE,
  first_price_at DATE,
  last_price_at  DATE,
  price_rows     INTEGER,
  refreshed_at   TIMESTAMPTZ,
  search_text    TEXT                     -- lower(name || ticker || isin)
);
CREATE INDEX instruments_search ON instruments USING gin (search_text gin_trgm_ops);
CREATE INDEX instruments_isin ON instruments (isin);
```

`share_class`, `exchange` and `currency` together are what make *"Apple Class C
USD"* distinguishable from *"Apple Class A EUR"* — the readability problem you
described. They come from OpenFIGI (`securityDescription`, `exchCode`) and
yfinance metadata (`longName`, `currency`, `exchange`, `quoteType`).

`price_rows` / `first_price_at` / `last_price_at` are refreshed from QuestDB
(`select ticker, count(), min(timestamp), max(timestamp) from equity_prices
group by ticker`) so the UI can warn *before* you track something that Yahoo
has 14 days of history for — which is exactly the situation `REFACTORING.md`
records silently understating unrealised gains.

### Ingestion progress

```sql
CREATE TABLE ingest_jobs (
  id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  ticker      TEXT NOT NULL,
  requested_by UUID REFERENCES users(id) ON DELETE SET NULL,
  stage       TEXT NOT NULL,   -- queued|resolving|fetching|writing|done|failed
  rows_written INTEGER NOT NULL DEFAULT 0,
  first_bar   DATE,
  last_bar    DATE,
  message     TEXT,
  started_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);
```

`shared/backfill.py` writes stage transitions as it goes. That is the fix for
"the logging messages are a bit scarce": the UI can then say *"Fetching daily
bars from Yahoo… 4,210 rows written, 1998-01-02 → 2026-08-21"* and finish with
a real completion, instead of an optimistic *"Backfilling in progress"* that
never updates.

### Endpoints

| Method | Path | Notes |
|---|---|---|
| GET | `/api/instruments/search?q=` | Trigram + prefix ranked. Matches name, ticker or ISIN, so pasting an ISIN from a broker statement works. |
| GET | `/api/instruments/{ticker}` | Full detail including price coverage. |
| POST | `/api/track` | Unchanged path, now returns an `ingest_jobs.id`. |
| GET | `/api/ingest/{job_id}` | Poll for stage and row count. |

### `TickerSelector` / `TickerTracker`

The text input becomes a search field with a results list:

```
  AAPL          Apple Inc.                        NASDAQ · USD    ✓ tracked
                11,438 daily bars · 1980-12-12 → 2026-08-21

  APC.F         Apple Inc.                        Frankfurt · EUR
                2,104 daily bars · 2015-03-02 → 2026-08-21

  SXR8.DE       iShares Core S&P 500 UCITS (Acc)  XETRA · EUR     ✓ tracked
```

Selecting an untracked row asks to confirm — *"Track APC.F — Apple Inc.
(Frankfurt, EUR)?"* — which is the *"ticker X corresponds to company Y on
market Z"* confirmation you asked for, placed where the mistake would otherwise
happen. Then the row shows live ingestion progress from `/api/ingest/{id}`.

The same component then answers a question it cannot answer today: which of two
Apple listings you are actually looking at.

---

## Phase 5 — deployment hardening

Not optional once this leaves localhost, and cheaper to do alongside Phase 2
than after.

- [ ] **TLS.** Caddy in front of everything (automatic certificates, trivial
      config). `Secure` cookies do not work without it, and without `Secure` the
      session travels in clear.
- [ ] **CORS pinned** to the two real origins in all three APIs. Both currently
      run `allow_origins=["*"]`, which is fine for single-user localhost and
      unacceptable next to a login form.
- [ ] **Ticker input validation** before it reaches an f-string SQL query
      (`/api/data`, `/api/corporate_actions`). QuestDB's REST API has no
      parameter binding, so a `^[A-Z0-9.\-^]{1,12}$` check *is* the fix.
- [ ] **Frontend served built**, not by `vite dev` with HMR polling — a
      two-stage Dockerfile serving `dist/` from Caddy.
- [ ] **Rate limits** on `/auth/*` and the upload endpoint.
- [ ] **Backups.** `pg_dump` on a schedule. QuestDB holds re-fetchable market
      data; Postgres will hold the only copy of someone's transaction history.
- [ ] **Scrub the git history** or keep the repo private — the seed JSONs, both
      Trade Republic CSVs and the old FRED key are all still in it.
- [ ] **Say what you keep.** Once other people's financial records are in your
      database, a short privacy note and a working account-deletion path
      (`ON DELETE CASCADE` is already in the schema for this reason) stop being
      niceties. If anyone in the EU other than you uses it, that is GDPR
      territory: lawful basis, retention, export, erasure. I am not a lawyer and
      this is not legal advice — worth 30 minutes with someone who is before
      you invite users.

---

## Suggested order, and why

1. **Phase 1** (Postgres + `core_db` + `run_local.py`) — everything else needs
   somewhere to write. Small, self-contained, no user-visible change.
2. **Phase 2** (auth service + both frontends) — the largest single piece.
   Reviewable on its own: sign up, sign in, sign out, Google, refresh.
3. **Phase 3** (uploads, per-user data, demo mode) — needs 1 and 2. This is
   where the bundled-JSON P0 finally dies.
4. **Phase 4** (instruments + ingestion progress) — independent of 2 and 3
   apart from `requested_by`. If you would rather have the daily quality-of-life
   win first, this can be pulled ahead of Phase 2; only the `ingest_jobs`
   user column has to wait.
5. **Phase 5** — alongside 2, finished before anything is exposed.

One thing worth flagging as genuinely bigger than it looks: **Phase 2 makes you
a custodian of other people's credentials and financial records**, which is a
different thing from a personal dashboard. The hardening list above is the
minimum, not a wish list.

**Phase 3's safety net is now in place.** That phase changes what
`usePortfolio` is — from a hook over bundled JSON with a localStorage cache to a
hook over an authenticated API — underneath a value engine that had no tests. As
of 2026-08-22 it has 50 (`npm test` in `frontend/`), covering the accounting
identity, all three bugs previously found by hand, and the deposit-is-not-a-gain
rule. Mutation-checked: each guarded behaviour, broken by hand, fails its test.
Run them before and after the data source moves — a diff in those numbers is the
signal that the migration changed a result rather than just a source.
