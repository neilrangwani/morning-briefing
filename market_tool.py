"""
market_tool.py

Fetches S&P 500 current price and 1-day percentage change using the
Yahoo Finance unofficial chart API. No API key required.
"""

import requests

YF_BASE = "https://query1.finance.yahoo.com/v8/finance/chart"
SYMBOL = "^GSPC"
REQUEST_TIMEOUT = 10

# Yahoo Finance blocks generic Python user-agents; mimic a browser.
HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}


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
        resp = requests.get(
            f"{YF_BASE}/{SYMBOL}",
            params={"interval": "1d", "range": "2d"},
            headers=HEADERS,
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        data = resp.json()

        meta = data["chart"]["result"][0]["meta"]
        price = meta["regularMarketPrice"]
        prev_close = meta["chartPreviousClose"]

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
