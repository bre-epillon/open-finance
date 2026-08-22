"""Environment configuration, read once.

open-finance's BACKLOG.md records that every ad-hoc script there needs
QUESTDB_HOST / QUESTDB_REST_PORT / QUESTDB_ILP_PORT and the corporate TLS
variables re-typed by hand. One module, read once, so that does not repeat
here.
"""

import os

QUESTDB_HOST = os.getenv("QUESTDB_HOST", "localhost")
QUESTDB_REST_PORT = int(os.getenv("QUESTDB_REST_PORT", "9000"))
QUESTDB_ILP_PORT = int(os.getenv("QUESTDB_ILP_PORT", "9009"))
QUESTDB_PG_PORT = int(os.getenv("QUESTDB_PG_PORT", "8812"))
QUESTDB_PG_USER = os.getenv("QUESTDB_PG_USER", "admin")
QUESTDB_PG_PASSWORD = os.getenv("QUESTDB_PG_PASSWORD", "quest")

REST_URL = f"http://{QUESTDB_HOST}:{QUESTDB_REST_PORT}"
ILP_CONF = f"tcp::addr={QUESTDB_HOST}:{QUESTDB_ILP_PORT};"

OPEN_FINANCE_API = os.getenv("OPEN_FINANCE_API", "http://localhost:8000")
FRED_API_KEY = os.getenv("FRED_API_KEY")

API_PORT = int(os.getenv("API_PORT", "8100"))

# Set by scripts/demo_server.py. Surfaced through /health so the dashboard can
# say on its face that the figures are invented -- a screenshot outlives the
# terminal it was taken from, and "is this real?" is not a question anyone
# should have to ask twice.
DEMO_MODE = os.getenv("REGIME_DEMO") == "1"

# Tables this project owns and writes.
REGIME_TABLE = "regime_history"
SENTIMENT_TABLE = "sentiment_index"

# Tables owned by open-finance, read-only from here apart from the additive
# indicator symbols documented in core/series.py.
MACRO_TABLE = "macro_indicators"
PRICE_TABLE = "equity_prices"

HTTP_TIMEOUT = 60
