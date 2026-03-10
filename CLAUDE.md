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
| `gmail_tool.py` | Gmail fetch + `NEWSLETTERS` config |
| `gcal_tool.py` | Calendar fetch + Magic Walk detection |
| `weather_tool.py` | IP geolocation (ipapi.co with ip-api.com fallback) + Open-Meteo |

## Newsletter Config
Edit the `NEWSLETTERS` list in `gmail_tool.py`.
Each entry has `from_match`, `subject_match`, `interest`, and `include_links` fields.

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
