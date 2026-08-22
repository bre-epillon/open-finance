"""Regime endpoints."""

from fastapi import APIRouter, HTTPException, Query

from api import reads, serialise
from core import regime as R
from core.db.pg import regime_with_sentiment
from core.tilts import payload as tilt_payload

router = APIRouter(prefix="/api/regime", tags=["regime"])

NO_DATA = ("No regime history yet. Run scripts/backfill_history.py, and check "
           "scripts/check_data.py first if it produces nothing.")


@router.get("")
def current():
    """The current regime call, with the axes that produced it."""
    row = reads.latest_regime()
    if row is None:
        raise HTTPException(status_code=503, detail=NO_DATA)

    out = serialise.row(row)
    out["description"] = R.DESCRIPTION.get(row["quadrant"], "")
    out["reading"] = R.reading(row)
    # Surfaced so a consumer can see how the confidence was arrived at rather
    # than having to trust the number.
    out["confidence_floor"] = R.CONFIDENCE_FLOOR
    out["full_confidence_radius"] = R.FULL_CONFIDENCE_RADIUS
    return out


@router.get("/history")
def history(months: int = Query(24, ge=1, le=1200)):
    """Trajectory points for the quadrant scatter, oldest first."""
    df = reads.regime_history(limit=months)
    if df.empty:
        raise HTTPException(status_code=503, detail=NO_DATA)
    return {"months": len(df), "points": serialise.frame(df)}


@router.get("/tilts")
def tilts():
    """All Weather baseline and the current regime's tilt away from it."""
    row = reads.latest_regime()
    if row is None:
        raise HTTPException(status_code=503, detail=NO_DATA)
    out = tilt_payload(row["quadrant"], row["confidence"])
    out["as_of"] = serialise.scalar(row.name)
    return out


@router.get("/with_sentiment")
def with_sentiment(months: int = Query(24, ge=1, le=1200)):
    """Regime points carrying the sentiment reading as of each one.

    This is the ASOF JOIN read (core/db/pg.py): monthly regime rows matched to
    the most recent daily sentiment row at or before each. Degrades to the
    regime history alone if pg-wire on 8812 is unavailable, rather than
    failing the request.
    """
    df = regime_with_sentiment(limit=months)
    if df.empty:
        return {"joined": False, "reason": "pg-wire unavailable or no rows",
                **history(months)}
    df = df.set_index("timestamp")
    return {"joined": True, "months": len(df), "points": serialise.frame(df)}
