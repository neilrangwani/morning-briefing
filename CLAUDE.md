# CLAUDE.md — Morning Briefing Agent

## What This Is
A Python CLI that generates a personalized daily morning briefing.
Sources: Gmail newsletters, Google Calendar, Open-Meteo weather.
Synthesis: Claude Haiku (`claude-haiku-4-5-20251001`).

## Stack
- Python 3.10+
- `anthropic` — Claude API (Haiku model)
- `google-api-python-client` + `google-auth-oauthlib` — Gmail + Calendar (OAuth 2.0)
- `requests` — Open-Meteo forecast + IP geolocation (free, no keys)
- `python-dotenv` — .env management

## Running
```bash
python main.py            # live run
python main.py --dry-run  # mock data, no API calls
```

## Key Files
| File | Purpose |
|---|---|
| `main.py` | Orchestrator — auth, data gather, Claude call, print |
| `gmail_tool.py` | Gmail fetch by "Newsletter" label |
| `gcal_tool.py` | Calendar fetch + Magic Walk detection |
| `weather_tool.py` | IP geolocation (ipapi.co with ip-api.com fallback) + Open-Meteo |

## Newsletter Config
`gmail_tool.py` fetches up to **10** emails from the Gmail label **"Projects/Newsletter"** from the last 36 hours that haven't already been labeled **"Projects/Briefed"**.

To include a newsletter, label it **"Projects/Newsletter"** in Gmail — no code changes needed.
After a briefing runs, processed emails are moved to **"Projects/Briefed"** to prevent re-processing.

Each newsletter body is capped at **15,000 characters** before being passed to Claude.

Summarization rules (in `SYSTEM_PROMPT` in `main.py`):
- **All newsletters**: summarize all editorial content; skip ads and sponsored content
- **Axios Pro Rata**: only include deals involving AI companies; skip all non-AI deals
- AI-related content is highlighted across all newsletters

## Magic Walk Detection
`gcal_tool.py` scans for `"magic walk"` (case-insensitive) in event title or description.
Keyword is set in `MAGIC_WALK_KEYWORD` at the top of that file.

## Google OAuth
`main.py` wraps `flow.authorization_url` to open the browser via macOS `open` (subprocess),
then calls `flow.run_local_server(port=0, open_browser=False)` to handle the redirect.
On first run, a `token.json` is written. Subsequent runs load and auto-refresh it.

## Secrets (never commit)
| File | Contains |
|---|---|
| `.env` | `ANTHROPIC_API_KEY` |
| `credentials.json` | Google OAuth client secrets |
| `token.json` | Cached OAuth token (auto-created on first run) |

## Scheduling
Runs via GitHub Actions at 9 AM PT daily (see `.github/workflows/morning-briefing.yml`).
Required secrets: `ANTHROPIC_API_KEY`, `GOOGLE_CREDENTIALS_JSON`, `GOOGLE_TOKEN_JSON`.
