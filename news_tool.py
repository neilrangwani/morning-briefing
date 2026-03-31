"""
news_tool.py

Fetches hyper-local SF news by scraping public RSS feeds from SFGate and
Mission Local. No API key required.

The zip_code argument is accepted for interface consistency with the tool
definition but is not used to filter results — both feeds cover San Francisco
broadly. Pass Neil's current zip (e.g. "94117") and you'll get SF news.
"""

import xml.etree.ElementTree as ET

import requests

NEWS_FEEDS = {
    "SFGate": "https://www.sfgate.com/rss/feed/SFGate-Top-News-476.php",
    "Mission Local": "https://missionlocal.org/feed/",
}

MAX_ITEMS = 10
REQUEST_TIMEOUT = 10


def fetch_local_news(zip_code: str = "94117") -> list:
    """
    Fetch SF neighborhood news from SFGate and Mission Local RSS feeds.

    Args:
        zip_code: Neil's current zip (used for labeling; both feeds cover SF).

    Returns:
        List of up to 10 dicts: {title, source, url}
    """
    buckets = {}

    for source, url in NEWS_FEEDS.items():
        items = []
        try:
            resp = requests.get(
                url,
                timeout=REQUEST_TIMEOUT,
                headers={"User-Agent": "MorningBriefingBot/1.0"},
            )
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            for item in root.findall(".//item"):
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                if title and link:
                    items.append({"title": title, "source": source, "url": link})
        except Exception as exc:
            items.append({
                "title": f"(error fetching {source}: {exc})",
                "source": source,
                "url": "",
            })
        buckets[source] = items

    # Round-robin interleave across sources, then cap at MAX_ITEMS
    merged = []
    seen_titles = set()
    source_names = list(buckets.keys())
    max_len = max(len(v) for v in buckets.values()) if buckets else 0

    for i in range(max_len):
        if len(merged) >= MAX_ITEMS:
            break
        for name in source_names:
            if i < len(buckets[name]):
                item = buckets[name][i]
                norm = item["title"].lower()
                if norm not in seen_titles:
                    seen_titles.add(norm)
                    merged.append(item)
                    if len(merged) >= MAX_ITEMS:
                        break

    return merged
