"""The worker's two failure modes, both observed in the wild on 2026-08-22.

1. A pre-epoch FRED observation aborted the whole series, not just that row,
   so PAYEMS and CPILFESL went missing from the regime axes entirely.
2. A single QuestDB read timeout abandoned the recompute for 24 hours, leaving
   both computed tables absent and the dashboard reading "No regime history
   yet" until 02:00 the following day.

Both are cheap to guard and expensive to rediscover.
"""

import datetime

import pytest

from worker import extra_series, main as worker_main
from core.series import ours_to_ingest

# A real spec from the registry rather than a hand-built one: fetch() only reads
# .fred_id, and using the real thing means this test cannot drift out of step
# with the dataclass's fields.
SPEC = ours_to_ingest()[0]


class _Resp:
    def __init__(self, payload, status=200):
        self._payload, self.status_code, self.text = payload, status, ""

    def json(self):
        return self._payload


def _observations(*pairs):
    return {"observations": [{"date": d, "value": v} for d, v in pairs]}


# ---------------------------------------------------------------- pre-epoch
def test_history_start_is_not_before_the_unix_epoch():
    """QuestDB's ILP protocol rejects a negative designated timestamp."""
    start = datetime.date.fromisoformat(extra_series.HISTORY_START)
    assert start >= datetime.date(1970, 1, 1)


def test_fetch_drops_pre_epoch_rows_instead_of_losing_the_series(monkeypatch):
    monkeypatch.setattr(extra_series, "FRED_API_KEY", "x")
    monkeypatch.setattr(extra_series.requests, "get", lambda *a, **k: _Resp(
        _observations(("1939-01-01", "1.0"),   # pre-epoch: must be dropped
                      ("1969-12-31", "2.0"),   # pre-epoch: must be dropped
                      ("1970-01-01", "3.0"),   # the boundary: must be kept
                      ("2020-01-01", "4.0"))))

    rows = extra_series.fetch(SPEC, "1900-01-01")

    # The series survives with its post-epoch observations, rather than the
    # whole fetch aborting the way it did against 1960-01-01.
    assert [v for _, v in rows] == [3.0, 4.0]
    assert all(ts >= extra_series.EPOCH for ts, _ in rows)


def test_fetch_returns_timezone_aware_timestamps(monkeypatch):
    """questdb 4.x warns that a naive datetime is read as UTC; be explicit."""
    monkeypatch.setattr(extra_series, "FRED_API_KEY", "x")
    monkeypatch.setattr(extra_series.requests, "get",
                        lambda *a, **k: _Resp(_observations(("2020-01-01", "1.0"))))

    (ts, _), = extra_series.fetch(SPEC, "2020-01-01")
    assert ts.tzinfo is not None
    assert ts.utcoffset() == datetime.timedelta(0)


def test_fetch_still_drops_fred_missing_markers(monkeypatch):
    monkeypatch.setattr(extra_series, "FRED_API_KEY", "x")
    monkeypatch.setattr(extra_series.requests, "get", lambda *a, **k: _Resp(
        _observations(("2020-01-01", "."), ("2020-02-01", ""), ("2020-03-01", "5.0"))))

    assert [v for _, v in extra_series.fetch(SPEC, "2020-01-01")] == [5.0]


# ------------------------------------------------------------------- retries
def test_recompute_succeeding_first_time_does_not_sleep(monkeypatch):
    calls = []
    monkeypatch.setattr(worker_main.recompute, "run_all",
                        lambda: calls.append(1) or {"regime": 5, "sentiment": 5})
    monkeypatch.setattr(worker_main.time, "sleep",
                        lambda s: pytest.fail("slept on a first-attempt success"))

    worker_main._recompute_with_retry()
    assert len(calls) == 1


def test_recompute_retries_a_transient_timeout_then_succeeds(monkeypatch):
    # The real shape of the incident: QuestDB is busy with the backfills that
    # ticker registration just triggered, then frees up.
    attempts = {"n": 0}
    slept = []

    def flaky():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise RuntimeError("QuestDB unreachable: Read timed out")
        return {"regime": 780, "sentiment": 6300}

    monkeypatch.setattr(worker_main.recompute, "run_all", flaky)
    monkeypatch.setattr(worker_main.time, "sleep", slept.append)

    worker_main._recompute_with_retry()

    assert attempts["n"] == 3
    assert slept == list(worker_main.RECOMPUTE_BACKOFF_SECONDS[:2])


def test_recompute_gives_up_after_the_last_attempt_without_raising(monkeypatch):
    """A dead database must not kill the scheduler -- tomorrow's run should
    still happen."""
    attempts = {"n": 0}

    def always_fails():
        attempts["n"] += 1
        raise RuntimeError("QuestDB unreachable")

    monkeypatch.setattr(worker_main.recompute, "run_all", always_fails)
    monkeypatch.setattr(worker_main.time, "sleep", lambda s: None)

    worker_main._recompute_with_retry()          # must not raise
    assert attempts["n"] == worker_main.RECOMPUTE_ATTEMPTS


def test_backoff_table_covers_every_retry():
    """One wait per retry: attempts - 1 of them."""
    assert len(worker_main.RECOMPUTE_BACKOFF_SECONDS) == worker_main.RECOMPUTE_ATTEMPTS - 1
    assert list(worker_main.RECOMPUTE_BACKOFF_SECONDS) == sorted(
        worker_main.RECOMPUTE_BACKOFF_SECONDS), "backoff should not shrink"


def test_nightly_recomputes_even_when_the_fred_ingest_fails(monkeypatch):
    """Stale macro data is still worth a regime call; the two stages are
    independent."""
    monkeypatch.setattr(worker_main.extra_series, "run_once",
                        lambda: (_ for _ in ()).throw(RuntimeError("FRED down")))
    ran = []
    monkeypatch.setattr(worker_main.recompute, "run_all",
                        lambda: ran.append(1) or {"regime": 1, "sentiment": 1})

    worker_main.nightly()
    assert ran == [1]
