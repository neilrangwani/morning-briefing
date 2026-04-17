"""
market_tool.py

Fetches S&P 500 performance data using yfinance.
- Prior market day: always returned (full day close-over-close change)
- Today intraday: returned only if move exceeds ±1%
"""

import datetime

import yfinance as yf

SYMBOL = "^GSPC"


def fetch_market() -> dict:
    """
    Fetch S&P 500 prior market day performance and optionally today's intraday move.

    Returns:
        {
            "symbol": str,
            "prior_day": {
                "date": str,        # e.g. "2026-04-16"
                "close": float,
                "change_pct": float,
                "direction": str,   # "up" or "down"
            },
            "today": {              # None if market hasn't opened today
                "price": float,
                "change_pct": float,
                "direction": str,
            } or None,
        }
    On error, returns {"error": str}.
    """
    try:
        ticker = yf.Ticker(SYMBOL)
        hist = ticker.history(period="10d", interval="1d")

        if hist.empty or len(hist) < 2:
            return {"error": "Insufficient market history data"}

        today = datetime.date.today()
        hist_dates = hist.index.date
        completed = hist[hist_dates < today]

        if len(completed) < 2:
            return {"error": "Not enough completed trading days"}

        prior_row = completed.iloc[-1]
        prev_row = completed.iloc[-2]

        prior_close = round(float(prior_row["Close"]), 2)
        prev_close = round(float(prev_row["Close"]), 2)
        prior_change_pct = round((prior_close - prev_close) / prev_close * 100, 2)
        prior_date = str(completed.index[-1].date())

        # Today's intraday — only included if market has opened today
        today_result = None
        today_rows = hist[hist_dates == today]
        if not today_rows.empty:
            info = ticker.fast_info
            current_price = round(float(info.last_price), 2)
            today_change_pct = round((current_price - prior_close) / prior_close * 100, 2)
            today_result = {
                "price": current_price,
                "change_pct": today_change_pct,
                "direction": "up" if today_change_pct >= 0 else "down",
            }

        return {
            "symbol": SYMBOL,
            "prior_day": {
                "date": prior_date,
                "close": prior_close,
                "change_pct": prior_change_pct,
                "direction": "up" if prior_change_pct >= 0 else "down",
            },
            "today": today_result,
        }

    except Exception as exc:
        return {"error": str(exc)}
