"""
gcal_tool.py

Fetches today's Google Calendar events and detects Magic's walk.
Receives a pre-built Google OAuth2 credentials object from main.py.
"""

import datetime

from googleapiclient.discovery import build

MAGIC_WALK_KEYWORD = "magic walk"  # case-insensitive match on event title/description


def fetch_calendar(credentials) -> dict:
    """
    Fetch today's events from Google Calendar (primary calendar).

    Args:
        credentials: Google OAuth2 credentials object (built in main.py)

    Returns:
        {
            "events": [{"time": str, "title": str, "location": str}, ...],
            "magic_walk_scheduled": bool,
            "magic_walk_time": str | None,
        }
    """
    service = build("calendar", "v3", credentials=credentials)

    # Use local system timezone so midnight is correct for the user's location
    local_tz = datetime.datetime.now().astimezone().tzinfo
    today = datetime.date.today()
    time_min = datetime.datetime.combine(today, datetime.time.min, tzinfo=local_tz).isoformat()
    time_max = datetime.datetime.combine(today, datetime.time.max, tzinfo=local_tz).isoformat()

    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )

    events = result.get("items", [])

    parsed_events = []
    magic_walk_scheduled = False
    magic_walk_time = None

    for event in events:
        summary = event.get("summary", "(No title)")
        description = event.get("description", "") or ""
        location = event.get("location", "") or ""

        start = event.get("start", {})
        if "dateTime" in start:
            dt = datetime.datetime.fromisoformat(start["dateTime"])
            time_str = dt.strftime("%-I:%M %p")
        else:
            time_str = "All day"

        parsed_events.append(
            {"time": time_str, "title": summary, "location": location}
        )

        # Detect Magic's walk by keyword in title or description
        searchable = (summary + " " + description).lower()
        if MAGIC_WALK_KEYWORD in searchable:
            magic_walk_scheduled = True
            magic_walk_time = time_str

    return {
        "events": parsed_events,
        "magic_walk_scheduled": magic_walk_scheduled,
        "magic_walk_time": magic_walk_time,
    }


def format_calendar(cal: dict) -> str:
    """Format calendar data into a plain-text block for the Claude prompt."""
    if not cal["events"]:
        lines = ["No events scheduled today."]
    else:
        lines = []
        for e in cal["events"]:
            line = f"  {e['time']}: {e['title']}"
            if e["location"]:
                line += f" @ {e['location']}"
            lines.append(line)

    if cal["magic_walk_scheduled"]:
        lines.append(f"\nMAGIC WALK SCHEDULED: {cal['magic_walk_time']} — do not forget!")

    return "\n".join(lines)
