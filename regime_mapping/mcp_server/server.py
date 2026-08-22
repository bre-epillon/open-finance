"""MCP server exposing the regime and sentiment engine to Claude Code.

stdio transport. Thin by design: it calls the same api.reads functions the
REST routes call, so there is no third copy of the maths and no way for the
two surfaces to disagree.

Every tool returns a `reading` field -- deterministic prose generated from the
same thresholds the dashboard uses. An LLM handed a bare z-score will invent
an interpretation of it, so supplying one is cheaper than correcting one.

The directory is `mcp_server/`, not `mcp/`, deliberately. This file inserts
the project root onto sys.path, so a directory called `mcp` would shadow the
installed MCP SDK and the import below would fail with "'mcp.server' is not a
package".

Run:  python mcp_server/server.py
Register:  claude mcp add regime -- python /abs/path/regime_mapping/mcp_server/server.py
"""

import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from mcp.server.fastmcp import FastMCP

from api import reads, serialise
from core import regime as R
from core import sentiment as S
from core.db.rest import QueryError
from core.tilts import payload as tilt_payload

# stderr, not stdout: stdout is the MCP transport, and a stray log line there
# corrupts the protocol stream.
logging.basicConfig(level=logging.INFO, stream=sys.stderr)

server = FastMCP("regime-mapping")

NO_REGIME = {"error": "No regime history yet. Run "
                      "scripts/backfill_history.py in the regime_mapping "
                      "project, then retry."}
NO_SENTIMENT = {"error": "No sentiment history yet. Run "
                         "scripts/backfill_history.py; it needs ^GSPC and "
                         "^VIX in QuestDB's equity_prices table."}


def guarded(fetch, empty: dict):
    """Run a DB read and turn every failure into a short, actionable dict.

    Without this, an unreachable QuestDB propagates as a ToolError carrying a
    wrapped urllib3 stack -- twenty lines of connection-pool detail for a
    consumer whose only useful next step is "start the container". FastMCP
    surfaces a raised exception verbatim, so the catching has to happen here.

    Returns (payload, row): payload is non-None when the caller should return
    it immediately.
    """
    try:
        row = fetch()
    except QueryError as e:
        return {"error": "Cannot reach QuestDB. Is the open-finance stack "
                         "running? (docker compose ps)",
                "detail": str(e).split(":")[0]}, None
    if row is None:
        return empty, None
    return None, row


@server.tool()
def get_regime() -> dict:
    """Current Dalio 4-quadrant macro regime for the US economy.

    Returns the quadrant (Goldilocks, Reflation, Stagflation, Deflation, or
    Transition when the signal is too weak to call), a 0-1 confidence, and the
    growth and inflation axes as levels, 3-month changes (Delta) and
    accelerations (Gamma). Units are standard deviations of each axis' own
    history. Also returns the All Weather portfolio tilt the regime implies --
    which is a research output, not investment advice.
    """
    failure, row = guarded(reads.latest_regime, NO_REGIME)
    if failure:
        return failure

    out = serialise.row(row)
    out["description"] = R.DESCRIPTION.get(row["quadrant"], "")
    out["reading"] = R.reading(row)
    out["confidence_floor"] = R.CONFIDENCE_FLOOR
    out["tilts"] = tilt_payload(row["quadrant"], row["confidence"])
    return out


@server.tool()
def get_sentiment() -> dict:
    """Current Greed & Fear index for US equity markets, 0-100.

    A composite of five percentile-ranked components: S&P 500 momentum, VIX
    versus its own 50-day average, safe-haven demand (equities minus long
    Treasuries), high-yield credit spreads, and market breadth. Returns the
    composite, its label from Extreme Fear to Extreme Greed, each sub-score,
    and how many of the five components were actually measurable -- a score
    built from three inputs is a weaker claim than one built from five.
    """
    failure, row = guarded(reads.latest_sentiment, NO_SENTIMENT)
    if failure:
        return failure

    out = serialise.row(row)
    out["label"] = S.classify(row["composite"])
    out["reading"] = S.reading(row)
    out["components_expected"] = len(S.COMPONENTS)
    return out


@server.tool()
def get_regime_history(months: int = 24) -> dict:
    """Monthly regime history, oldest first, for trajectory questions.

    Use this to answer "how long have we been in this regime", "when did it
    turn", or "what was the path". Each point carries the quadrant, the
    confidence and both axes' Delta and Gamma.
    """
    months = max(1, min(int(months), 1200))
    # No `or None` here: a DataFrame has no truth value, so `df or None`
    # raises ValueError instead of falling through.
    failure, df = guarded(lambda: reads.regime_history(limit=months),
                          NO_REGIME)
    if failure:
        return failure
    if df is None or df.empty:
        return NO_REGIME
    return {"months": len(df), "points": serialise.frame(df)}


if __name__ == "__main__":
    server.run()
