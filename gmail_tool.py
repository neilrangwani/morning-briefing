"""
gmail_tool.py

Fetches newsletters from Gmail for the last 24 hours.
Matches against a curated NEWSLETTERS config and returns structured data
for Claude to summarize.
"""

import base64
import datetime
import re

from googleapiclient.discovery import build

# ─────────────────────────────────────────────────────────────────────────────
# Newsletter configuration
#
# Each entry:
#   name          — display name shown in the briefing
#   from_match    — substrings to match against the From header (case-insensitive, OR logic)
#   subject_match — substrings to match against Subject (case-insensitive, OR logic)
#                   If BOTH lists are non-empty, BOTH must have at least one hit.
#                   If only one list is non-empty, only that one is checked.
#   interest      — instruction passed to Claude: what to extract from this newsletter
#   include_links — True = ask Claude to include URLs; False = no links in output
#
# To tune matching after first run: check which emails arrive and adjust
# from_match / subject_match to be more or less specific.
# ─────────────────────────────────────────────────────────────────────────────
NEWSLETTERS = [
    {
        "name": "Axios Pro Rata",
        "from_match": ["pro rata", "primack"],
        "subject_match": ["pro rata"],
        "interest": (
            "Extract only VC deals and investments that involve AI companies. "
            "Skip all other content (earnings, policy, non-AI deals)."
        ),
        "include_links": False,
    },
    {
        "name": "Axios San Francisco",
        "from_match": ["axios"],
        "subject_match": ["san francisco", "axios sf"],
        "interest": "Full summary of all stories covered.",
        "include_links": False,
    },
    {
        "name": "The Rundown AI",
        "from_match": ["rundown", "therundown"],
        "subject_match": [],
        "interest": (
            "Summarize all non-advertisement articles. "
            "Skip any sponsored content, ads, or promotional sections."
        ),
        "include_links": False,
    },
    {
        "name": "Lenny's Newsletter",
        "from_match": ["lenny", "lennynewsletter"],
        "subject_match": [],
        "interest": "Full summary of the main article or topic covered.",
        "include_links": False,
    },
    {
        "name": "Ben's Bites",
        "from_match": ["benbites", "ben's bites", "ben bite"],
        "subject_match": [],
        "interest": "Full summary of all stories and tools covered.",
        "include_links": False,
    },
    {
        "name": "AI Operators by Evan Lee",
        "from_match": ["evan lee", "ai operators"],
        "subject_match": [],
        "interest": (
            "List every job posting mentioned. "
            "For each: company name, role title, and the application link."
        ),
        "include_links": True,
    },
]

# Maximum characters of email body to pass to Claude per newsletter.
# Keeps token usage predictable; 6000 chars ≈ ~1500 tokens.
MAX_BODY_CHARS = 6000


def _matches_newsletter(from_header: str, subject: str, nl: dict) -> bool:
    """Return True if this email matches a newsletter config entry."""
    from_lower = from_header.lower()
    subject_lower = subject.lower()

    has_from = bool(nl["from_match"])
    has_subject = bool(nl["subject_match"])

    from_hit = any(kw in from_lower for kw in nl["from_match"]) if has_from else True
    subject_hit = any(kw in subject_lower for kw in nl["subject_match"]) if has_subject else True

    if has_from and has_subject:
        return from_hit and subject_hit
    elif has_from:
        return from_hit
    elif has_subject:
        return subject_hit
    return False


def _decode_part(part: dict) -> str:
    """Decode a single Gmail payload part from base64url."""
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    # Gmail uses base64url; pad to multiple of 4
    padded = data + "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(padded).decode("utf-8", errors="replace")


def _extract_text(payload: dict) -> str:
    """
    Recursively extract the best plain-text body from a Gmail message payload.
    Prefers text/plain; falls back to text/html with tags stripped.
    """
    mime_type = payload.get("mimeType", "")

    if mime_type == "text/plain":
        return _decode_part(payload)

    if mime_type == "text/html":
        html = _decode_part(payload)
        # Strip tags and collapse whitespace
        text = re.sub(r"<[^>]+>", " ", html)
        text = re.sub(r"\s+", " ", text)
        return text.strip()

    # Multipart: recurse into parts, prefer text/plain hit first
    parts = payload.get("parts", [])

    # First pass: look for a text/plain part anywhere in the tree
    for part in parts:
        if "text/plain" in part.get("mimeType", ""):
            result = _extract_text(part)
            if result.strip():
                return result

    # Second pass: accept anything with text
    for part in parts:
        result = _extract_text(part)
        if result.strip():
            return result

    return ""


def fetch_newsletters(credentials) -> list[dict]:
    """
    Fetch emails from the last 24 hours and return matched newsletters.

    Args:
        credentials: Google OAuth2 credentials object (built in main.py)

    Returns:
        List of dicts: {name, subject, body_snippet, interest, include_links}
        Only newsletters that had a matching email are included.
    """
    service = build("gmail", "v1", credentials=credentials)

    # Gmail's `after:` operator accepts YYYY/MM/DD (searches since start of that day)
    yesterday = (datetime.date.today() - datetime.timedelta(days=1)).strftime("%Y/%m/%d")
    query = f"after:{yesterday}"

    result = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=100)
        .execute()
    )
    messages = result.get("messages", [])

    # Track which newsletters we've already matched to avoid duplicates
    matched_names: set[str] = set()
    found: list[dict] = []

    for msg_stub in messages:
        msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg_stub["id"], format="full")
            .execute()
        )

        headers = {
            h["name"]: h["value"]
            for h in msg.get("payload", {}).get("headers", [])
        }
        from_header = headers.get("From", "")
        subject = headers.get("Subject", "")

        for nl in NEWSLETTERS:
            if nl["name"] in matched_names:
                continue  # already found this newsletter today

            if _matches_newsletter(from_header, subject, nl):
                body = _extract_text(msg.get("payload", {}))
                # Normalize whitespace and truncate
                body = " ".join(body.split())[:MAX_BODY_CHARS]

                found.append(
                    {
                        "name": nl["name"],
                        "subject": subject,
                        "body_snippet": body,
                        "interest": nl["interest"],
                        "include_links": nl["include_links"],
                    }
                )
                matched_names.add(nl["name"])
                break  # don't match same email to multiple newsletters

    return found


def format_newsletters(newsletters: list[dict]) -> str:
    """Format newsletter list into a structured block for the Claude prompt."""
    if not newsletters:
        return "No newsletters found in the last 24 hours."

    sections = []
    for nl in newsletters:
        link_note = (
            " Include all URLs/links."
            if nl["include_links"]
            else " Do not include any links in the output."
        )
        sections.append(
            f"=== {nl['name']} ===\n"
            f"Subject: {nl['subject']}\n"
            f"What to extract: {nl['interest']}{link_note}\n"
            f"---\n"
            f"{nl['body_snippet']}"
        )

    return "\n\n".join(sections)
