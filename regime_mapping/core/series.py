"""The macro series registry -- the single place that says what each FRED
series is and how it enters the model.

Everything downstream is driven by this table: what to ingest, what transform
to apply, how long to wait before a value counts as known, and which axis it
feeds with what sign. Adding an indicator means adding a row here, not editing
the engine.

US series only. A euro-area registry would be a second dict with the same
shape and the same engine behind it -- see IMPLEMENTATION_PLAN.md section 9.
"""

from dataclasses import dataclass

GROWTH = "growth"
INFLATION = "inflation"
POLICY = "policy"
SENTIMENT = "sentiment"


@dataclass(frozen=True)
class MacroSeries:
    """One FRED series and its role in the model.

    name        symbol used in the macro_indicators.indicator column
    fred_id     FRED series ID
    freq        native publication frequency: D, M or Q
    transform   'yoy' for index levels, 'none' for things already in rate form
    lag_months  publication lag -- see the note below
    axis        which composite it feeds, or POLICY/SENTIMENT for context only
    sign        +1, or -1 where a rise in the series means a fall in the axis
    weight      relative weight inside its axis composite
    """

    name: str
    fred_id: str
    freq: str
    transform: str
    lag_months: int
    axis: str
    sign: int = 1
    weight: float = 1.0


# Publication lag, in months, between a value's reference date and the date it
# was actually knowable. FRED stamps observations at the reference date, so
# without this shift any historical run of the model is reading a newspaper
# from the future -- CPI for March is not public until mid-April, and Q1 GDP
# not until late April. Daily market series carry lag 0 because they are
# prices. UMCSENT carries 0 because the final reading lands inside its own
# reference month.

REGISTRY: dict[str, MacroSeries] = {
    # ---- growth axis ----------------------------------------------------
    # Two hard monthly output/labour reads, one quarterly national-accounts
    # read, one demand read, one labour-slack read, one survey. GDP alone
    # cannot drive a monthly series; the monthly pair is what makes the axis
    # move between quarters.
    "Industrial_Production": MacroSeries(
        "Industrial_Production", "INDPRO", "M", "yoy", 1, GROWTH),
    "Nonfarm_Payrolls": MacroSeries(
        "Nonfarm_Payrolls", "PAYEMS", "M", "yoy", 1, GROWTH),
    "GDP_Growth": MacroSeries(
        # Already an annualised percent change -- differencing it again would
        # give acceleration, not growth. transform='none' is load-bearing.
        "GDP_Growth", "A191RL1Q225SBEA", "Q", "none", 2, GROWTH),
    "Retail_Sales": MacroSeries(
        "Retail_Sales", "RSAFS", "M", "yoy", 1, GROWTH),
    "Unemployment": MacroSeries(
        # Negated: rising unemployment is weakening growth. A flipped sign
        # here yields a plausible-looking, entirely wrong map, so
        # tests/test_regime.py asserts it directly.
        "Unemployment", "UNRATE", "M", "none", 1, GROWTH, sign=-1),
    "Consumer_Sentiment": MacroSeries(
        # Half weight: a survey, and the softest input on the axis.
        "Consumer_Sentiment", "UMCSENT", "M", "none", 0, GROWTH, weight=0.5),

    # ---- inflation axis -------------------------------------------------
    "Inflation_CPI": MacroSeries(
        "Inflation_CPI", "CPIAUCSL", "M", "yoy", 1, INFLATION),
    "Core_CPI": MacroSeries(
        "Core_CPI", "CPILFESL", "M", "yoy", 1, INFLATION),
    "Breakeven_10Y": MacroSeries(
        # The only forward-looking input on either axis: market-implied
        # inflation, known in real time. Everything else here is history.
        "Breakeven_10Y", "T10YIE", "D", "none", 0, INFLATION),

    # ---- policy / liquidity context (not classified on) -----------------
    "Fed_Funds_Rate": MacroSeries(
        "Fed_Funds_Rate", "FEDFUNDS", "M", "none", 0, POLICY),
    "Yield_Curve": MacroSeries(
        "Yield_Curve", "T10Y2Y", "D", "none", 0, POLICY),
    "Real_Yield_10Y": MacroSeries(
        "Real_Yield_10Y", "DFII10", "D", "none", 0, POLICY),
    "M2_Money_Supply": MacroSeries(
        "M2_Money_Supply", "M2SL", "M", "yoy", 1, POLICY),

    # ---- sentiment input ------------------------------------------------
    "Junk_Bond_Spread": MacroSeries(
        "Junk_Bond_Spread", "BAMLH0A0HYM2", "D", "none", 0, SENTIMENT),
}

# Ingested by open-finance's fred_worker already. Everything else in REGISTRY
# is ours to ingest (worker/extra_series.py).
OPEN_FINANCE_OWNED = frozenset({
    "GDP_Growth", "Inflation_CPI", "Fed_Funds_Rate", "Unemployment",
    "Yield_Curve", "M2_Money_Supply", "Consumer_Sentiment",
    "Junk_Bond_Spread",
})


def by_axis(axis: str) -> list[MacroSeries]:
    """Registry entries feeding one axis, in registry order."""
    return [s for s in REGISTRY.values() if s.axis == axis]


def ours_to_ingest() -> list[MacroSeries]:
    """Series regime_mapping must fetch itself."""
    return [s for s in REGISTRY.values() if s.name not in OPEN_FINANCE_OWNED]
