"""
market_tool.py

Fetches S&P 500 current price and 1-day percentage change using yfinance.
No API key required.
"""

import yfinance as yf

SYMBOL = "^GSPC"


def fetch_market() -> dict:
    """
    Fetch S&P 500 current price and 1-day percentage change.

    Returns:
        {
            "symbol": str,        # "^GSPC"
            "price": float,       # current/last-close price
            "change_pct": float,  # e.g. -0.42 means -0.42%
            "direction": str,     # "up" or "down"
        }
    On error, returns a dict with an "error" key instead.
    """
    try:
        ticker = yf.Ticker(SYMBOL)
        info = ticker.fast_info
        price = info.last_price
        prev_close = info.previous_close

        if prev_close and prev_close != 0:
            change_pct = round((price - prev_close) / prev_close * 100, 2)
        else:
            change_pct = 0.0

        return {
            "symbol": SYMBOL,
            "price": round(price, 2),
            "change_pct": change_pct,
            "direction": "up" if change_pct >= 0 else "down",
        }

    except Exception as exc:
        return {"error": str(exc)}
