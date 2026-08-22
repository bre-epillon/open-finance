"""JSON-safe conversion for pandas rows.

json.dumps writes bare NaN and Infinity, which no strict JSON parser accepts
-- including the browser's. Everything leaving this API goes through here.
"""

import math

import pandas as pd


def scalar(v):
    """One value -> a JSON-safe Python scalar."""
    if v is None or (isinstance(v, float) and not math.isfinite(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.date().isoformat()
    if pd.isna(v):
        return None
    if hasattr(v, "item"):          # numpy scalar
        v = v.item()
    if isinstance(v, float):
        return None if not math.isfinite(v) else round(v, 6)
    return v


def row(r: pd.Series, timestamp_name: str = "as_of") -> dict:
    """One row -> dict, index value included as `timestamp_name`.

    Pass a row built by api.reads.last_row, not one from df.iloc[-1]: a Series
    holds a single dtype, so slicing a row out of a mixed frame upcasts every
    integer to float and a component count of 5 is emitted as 5.0.
    """
    out = {timestamp_name: scalar(r.name)}
    out.update({str(k): scalar(v) for k, v in r.items()})
    return out


def frame(df: pd.DataFrame, timestamp_name: str = "as_of") -> list[dict]:
    """Whole frame -> list of dicts, oldest first.

    Built column by column rather than with iterrows() for the same reason:
    iterrows() yields each row as a single-dtype Series, so an int64 column
    comes back as floats. Column-wise also avoids constructing one Series per
    row, which matters at 250 rows a request.
    """
    if df.empty:
        return []
    stamps = [scalar(t) for t in df.index]
    cols = {str(c): [scalar(v) for v in df[c]] for c in df.columns}
    return [
        {timestamp_name: stamps[i], **{c: vals[i] for c, vals in cols.items()}}
        for i in range(len(df))
    ]
