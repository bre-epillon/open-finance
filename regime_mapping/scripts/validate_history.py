#!/usr/bin/env python3
"""Historical face validity, and the grid search that sets the tunables.

IMPLEMENTATION_PLAN.md section 7.2. This is the step that decides whether the
regime engine is real: it produces plausible-looking numbers either way, and
the only way to tell is to check it against periods no reasonable framework
should get wrong.

Reads macro_indicators directly and rebuilds the regime frame in memory, so it
never touches regime_history and is safe to run against a live stack.

    python scripts/validate_history.py             # score the current settings
    python scripts/validate_history.py --grid      # search the tunables
    python scripts/validate_history.py --csv out.csv

If the classifier calls 2022 "Goldilocks", the settings are wrong -- and this
is where that surfaces, not on the dashboard.
"""

import argparse
import itertools
import logging
import os
import sys

import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core import regime as R
from core import transforms as T
from core.db.rest import QueryError, macro_frame
from core.series import GROWTH, INFLATION, REGISTRY

logging.basicConfig(level=logging.WARNING)

# Periods where the regime is not seriously disputed ON A MOMENTUM READING.
# That qualifier matters, and the windows are narrower than the popular names
# for the same episodes because of it:
#
#   * CPI peaked in June 2022 and fell after, so by momentum H2 2022 was
#     disinflationary contraction rather than stagflation.
#   * Inflation peaked in March 1980, so 1981 was disinflationary even though
#     the level was still high.
#   * "Goldilocks 2013-2015" describes LEVELS -- decent growth, inflation
#     below target -- not momentum. Those years were genuinely becalmed and
#     the model should decline to call them; the 2014-15 oil crash is the
#     window where inflation was actually falling fast.
#
# Dates allow for the publication lag, so the model's call turns a month or
# two after the reference data does.
EXPECTED = [
    ("1978-09", "1980-09", R.STAGFLATION, "second oil shock into recession"),
    ("2008-11", "2009-09", R.DEFLATION, "GFC: growth and prices collapsing"),
    ("2014-09", "2015-09", R.GOLDILOCKS, "oil crash: inflation down, growth firm"),
    ("2020-05", "2020-09", R.DEFLATION, "COVID shutdown"),
    ("2020-12", "2021-10", R.REFLATION, "reopening boom, inflation building"),
    ("2022-02", "2022-08", R.STAGFLATION, "inflation peak, growth slowing"),
]

AXIS_NAMES = [s.name for s in REGISTRY.values() if s.axis in (GROWTH, INFLATION)]


def score(frame: pd.DataFrame) -> tuple[pd.DataFrame, float]:
    """Per-period hit rates, and the coverage-weighted overall rate."""
    rows, hits, total = [], 0, 0
    for start, end, expected, why in EXPECTED:
        window = frame.loc[start:end]
        n = len(window)
        if n == 0:
            rows.append({"period": f"{start}..{end}", "expected": expected,
                         "months": 0, "hit_rate": None, "transition": None,
                         "top_call": "no data", "note": why})
            continue
        calls = window["quadrant"]
        hit = int((calls == expected).sum())
        trans = int((calls == R.TRANSITION).sum())
        # Transition is not a wrong answer, only an unhelpful one, so the
        # denominator excludes it -- otherwise raising the confidence floor
        # would look like it degrades accuracy when it only reduces coverage.
        decided = n - trans
        rows.append({
            "period": f"{start}..{end}", "expected": expected, "months": n,
            "hit_rate": round(hit / decided, 3) if decided else None,
            "transition": round(trans / n, 3),
            "top_call": calls.value_counts().idxmax(), "note": why,
        })
        hits += hit
        total += decided
    return pd.DataFrame(rows), (hits / total if total else 0.0)


def build(raw, diff_periods, window, min_periods, radius):
    """Rebuild with one parameter set.

    CALL_RADIUS is a module constant that label() reads through
    CONFIDENCE_FLOOR, so both are swapped for the duration and restored in a
    finally -- a grid search that leaked its last setting into the process
    would silently mis-tune everything after it.
    """
    original = (R.CALL_RADIUS, R.CONFIDENCE_FLOOR)
    R.CALL_RADIUS = radius
    R.CONFIDENCE_FLOOR = radius / R.FULL_CONFIDENCE_RADIUS
    try:
        return R.build(raw, diff_periods=diff_periods, window=window,
                       min_periods=min_periods)
    finally:
        R.CALL_RADIUS, R.CONFIDENCE_FLOOR = original


def report(raw, args) -> int:
    frame = build(raw, args.diff_periods, args.window, args.min_periods,
                  args.radius)
    if frame.empty:
        print("Regime frame is empty. Almost always insufficient FRED history "
              "-- apply patches/0002 and re-run scripts/check_data.py.")
        return 1

    print(f"\nRegime history: {frame.index[0].date()} to "
          f"{frame.index[-1].date()} ({len(frame)} months)")
    print(f"Settings: diff_periods={args.diff_periods} window={args.window} "
          f"min_periods={args.min_periods} call_radius={args.radius}")
    print(f"Latest call: {frame.iloc[-1]['quadrant']} "
          f"(confidence {frame.iloc[-1]['confidence']:.2f})\n")

    table, overall = score(frame)
    with pd.option_context("display.width", 200, "display.max_colwidth", 44):
        print(table.to_string(index=False))
    print(f"\nOverall hit rate on decided months: {overall:.1%}")
    print(f"Distribution of all calls:\n"
          f"{frame['quadrant'].value_counts().to_string()}")

    if args.csv:
        frame.to_csv(args.csv)
        print(f"\nFull frame written to {args.csv}")

    if overall < 0.6:
        print("\nBelow 60%: do not build anything on top of this yet. Try "
              "--grid, and check the component signs in core/series.py.")
        return 1
    return 0


def grid(raw, args) -> int:
    """Search the tunables against the EXPECTED table.

    This is what IMPLEMENTATION_PLAN.md section 4.1 promised instead of
    picking round numbers: the defaults in core/transforms.py and
    core/regime.py were set from the synthetic sweep in tests/, and real macro
    noise is not synthetic noise.
    """
    combos = list(itertools.product(args.grid_diff, args.grid_window,
                                    args.grid_radius))
    print(f"Searching {len(combos)} combinations...\n")
    results = []
    for dp, w, rad in combos:
        mp = min(args.min_periods, w // 2)
        frame = build(raw, dp, w, mp, rad)
        if frame.empty:
            continue
        table, overall = score(frame)
        decided = float((frame["quadrant"] != R.TRANSITION).mean())
        results.append({
            "diff": int(dp), "window": int(w), "radius": rad,
            "hit_rate": round(overall, 3),
            "decided": round(decided, 3),
            # Neither column is useful alone: a model that only ever calls the
            # two obvious crises scores ~100% on nothing, and one that calls
            # every month scores near chance. The product is the trade-off.
            "balance": round(overall * decided, 3),
            "months": len(frame),
        })

    if not results:
        print("Every combination produced an empty frame -- not enough FRED "
              "history. Apply patches/0002.")
        return 1

    df = pd.DataFrame(results).sort_values("balance", ascending=False)
    print(df.head(20).to_string(index=False))

    top = df.iloc[0]
    accurate = df.sort_values("hit_rate", ascending=False).iloc[0]
    fmt = lambda r: (f"diff={int(r['diff'])} window={int(r['window'])} "
                     f"radius={r['radius']:g}")
    print(f"\nBest balance: {fmt(top)} -> {top['hit_rate']:.1%} accurate on "
          f"{top['decided']:.1%} of months")
    if accurate["balance"] < top["balance"]:
        print(f"Most accurate: {fmt(accurate)} -> "
              f"{accurate['hit_rate']:.1%} accurate, but on only "
              f"{accurate['decided']:.1%} of months")
    print("\nRead hit_rate and decided together, which is what `balance` "
          "does. A high hit rate on a small decided share means the model "
          "calls the two obvious crises and stays quiet the rest of the "
          "time -- accurate, and not a regime map.")
    print("\nTo adopt a setting, edit DIFF_PERIODS / Z_WINDOW in "
          "core/transforms.py and CALL_RADIUS in core/regime.py, then re-run "
          "pytest: the synthetic sweeps there are documented against the "
          "current values and will need their comments updated.")
    return 0


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--diff-periods", type=int, default=T.DIFF_PERIODS)
    p.add_argument("--window", type=int, default=T.Z_WINDOW)
    p.add_argument("--min-periods", type=int, default=T.Z_MIN_PERIODS)
    p.add_argument("--radius", type=float, default=R.CALL_RADIUS)
    p.add_argument("--csv", help="write the full regime frame here")
    p.add_argument("--grid", action="store_true")
    p.add_argument("--grid-diff", type=int, nargs="+", default=[1, 3, 6, 12])
    p.add_argument("--grid-window", type=int, nargs="+", default=[60, 120, 240])
    p.add_argument("--grid-radius", type=float, nargs="+",
                   default=[0.20, 0.30, 0.375, 0.45, 0.60],
                   help="CALL_RADIUS values to try, in axis sd per quarter")
    args = p.parse_args()

    try:
        raw = macro_frame(AXIS_NAMES)
    except QueryError as e:
        print(f"Cannot read QuestDB: {e}")
        return 1
    if not raw:
        print("No macro data found. Is the open-finance stack running?")
        return 1
    print(f"Loaded {len(raw)} series: {', '.join(sorted(raw))}")

    return grid(raw, args) if args.grid else report(raw, args)


if __name__ == "__main__":
    sys.exit(main())
