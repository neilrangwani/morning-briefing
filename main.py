"""
main.py

Morning Briefing Agent — orchestrator.

Usage:
  python main.py            # live run — hits Google + weather APIs + Claude
  python main.py --dry-run  # uses mock data, no external API calls (for testing)
"""

import argparse
import datetime
import os
import subprocess
import sys
from pathlib import Path

import anthropic
from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

from gcal_tool import fetch_calendar, format_calendar
from gmail_tool import fetch_newsletters, format_newsletters, mark_newsletters_briefed
from weather_tool import fetch_weather, format_weather

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
            creds.refresh(Request())
        else:
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
# Claude synthesis
# ─────────────────────────────────────────────────────────────────────────────

def build_context(weather: dict, calendar: dict, newsletters: list[dict]) -> str:
    """Assemble the structured data block sent to Claude."""
    today = datetime.date.today().strftime("%A, %B %-d, %Y")
    return (
        f"Today is {today}.\n\n"
        f"--- WEATHER ---\n{format_weather(weather)}\n\n"
        f"--- CALENDAR ---\n{format_calendar(calendar)}\n\n"
        f"--- NEWSLETTERS ---\n{format_newsletters(newsletters)}"
    )


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


def synthesize(context: str) -> str:
    """Call Claude Haiku to produce the morning briefing from the context block."""
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
        weather = MOCK_WEATHER
        calendar = MOCK_CALENDAR
        newsletters = MOCK_NEWSLETTERS
    else:
        # Single Google OAuth flow covers both Gmail + Calendar
        print("\nAuthenticating with Google...", end=" ", flush=True)
        creds = get_google_credentials()
        print("done")

        print("Fetching weather...", end=" ", flush=True)
        weather = fetch_weather()
        print(f"done  ({weather['city']})")

        print("Fetching calendar...", end=" ", flush=True)
        calendar = fetch_calendar(creds)
        print(f"done  ({len(calendar['events'])} event(s))")

        print("Fetching newsletters...", end=" ", flush=True)
        newsletters = fetch_newsletters(creds)
        print(f"done  ({len(newsletters)} newsletter(s) found)")

    print("\nSynthesizing with Claude Haiku...\n")
    context = build_context(weather, calendar, newsletters)
    briefing = synthesize(context)

    print(divider)
    print()
    print(briefing)
    print()
    print(divider)
    print()

    if not args.dry_run:
        mark_newsletters_briefed(creds, newsletters)

    today = datetime.date.today().strftime("%A, %B %-d")
    send_email(subject=f"Morning Briefing — {today}", body=briefing)


if __name__ == "__main__":
    main()
