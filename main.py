"""
main.py

Morning Briefing Agent — orchestrator.

Usage:
  python main.py            # live run — hits Google + weather APIs + Claude
  python main.py --dry-run  # uses mock data, no external API calls (for testing)

Live run: Claude drives an agentic tool loop to gather data, draft email replies,
and produce the briefing. Dry-run uses the old pre-fetched data path.
"""

import argparse
import datetime
import json
import os
import subprocess
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gcal_tool import fetch_calendar, format_calendar
from gmail_tool import (
    create_draft_reply,
    fetch_email_body_by_id,
    fetch_newsletters,
    format_newsletters,
    list_inbox_emails,
    list_newsletters_metadata,
    mark_newsletters_briefed,
)
from hn_tool import fetch_hn_top
from market_tool import fetch_market
from news_tool import fetch_local_news
from nyt_tool import fetch_nyt_headlines
from weather_tool import fetch_weather, fetch_weather_for_city, format_weather

load_dotenv()

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/calendar.readonly",
]

TOKEN_PATH = Path(__file__).parent / "token.json"
CREDENTIALS_PATH = Path(__file__).parent / "credentials.json"

CLAUDE_MODEL = "claude-haiku-4-5-20251001"

# Cost controls
MAX_TURNS = 25          # max tool-call rounds before we force a stop
MAX_INPUT_TOKENS = 200_000  # Haiku: $1/1M input tokens → hard ceiling ~$0.20/run

# ─────────────────────────────────────────────────────────────────────────────
# Tool definitions
# ─────────────────────────────────────────────────────────────────────────────

TOOLS = [
    {
        "name": "get_calendar",
        "description": (
            "Get today's calendar events including titles, times, and locations. "
            "Call this first to determine where Neil will be today."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_weather",
        "description": (
            "Get today's weather forecast for a city. "
            "Use the location from calendar events when available; default to San Francisco."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "city": {
                    "type": "string",
                    "description": "City name, e.g. 'San Francisco' or 'New York'",
                }
            },
            "required": ["city"],
        },
    },
    {
        "name": "list_newsletters",
        "description": "List today's unread newsletters (sender name, subject, message ID). Does not fetch bodies.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "fetch_email_body",
        "description": "Fetch the full text body of an email by its Gmail message ID.",
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID from list_newsletters or list_inbox_emails",
                }
            },
            "required": ["message_id"],
        },
    },
    {
        "name": "list_inbox_emails",
        "description": (
            "List recent inbox emails that are not newsletters (last 24 hours). "
            "Returns sender, subject, and a short snippet."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "create_draft_reply",
        "description": (
            "Create a Gmail draft reply to an email. Use this when an email clearly warrants a response. "
            "Drafts are saved but not sent."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "message_id": {
                    "type": "string",
                    "description": "Gmail message ID of the email to reply to",
                },
                "body": {
                    "type": "string",
                    "description": "Plain-text body of the draft reply",
                },
            },
            "required": ["message_id", "body"],
        },
    },
    {
        "name": "get_nyt_headlines",
        "description": (
            "Get today's New York Times headlines from technology, business, and US news feeds. "
            "Filter for stories relevant to San Francisco, the economy, and AI."
        ),
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
    {
        "name": "get_local_news",
        "description": (
            "Get hyper-local San Francisco news from SFGate and Mission Local RSS feeds. "
            "Call this to surface neighborhood-level SF stories not covered by national outlets."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "zip_code": {
                    "type": "string",
                    "description": "Neil's current zip code, e.g. '94117'",
                }
            },
            "required": ["zip_code"],
        },
    },
    {
        "name": "get_hn_top",
        "description": (
            "Fetch top Hacker News stories filtered for AI and tech relevance. "
            "Returns the highest-scoring stories matching AI, ML, startups, or developer topics."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "n": {
                    "type": "integer",
                    "description": "Number of stories to return (default 5, max 10)",
                }
            },
            "required": [],
        },
    },
    {
        "name": "get_market",
        "description": "Get the S&P 500 current price and 1-day percentage change.",
        "input_schema": {"type": "object", "properties": {}, "required": []},
    },
]

# ─────────────────────────────────────────────────────────────────────────────
# System prompt (agentic path)
# ─────────────────────────────────────────────────────────────────────────────

AGENT_SYSTEM_PROMPT = """\
You are Neil's personal morning briefing assistant. Use your tools to gather \
data, then produce a warm but concise morning briefing — like a smart friend \
giving him the morning rundown. Address him as Neil.

GATHERING DATA — follow these steps:
1. Call get_calendar to see today's schedule.
2. The user message includes Neil's current location. Use that as the primary \
city for get_weather. If a calendar event is in a different city, also fetch \
weather for that city.
3. Call list_newsletters, then call fetch_email_body for each one to read it.
4. Call list_inbox_emails to see what's in the inbox. For any email that looks like \
it may warrant a personal reply, call fetch_email_body to read it fully first. Then \
call create_draft_reply only if the full content confirms a reply makes sense. Skip \
automated emails, notifications, and anything promotional.
5. Call get_nyt_headlines and filter for stories about AI, San Francisco, or the economy.
6. Call get_local_news with Neil's current zip code for SF neighborhood news.
7. Call get_hn_top for top Hacker News AI/tech stories.
8. Call get_market for the S&P 500 daily move.

FORMAT — produce the briefing in Markdown using exactly this structure:

# 🌤 Weather
One or two sentences on what to expect today.

# 📅 Today's Calendar

- HH:MM AM/PM — Event Title @ Location
- HH:MM AM/PM — Event Title @ Location

Each event on its own line. Dog walk events: `- 🐾 **HH:MM PM — Event Title**`

# 📬 Newsletter Highlights

For each newsletter, use EXACTLY this format (blank lines required):

## [Sender Name]

**"[Email Subject]"**

- First bullet (one sentence, 15 words max)
- Second bullet (one sentence, 15 words max)

Up to 7 bullets per newsletter. Ruthlessly prioritize — most newsworthy only.

Newsletter filtering rules:
- Always skip: ads, sponsored content, promotional offers.
- Axios Pro Rata: AI deals only (company, round size, valuation, one-line description). Skip non-AI deals.
- Axios San Francisco: full local news summary; highlight AI but include non-AI content too.
- All other newsletters: summarize all editorial content; highlight AI-related items.

# 📰 From The New York Times

Up to 7 bullets covering AI, San Francisco, and economy stories. Skip anything \
not relevant to those three topics.

- [CATEGORY] Headline or one-sentence summary

# 🏙 SF Local News

Up to 5 bullets. Lead with any stories touching Neil's neighborhood \
(94117 / Inner Sunset / Cole Valley / Haight). Include source in brackets.

- [Source] One-sentence summary

# 💻 Hacker News

Up to 5 items. Include score and comment count.

- **Title** — score: N, comments: N

# 📈 Markets

One line: S&P 500 price and 1-day move. Add one sentence of context if the \
move is notable (>1% either direction).

# 📝 Draft Replies Queued

(Include only if you created drafts. Omit this section entirely if no drafts.)
- Reply to [Name] re: "[Subject]" — saved to Drafts

Keep the whole briefing scannable. No filler. Get straight to the point.\
"""

# ─────────────────────────────────────────────────────────────────────────────
# System prompt (dry-run / legacy path)
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """\
You are Neil's personal morning briefing assistant. Be warm but concise — like a \
smart friend giving him the morning rundown, not a formal report. Address him as Neil.

Format the briefing in Markdown. Use the exact structure below:

# 🌤 Weather
One or two sentences on what to expect today.

# 📅 Today's Calendar

- HH:MM AM/PM — Event Title @ Location
- HH:MM AM/PM — Event Title @ Location

Each event MUST be on its own line as a bullet. Dog walk events: `- 🐾 **HH:MM PM — Event Title**`

# 📬 Newsletter Highlights

For each newsletter, use EXACTLY this format (blank lines are required):

## [Sender Name]

**"[Email Subject]"**

- First bullet point (one sentence max)
- Second bullet point (one sentence max)
- Third bullet point (one sentence max)

Limit each newsletter to 7 bullets max. Each bullet must be one sentence, no more than \
15 words. Ruthlessly prioritize — only the most newsworthy, non-redundant points. The \
entire briefing must fit within 8192 output tokens, so be aggressive about cutting filler.

IMPORTANT: There must be a blank line before the first bullet and between the subject line and bullets. Each bullet must be on its own line starting with `- `.

Newsletter filtering rules:
- **Always skip**: ads, sponsored content, and promotional offers in any newsletter.
- **Axios Pro Rata**: Extract every VC/PE/M&A deal that involves an AI company or AI \
technology. Include the company, round size, valuation if mentioned, and a one-line \
description. Skip all non-AI deals.
- **Axios San Francisco**: Summarize all editorial content as a regular local news briefing. \
Highlight anything AI-related, but do not skip non-AI content.
- **All other newsletters**: Summarize all editorial content. Highlight anything related \
to AI (tools, products, jobs, company news, how-to content). Skip only ads and \
sponsored content.

Keep the whole briefing scannable. No filler sentences. Get straight to the point.\
"""

# ─────────────────────────────────────────────────────────────────────────────
# Mock data for --dry-run (no API calls)
# ─────────────────────────────────────────────────────────────────────────────

MOCK_WEATHER = {
    "city": "San Francisco",
    "region": "California",
    "current_temp_f": 62,
    "high_f": 69,
    "low_f": 54,
    "precip_pct": 5,
    "conditions": "Partly cloudy",
}

MOCK_CALENDAR = {
    "events": [
        {"time": "9:00 AM", "title": "Team standup", "location": "Zoom"},
        {"time": "11:00 AM", "title": "Magic Walk - JD", "location": ""},
        {"time": "2:00 PM", "title": "Product review", "location": "Conference Room B"},
    ],
    "magic_walk_scheduled": True,
    "magic_walk_time": "11:00 AM",
}

MOCK_NEWSLETTERS = [
    {
        "name": "Axios Pro Rata",
        "subject": "Pro Rata: The AI funding wave continues",
        "body_snippet": (
            "Anthropic raised $2B at a $15B valuation in a round led by Google. "
            "OpenAI is in talks to raise $10B from SoftBank. "
            "Scale AI saw enterprise demand surge 3x YoY driven by LLM fine-tuning workloads."
        ),
        "interest": "VC deals and investments involving AI companies only.",
        "include_links": False,
    },
    {
        "name": "AI Operators by Evan Lee",
        "subject": "AI Operators: 12 new roles this week",
        "body_snippet": (
            "Acme Corp is hiring a Head of AI to lead their LLM product team. "
            "Apply at https://acme.com/jobs/head-of-ai. "
            "Startup XYZ needs ML Engineers with RAG experience. "
            "Apply at https://xyz.io/careers/ml-engineer. "
            "Big Co is looking for an AI Product Manager. https://bigco.com/jobs/ai-pm"
        ),
        "interest": "List every job posting mentioned, with company name, role title, and application link.",
        "include_links": True,
    },
]


# ─────────────────────────────────────────────────────────────────────────────
# Google OAuth
# ─────────────────────────────────────────────────────────────────────────────

def get_google_credentials() -> Credentials:
    """Load cached Google OAuth2 credentials or run the browser auth flow."""
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
            except RefreshError:
                creds = None
        if not creds:
            if os.environ.get("GITHUB_ACTIONS"):
                print(
                    "\nERROR: Google token is missing or expired and cannot be refreshed in CI.\n"
                    "Re-run the OAuth flow locally (python main.py) and update the GOOGLE_TOKEN_JSON secret.\n",
                    file=sys.stderr,
                )
                sys.exit(1)
            if not CREDENTIALS_PATH.exists():
                print(
                    "\nERROR: credentials.json not found.\n"
                    "Follow the setup steps in README.md to create Google OAuth credentials.\n",
                    file=sys.stderr,
                )
                sys.exit(1)
            flow = InstalledAppFlow.from_client_secrets_file(
                str(CREDENTIALS_PATH), SCOPES
            )
            # Wrap authorization_url so we can open the browser via macOS 'open'
            _orig_auth_url = flow.authorization_url
            def _auth_and_open(**kwargs):
                url, state = _orig_auth_url(**kwargs)
                print(f"\nOpening browser for Google sign-in...\n{url}\n", flush=True)
                subprocess.Popen(["open", url])
                return url, state
            flow.authorization_url = _auth_and_open
            creds = flow.run_local_server(port=0, open_browser=False)

        TOKEN_PATH.write_text(creds.to_json())

    return creds


# ─────────────────────────────────────────────────────────────────────────────
# Tool executor
# ─────────────────────────────────────────────────────────────────────────────

def execute_tool(
    name: str,
    tool_input: dict,
    creds: Credentials,
    newsletters_seen: list[dict],
) -> str:
    """
    Dispatch a tool call and return the result as a plain-text string.
    Appends newsletter metadata to newsletters_seen for post-run marking.
    """
    try:
        if name == "get_calendar":
            cal = fetch_calendar(creds)
            if not cal["events"]:
                return "No events scheduled today."
            lines = []
            for e in cal["events"]:
                line = f"{e['time']}: {e['title']}"
                if e["location"]:
                    line += f" @ {e['location']}"
                lines.append(line)
            if cal["magic_walk_scheduled"]:
                lines.append(f"\nMAGIC WALK SCHEDULED: {cal['magic_walk_time']} — do not forget!")
            return "\n".join(lines)

        elif name == "get_weather":
            city = tool_input.get("city", "San Francisco")
            w = fetch_weather_for_city(city)
            return (
                f"Location: {w['city']}, {w['region']}\n"
                f"Current: {w['current_temp_f']}°F — {w['conditions']}\n"
                f"High: {w['high_f']}°F  |  Low: {w['low_f']}°F\n"
                f"Precipitation chance: {w['precip_pct']}%"
            )

        elif name == "list_newsletters":
            newsletters = list_newsletters_metadata(creds)
            newsletters_seen.extend(newsletters)
            if not newsletters:
                return "No new newsletters today."
            lines = [f"{i+1}. [{nl['name']}] \"{nl['subject']}\" (id: {nl['message_id']})"
                     for i, nl in enumerate(newsletters)]
            return "\n".join(lines)

        elif name == "fetch_email_body":
            message_id = tool_input["message_id"]
            return fetch_email_body_by_id(creds, message_id)

        elif name == "list_inbox_emails":
            emails = list_inbox_emails(creds)
            if not emails:
                return "No new inbox emails in the last 24 hours."
            lines = [
                f"{i+1}. From: {e['from_name']} | Subject: {e['subject']} | "
                f"Snippet: {e['snippet']} (id: {e['message_id']})"
                for i, e in enumerate(emails)
            ]
            return "\n".join(lines)

        elif name == "create_draft_reply":
            return create_draft_reply(creds, tool_input["message_id"], tool_input["body"])

        elif name == "get_nyt_headlines":
            headlines = fetch_nyt_headlines()
            if not headlines:
                return "No NYT headlines available."
            lines = [
                f"[{h['category'].upper()}] {h['title']}"
                + (f"\n  {h['description']}" if h["description"] else "")
                for h in headlines
            ]
            return "\n".join(lines)

        elif name == "get_local_news":
            zip_code = tool_input.get("zip_code", "94117")
            stories = fetch_local_news(zip_code)
            if not stories:
                return "No local news available."
            lines = [
                f"{i+1}. [{s['source']}] {s['title']}"
                + (f"\n   {s['url']}" if s["url"] else "")
                for i, s in enumerate(stories)
            ]
            return "\n".join(lines)

        elif name == "get_hn_top":
            n = int(tool_input.get("n", 5))
            n = max(1, min(n, 10))
            stories = fetch_hn_top(n)
            if not stories:
                return "No relevant HN stories found."
            lines = [
                f"{i+1}. {s['title']} (score: {s['score']}, comments: {s['comments']})\n   {s['url']}"
                for i, s in enumerate(stories)
            ]
            return "\n".join(lines)

        elif name == "get_market":
            result = fetch_market()
            if "error" in result:
                return f"Market data unavailable: {result['error']}"
            arrow = "▲" if result["direction"] == "up" else "▼"
            sign = "+" if result["change_pct"] >= 0 else ""
            return (
                f"S&P 500 (^GSPC): {result['price']:,.2f}  "
                f"{arrow} {sign}{result['change_pct']}% today"
            )

        else:
            return f"Unknown tool: {name}"

    except Exception as exc:
        return f"Error running {name}: {exc}"


# ─────────────────────────────────────────────────────────────────────────────
# Agentic loop (live run)
# ─────────────────────────────────────────────────────────────────────────────

def run_agent(creds: Credentials) -> tuple[str, list[dict]]:
    """
    Run the morning briefing agent with tool access.
    Returns (briefing_text, newsletters_to_mark_as_briefed).
    """
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "\nERROR: ANTHROPIC_API_KEY is not set.\n"
            "Add it to your .env file: ANTHROPIC_API_KEY=sk-ant-...\n",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    newsletters_seen: list[dict] = []

    today = datetime.date.today().strftime("%A, %B %-d, %Y")
    current_location = os.environ.get("CURRENT_LOCATION", "").strip() or "94117"
    messages = [
        {
            "role": "user",
            "content": (
                f"Today is {today}. "
                f"My current location is: {current_location}. "
                "Please build my morning briefing."
            ),
        }
    ]

    turns = 0
    total_input_tokens = 0

    while turns < MAX_TURNS:
        response = client.messages.create(
            model=CLAUDE_MODEL,
            max_tokens=8192,
            system=AGENT_SYSTEM_PROMPT,
            tools=TOOLS,
            messages=messages,
        )

        total_input_tokens += response.usage.input_tokens
        turns += 1

        messages.append({"role": "assistant", "content": response.content})

        if response.stop_reason == "end_turn":
            briefing = next(
                (b.text for b in response.content if b.type == "text"), ""
            )
            print(
                f"\n  [usage: {turns} turn(s), "
                f"~{total_input_tokens:,} input tokens, "
                f"~${total_input_tokens / 1_000_000:.4f} est. input cost]"
            )
            return briefing, newsletters_seen

        if response.stop_reason != "tool_use":
            break

        if total_input_tokens >= MAX_INPUT_TOKENS:
            print(
                f"\n  [cost limit reached: {total_input_tokens:,} input tokens after {turns} turn(s) — stopping]",
                file=sys.stderr,
            )
            break

        # Execute all tool calls and collect results
        tool_results = []
        for block in response.content:
            if block.type == "tool_use":
                print(f"  → {block.name}({json.dumps(block.input) if block.input else ''})")
                result = execute_tool(block.name, block.input, creds, newsletters_seen)
                tool_results.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result,
                    }
                )

        messages.append({"role": "user", "content": tool_results})

    return "Error: agent did not complete.", newsletters_seen


# ─────────────────────────────────────────────────────────────────────────────
# Legacy synthesis (dry-run only)
# ─────────────────────────────────────────────────────────────────────────────

def build_context(weather: dict, calendar: dict, newsletters: list[dict]) -> str:
    """Assemble the structured data block sent to Claude (dry-run path)."""
    today = datetime.date.today().strftime("%A, %B %-d, %Y")
    return (
        f"Today is {today}.\n\n"
        f"--- WEATHER ---\n{format_weather(weather)}\n\n"
        f"--- CALENDAR ---\n{format_calendar(calendar)}\n\n"
        f"--- NEWSLETTERS ---\n{format_newsletters(newsletters)}"
    )


def synthesize(context: str) -> str:
    """Call Claude Haiku to produce the morning briefing from a pre-built context (dry-run)."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print(
            "\nERROR: ANTHROPIC_API_KEY is not set.\n"
            "Add it to your .env file: ANTHROPIC_API_KEY=sk-ant-...\n",
            file=sys.stderr,
        )
        sys.exit(1)

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model=CLAUDE_MODEL,
        max_tokens=8192,
        system=SYSTEM_PROMPT,
        messages=[
            {
                "role": "user",
                "content": (
                    f"Here is today's data:\n\n{context}\n\n"
                    "Please produce my morning briefing."
                ),
            }
        ],
    )
    return message.content[0].text


# ─────────────────────────────────────────────────────────────────────────────
# Email delivery
# ─────────────────────────────────────────────────────────────────────────────

def send_email(subject: str, body: str) -> None:
    """Send the briefing via Resend. No-ops if RESEND_API_KEY is not set."""
    api_key = os.environ.get("RESEND_API_KEY")
    to_email = os.environ.get("TO_EMAIL")
    if not api_key or not to_email:
        return

    import markdown as _md
    import requests as _req

    html_body = f"""
    <html><body style="font-family: sans-serif; max-width: 680px; margin: 0 auto; color: #111;">
    {_md.markdown(body)}
    </body></html>
    """

    resp = _req.post(
        "https://api.resend.com/emails",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "from": "Morning Briefing <onboarding@resend.dev>",
            "to": [to_email],
            "subject": subject,
            "html": html_body,
            "text": body,
        },
        timeout=15,
    )
    if resp.ok:
        print(f"Email sent to {to_email}")
    else:
        print(f"Email failed: {resp.status_code} {resp.text}", file=sys.stderr)


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Morning Briefing Agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Use mock data instead of real APIs (no network calls, for testing)",
    )
    args = parser.parse_args()

    divider = "━" * 58

    print(f"\n{divider}")
    print("  ☀  Morning Briefing Agent")
    print(divider)

    if args.dry_run:
        print("\n[DRY RUN — using mock data, no API calls]\n")
        context = build_context(MOCK_WEATHER, MOCK_CALENDAR, MOCK_NEWSLETTERS)
        print("Synthesizing with Claude Haiku...\n")
        briefing = synthesize(context)
        newsletters_to_mark = []
    else:
        print("\nAuthenticating with Google...", end=" ", flush=True)
        creds = get_google_credentials()
        print("done")

        print("\nRunning agent...\n")
        briefing, newsletters_to_mark = run_agent(creds)

    print(divider)
    print()
    print(briefing)
    print()
    print(divider)
    print()

    if not args.dry_run and newsletters_to_mark:
        mark_newsletters_briefed(creds, newsletters_to_mark)

    today = datetime.date.today().strftime("%A, %B %-d")
    send_email(subject=f"Morning Briefing — {today}", body=briefing)


if __name__ == "__main__":
    main()
