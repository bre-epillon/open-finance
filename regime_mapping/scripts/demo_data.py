"""Synthetic macro and price history, shaped like the real record.

SYNTHETIC. Every number here is invented. It exists so the dashboard and the
regime engine can be exercised without a database -- for frontend work, for
`scripts/demo_server.py`, and as the fixture behind
`tests/test_history_scenarios.py`.

Do not read any output derived from this as a statement about the economy.

Kept here rather than in tests/ because two callers need it, and a second copy
is how open-finance ended up with two backfill implementations that drifted to
different staleness thresholds.
"""

import numpy as np
import pandas as pd

MONTHLY = pd.date_range("1960-01-31", "2026-08-31", freq="ME")

# (date, value) anchors, linearly interpolated between. Approximate US CPI
# year-over-year and real GDP growth, in percent.
INFLATION = [
    ("1960-01", 1.5), ("1965-01", 1.6), ("1970-01", 5.9), ("1974-12", 11.0),
    ("1976-12", 5.0), ("1980-03", 13.5), ("1983-06", 3.2), ("1986-12", 1.9),
    ("1990-12", 5.4), ("1994-06", 2.6), ("2000-06", 3.4), ("2002-06", 1.6),
    ("2006-06", 3.2), ("2008-07", 5.6), ("2009-07", -2.1), ("2011-09", 3.9),
    ("2013-06", 1.5), ("2014-06", 2.1), ("2015-06", 0.1), ("2018-06", 2.4),
    ("2020-01", 2.3), ("2020-05", 0.1), ("2021-09", 5.4), ("2022-06", 9.1),
    ("2023-06", 3.0), ("2024-12", 2.9),
    # 2025 onward is an invented scenario, not a forecast: inflation
    # re-accelerating while growth fades, so the dashboard has a live regime
    # call and a non-zero portfolio tilt to show rather than sitting on
    # Transition with an all-baseline table.
    ("2025-06", 2.6), ("2026-02", 3.8), ("2026-08", 4.8),
]

GROWTH = [
    ("1960-01", 2.5), ("1962-06", 6.1), ("1966-06", 6.6), ("1970-06", 0.2),
    ("1973-06", 5.6), ("1975-06", -0.5), ("1978-06", 5.5), ("1980-06", -0.3),
    ("1982-12", -1.8), ("1984-06", 7.2), ("1987-06", 3.5), ("1991-03", -0.1),
    ("1995-06", 2.7), ("1999-06", 4.8), ("2001-09", 0.2), ("2004-06", 3.9),
    ("2007-06", 2.0), ("2009-06", -3.9), ("2010-06", 2.6), ("2013-01", 1.4),
    ("2015-06", 2.9), ("2018-06", 3.0), ("2020-01", 2.2), ("2020-04", -8.0),
    ("2020-09", -2.0), ("2021-04", 12.0), ("2021-12", 5.7), ("2022-09", 1.4),
    ("2023-06", 2.4), ("2024-12", 2.8),
    ("2025-06", 2.5), ("2026-02", 1.2), ("2026-08", 0.0),
]

# Month-to-month wiggle, in percentage points. Real CPI year-over-year moves
# ~0.3pp between prints from seasonal and energy noise alone. A near-noiseless
# fixture is not a gentler test, it is a different one: linear ramps between
# distant anchors have tiny 3-month momentum, so almost every month would land
# on Transition for reasons the real series would not.
NOISE_SD = 0.32


def _path(anchors, seed, noise=NOISE_SD, index=MONTHLY):
    """Anchors -> a monthly path with independent noise."""
    at = pd.Series(
        {pd.Timestamp(d) + pd.offsets.MonthEnd(0): v for d, v in anchors},
        dtype="float64")
    out = at.reindex(at.index.union(index)).interpolate("time").reindex(index)
    return out + np.random.default_rng(seed).normal(0.0, noise, len(index))


def _jitter(seed, sd=NOISE_SD, index=MONTHLY):
    return np.random.default_rng(seed).normal(0.0, sd, len(index))


def _level_from_yoy(yoy_path, start=100.0):
    """An index level whose year-over-year rate follows yoy_path.

    Compounds month by month at the annualised rate given for that month, so a
    caller can specify the economics it wants -- inflation falling from 6% to
    1% -- and get a level series the registry's 'yoy' transform reproduces it
    from.
    """
    rates = (1.0 + np.asarray(yoy_path, dtype="float64") / 100.0) ** (1.0 / 12.0)
    return start * np.cumprod(rates)


def macro(index=MONTHLY) -> dict[str, pd.Series]:
    """Raw macro series keyed by core.series registry name."""
    infl = _path(INFLATION, 1, index=index)
    grow = _path(GROWTH, 2, index=index)
    mk = lambda v: pd.Series(np.asarray(v, dtype="float64"), index=index)
    j = lambda s, sd=NOISE_SD: _jitter(s, sd, index)
    return {
        # Growth axis. Industrial production and retail sales run hotter than
        # GDP; payrolls lag and run cooler; unemployment moves the other way.
        "Industrial_Production": mk(_level_from_yoy(grow * 1.4 + j(11))),
        "Nonfarm_Payrolls": mk(_level_from_yoy(grow * 0.5 + 0.3 + j(12, 0.1))),
        "Retail_Sales": mk(_level_from_yoy(grow * 1.1 + infl * 0.4 + j(13))),
        "GDP_Growth": mk(grow + j(14, 0.2)),
        "Unemployment": mk(6.0 - grow * 0.6 + j(15, 0.15)),
        "Consumer_Sentiment": mk(88.0 + grow * 3.0 - infl * 1.5 + j(16, 2.0)),
        # Inflation axis.
        "Inflation_CPI": mk(_level_from_yoy(infl)),
        "Core_CPI": mk(_level_from_yoy(infl * 0.8 + 0.4 + j(17, 0.15))),
        "Breakeven_10Y": mk(infl * 0.55 + 1.0 + j(18, 0.2)),
    }


# --- daily market data, for the sentiment index ---------------------------

DAILY = pd.bdate_range("2019-01-02", "2026-08-21")


def _walk(n, seed, drift, vol):
    steps = np.random.default_rng(seed).normal(drift, vol, n)
    return np.cumprod(1.0 + steps)


def prices(index=DAILY) -> pd.DataFrame:
    """^GSPC, ^VIX and TLT. Includes a drawdown, so the gauge has something
    other than the middle of its range to show."""
    n = len(index)
    spx = 2500.0 * _walk(n, 21, 0.00035, 0.009)
    # A 15% slide over the last four months, so the demo lands in fear rather
    # than parked at neutral.
    tail = min(85, n)
    spx[-tail:] *= np.linspace(1.0, 0.85, tail)

    # VIX inverse to equity momentum, floored, with its own noise.
    ret20 = pd.Series(spx, index=index).pct_change(20).fillna(0.0).to_numpy()
    vix = np.clip(17.0 - ret20 * 160.0
                  + np.random.default_rng(22).normal(0, 1.6, n), 9.0, 80.0)

    tlt = 95.0 * _walk(n, 23, 0.00002, 0.006)
    return pd.DataFrame({"^GSPC": spx, "^VIX": vix, "TLT": tlt}, index=index)


def universe(n_names=26, index=DAILY) -> pd.DataFrame:
    """Breadth constituents. Correlated with the index, individually noisy."""
    n = len(index)
    market = pd.Series(prices(index)["^GSPC"]).pct_change().fillna(0.0).to_numpy()
    rng = np.random.default_rng(24)
    cols = {}
    for i in range(n_names):
        beta = 0.6 + rng.random() * 0.9
        idio = rng.normal(0.0, 0.011, n)
        cols[f"DEMO{i:02d}"] = 100.0 * np.cumprod(1.0 + market * beta + idio)
    return pd.DataFrame(cols, index=index)


def junk_spread(index=DAILY) -> pd.Series:
    """High-yield option-adjusted spread, widening as equities fall."""
    spx = prices(index)["^GSPC"]
    ret60 = spx.pct_change(60).fillna(0.0)
    noise = np.random.default_rng(25).normal(0.0, 0.12, len(index))
    return (3.4 - ret60 * 9.0 + noise).clip(lower=2.2)
