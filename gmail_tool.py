"""
gmail_tool.py

Fetches newsletters from Gmail labeled "Newsletter" that haven't been briefed yet.
After the briefing is generated, call mark_newsletters_briefed() to apply the
"Briefed" label so they won't be picked up again.
"""

import base64
import datetime
import re

from googleapiclient.discovery import build

# Maximum characters of email body to pass to Claude per newsletter.
# Haiku has a 200k token context window; 25000 chars ≈ ~6000 tokens.
MAX_BODY_CHARS = 15000

DEFAULT_INTEREST = (
    "Filter and summarize content relevant to someone who: (1) wants to use AI tools at work "
    "and in their personal life/business, (2) is looking for jobs in AI. "
    "Prioritize: AI tools and products, practical how-to AI content, AI job opportunities, "
    "AI company news and funding. Skip ads, sponsored content, and anything unrelated to AI."
)

BRIEFED_LABEL_NAME = "Projects/Briefed"
NEWSLETTER_LABEL_NAME = "Projects/Newsletter"


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


def _parse_sender_name(from_header: str) -> str:
    """Extract display name from a From header, falling back to the email address."""
    # "Display Name <email@example.com>" → "Display Name"
    match = re.match(r'^"?([^"<]+)"?\s*<', from_header)
    if match:
        return match.group(1).strip()
    # bare email address
    return from_header.strip()


def _get_or_create_label(service, name: str) -> str:
    """Return the label ID for the given name, creating it if it doesn't exist."""
    labels = service.users().labels().list(userId="me").execute().get("labels", [])
    for label in labels:
        if label["name"].lower() == name.lower():
            return label["id"]

    new_label = (
        service.users()
        .labels()
        .create(userId="me", body={"name": name})
        .execute()
    )
    return new_label["id"]


def fetch_newsletters(credentials) -> list[dict]:
    """
    Fetch emails labeled "Newsletter" but not "Briefed" from the last 36 hours.

    The 36-hour window is a safety net; the "Briefed" label is the primary
    deduplication mechanism.

    Args:
        credentials: Google OAuth2 credentials object (built in main.py)

    Returns:
        List of dicts: {message_id, name, subject, body_snippet, interest, include_links}
    """
    service = build("gmail", "v1", credentials=credentials)

    since = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=36)
    since_ts = int(since.timestamp())
    query = f"label:{NEWSLETTER_LABEL_NAME} -label:{BRIEFED_LABEL_NAME} after:{since_ts}"

    result = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=100)
        .execute()
    )
    messages = result.get("messages", [])

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

        body = _extract_text(msg.get("payload", {}))
        body = " ".join(body.split())[:MAX_BODY_CHARS]

        found.append(
            {
                "message_id": msg_stub["id"],
                "name": _parse_sender_name(from_header),
                "subject": subject,
                "body_snippet": body,
                "interest": DEFAULT_INTEREST,
                "include_links": False,
            }
        )

    return found


def mark_newsletters_briefed(credentials, newsletters: list[dict]) -> None:
    """Move newsletters to 'Briefed': add Briefed label, remove from inbox + Newsletter."""
    if not newsletters:
        return

    service = build("gmail", "v1", credentials=credentials)
    briefing_label_id = _get_or_create_label(service, BRIEFED_LABEL_NAME)
    newsletter_label_id = _get_or_create_label(service, NEWSLETTER_LABEL_NAME)

    for nl in newsletters:
        service.users().messages().modify(
            userId="me",
            id=nl["message_id"],
            body={
                "addLabelIds": [briefing_label_id],
                "removeLabelIds": ["INBOX", newsletter_label_id],
            },
        ).execute()


def format_newsletters(newsletters: list[dict]) -> str:
    """Format newsletter list into a structured block for the Claude prompt."""
    if not newsletters:
        return "No new newsletters found."

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
