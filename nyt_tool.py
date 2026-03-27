"""
nyt_tool.py

Fetches NYT headlines via free public RSS feeds. No API key required.
Covers technology, business, and US news (for SF filtering).
"""

import xml.etree.ElementTree as ET

import requests

NYT_FEEDS = {
    "technology": "https://rss.nytimes.com/services/xml/rss/nyt/Technology.xml",
    "business": "https://rss.nytimes.com/services/xml/rss/nyt/Business.xml",
    "us": "https://rss.nytimes.com/services/xml/rss/nyt/US.xml",
}

MAX_HEADLINES_PER_FEED = 8


def fetch_nyt_headlines() -> list[dict]:
    """
    Fetch recent NYT headlines from technology, business, and US feeds.

    Returns:
        List of dicts: {category, title, description}
    """
    headlines = []
    for category, url in NYT_FEEDS.items():
        try:
            resp = requests.get(
                url,
                timeout=10,
                headers={"User-Agent": "MorningBriefingBot/1.0"},
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item")[:MAX_HEADLINES_PER_FEED]:
                title = item.findtext("title", "").strip()
                description = item.findtext("description", "").strip()
                if title:
                    headlines.append(
                        {
                            "category": category,
                            "title": title,
                            "description": description[:200] if description else "",
                        }
                    )
        except Exception as exc:
            headlines.append(
                {
                    "category": category,
                    "title": f"(error fetching {category}: {exc})",
                    "description": "",
                }
            )
    return headlines
