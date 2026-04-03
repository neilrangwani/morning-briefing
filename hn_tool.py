"""
hn_tool.py

Fetches Hacker News top stories filtered for AI/tech relevance.
Uses the official HN Firebase REST API — no API key required.
  https://hacker-news.firebaseio.com/v1/
"""

import concurrent.futures

import requests

HN_BASE = "https://hacker-news.firebaseio.com/v0"
CANDIDATE_COUNT = 60   # pull this many top IDs before filtering
REQUEST_TIMEOUT = 8

# Keywords that make a story relevant to Neil's interests.
# Lower-cased; matched against lower-cased title.
RELEVANCE_KEYWORDS = {
    # AI / ML core
    "ai", "llm", "gpt", "claude", "gemini", "openai", "anthropic", "deepmind",
    "mistral", "llama", "model", "neural", "machine learning", "deep learning",
    "transformer", "diffusion", "inference", "fine-tun", "rag", "agent",
    "multimodal", "benchmark", "rlhf", "reinforcement",
    # AI products / companies
    "cursor", "copilot", "midjourney", "stable diffusion", "hugging face",
    "perplexity", "groq", "replicate",
    # General tech
    "startup", "vc", "funding", "raises", "acquisition", "ipo",
    "python", "rust", "open source", "api", "developer",
    # SF / Bay Area
    "san francisco", "bay area", "silicon valley",
}


def _is_relevant(title: str) -> bool:
    lower = title.lower()
    return any(kw in lower for kw in RELEVANCE_KEYWORDS)


def _fetch_item(item_id: int):
    try:
        resp = requests.get(
            f"{HN_BASE}/item/{item_id}.json",
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        return resp.json()
    except Exception:
        return None


def fetch_hn_top(n: int = 5) -> list:
    """
    Fetch top Hacker News stories filtered for AI/tech relevance.

    Pulls the top 60 story IDs, fetches them in parallel, filters by
    relevance keywords, then returns the top n by score.

    Args:
        n: Number of stories to return (default 5).

    Returns:
        List of dicts: {title, url, score, comments}
    """
    try:
        resp = requests.get(
            f"{HN_BASE}/topstories.json",
            timeout=REQUEST_TIMEOUT,
        )
        resp.raise_for_status()
        top_ids = resp.json()[:CANDIDATE_COUNT]
    except Exception as exc:
        return [{"title": f"(error fetching HN top stories: {exc})", "url": "", "score": 0, "comments": 0}]

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as pool:
        items = list(pool.map(_fetch_item, top_ids))

    relevant = []
    for item in items:
        if not item:
            continue
        if item.get("type") != "story":
            continue
        title = item.get("title", "").strip()
        if not title:
            continue
        if not _is_relevant(title):
            continue
        url = item.get("url") or f"https://news.ycombinator.com/item?id={item['id']}"
        relevant.append({
            "title": title,
            "url": url,
            "score": item.get("score", 0),
            "comments": item.get("descendants", 0),
        })

    relevant.sort(key=lambda x: x["score"], reverse=True)
    return relevant[:n]
