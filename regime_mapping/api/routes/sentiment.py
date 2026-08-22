"""Greed & Fear endpoints."""

from fastapi import APIRouter, HTTPException, Query

from api import reads, serialise
from core import sentiment as S

router = APIRouter(prefix="/api/sentiment", tags=["sentiment"])

NO_DATA = ("No sentiment history yet. Run scripts/backfill_history.py; it "
           "needs ^GSPC and ^VIX in equity_prices.")


@router.get("")
def current():
    """The current composite, its label, and the five sub-scores."""
    row = reads.latest_sentiment()
    if row is None:
        raise HTTPException(status_code=503, detail=NO_DATA)

    out = serialise.row(row)
    out["label"] = S.classify(row["composite"])
    out["reading"] = S.reading(row)
    # A score built from three of five components is a different claim from
    # one built from five, and this is the only way a consumer can tell.
    out["components_expected"] = len(S.COMPONENTS)
    out["bands"] = {name: upper for upper, name in S.BANDS}
    return out


@router.get("/history")
def history(days: int = Query(250, ge=1, le=20000)):
    """Daily composite and sub-scores, oldest first."""
    df = reads.sentiment_history(limit=days)
    if df.empty:
        raise HTTPException(status_code=503, detail=NO_DATA)
    return {"days": len(df), "points": serialise.frame(df)}
