# Stage 0 — backbone patches

Three fixes to `open-finance` that `regime_mapping` depends on. Apply in
order. Nothing here is applied automatically; review each one first.

Paths below are relative to the `open-finance` repo root.

---

## 0001 — rotate the FRED API key  (do this first, by hand)

`05f6f0ba0a0347f8cb544300570ad8de` is committed in plaintext in
`docker-compose.yml` and as the `os.getenv` default in `fred_worker/main.py`,
and `BACKLOG.md` records that this repo was pushed to
`github.com/bre-epillon/open-finance`.

1. Log in at <https://fredaccount.stlouisfed.org/apikeys> and **revoke** that
   key, then create a new one.
2. Create `open-finance/.env` (gitignored — verify with `git check-ignore .env`):

   ```
   FRED_API_KEY=<the new key>
   ```

3. Apply patch `0002`, which removes both plaintext copies.

Note that revoking does not remove the old key from git history. That is a
separate `git filter-repo` job; the key being dead makes it harmless.

---

## 0002 — fred_worker: read key from env, extend history to 1960

    cd open-finance
    git apply --check patches/0002-fred-worker.patch   # dry run
    git apply           patches/0002-fred-worker.patch

Two changes:

- `FRED_API_KEY` has no default. A missing key now raises at startup instead
  of silently authenticating as someone else's revoked key.
- `observation_start` goes from `today - 365*5` to `1960-01-01`. This is what
  makes a trailing 120-month z-score possible at all; with 5 years of history
  quarterly real GDP has ~20 observations and every z-score is `NaN`.

The compose file change is in the same patch: `FRED_API_KEY` is read from the
environment (`${FRED_API_KEY}`) rather than hardcoded, and `env_file: .env` is
added to the `fred_worker` service.

**Apply 0003 before restarting the worker**, or the first run after this patch
will insert ~65 years of observations into a table that still has no
deduplication keys.

---

## 0003 — macro_indicators: stop duplicating every row daily

`macro_indicators` was never given a `CREATE TABLE`; the ILP `Sender`
auto-created it, so it has no `DEDUPLICATE UPSERT KEYS`. `fred_worker` then
re-fetches and re-inserts the full observation window every night at 01:30.
Every observation is stored once per day the worker has run.

Run `scripts/check_data.py` first to see the current multiple. Then work
through `0003-macro-dedup.sql` **statement by statement** in the QuestDB web
console at <http://localhost:9000> — it contains a `DROP TABLE`, and the
verification step between the copy and the drop is the whole point. Do not
paste the file in one go.

Stop `fred_worker` for the duration:

    docker compose stop fred_worker
    # ... run 0003-macro-dedup.sql ...
    docker compose up -d fred_worker

`regime_mapping`'s own read path (`core/db/rest.py`) de-duplicates defensively
regardless, so it is correct either way — but every *other* consumer of that
table, including anything you write in the QuestDB console, is not.
