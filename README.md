# Morning Briefing Agent

A personal AI assistant that runs every morning at 9 AM and delivers a synthesized daily briefing — pulling live data from Gmail, Google Calendar, and weather APIs, then using Claude to distill it into a clean, scannable summary.

Built to replace the habit of opening 5+ tabs every morning before being able to focus.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

🌤 Weather
Overcast in San Francisco with a high of 61°F and low of 46°F. No rain expected.

📅 Today's Calendar
12:45 PM — Neil Rangwani <> Tina Bao | The CAM Collective @ Microsoft Teams

📬 Newsletter Highlights

Ben's Bites
• OpenAI released GPT-5.4 in "thinking" and "pro" variants with 1M token context
  window, improved vision, tool use, and computer use capabilities
• Anthropic enterprise releases: Code Review by Claude and Claude Marketplace
• Yann LeCun's new startup AMI Labs raised over $1B at $3.5B valuation

Lenny's Newsletter
• Advanced B2B positioning guide from April Dunford covering four patterns where
  teams encounter roadblocks during positioning development

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

## How it works

1. **Auth** — OAuth 2.0 flow authenticates once; token refreshes automatically on every run
2. **Fetch** — pulls today's calendar events, scans Gmail for newsletters from the last 24 hours, and gets a live weather forecast via Open-Meteo
3. **Synthesize** — structured data is passed to Claude Haiku with a custom system prompt; Claude extracts only what's relevant for each source (e.g. "VC deals involving AI companies only" for Axios Pro Rata)
4. **Output** — formatted briefing prints to terminal; scheduled via cron or GitHub Actions

## Stack

| Layer | Technology |
|---|---|
| Language | Python 3.10+ |
| AI synthesis | Anthropic Claude Haiku (`claude-haiku-4-5`) |
| Email | Gmail API (OAuth 2.0, read-only) |
| Calendar | Google Calendar API (OAuth 2.0, read-only) |
| Weather | Open-Meteo API (free, no key) |
| Geolocation | ipapi.co / ip-api.com (free tier, with fallback) |
| Scheduling | cron or GitHub Actions |

## Project structure

```
morning-briefing/
├── main.py           # Orchestrator — auth, fetch, Claude call, print
├── gmail_tool.py     # Gmail fetch + newsletter config (NEWSLETTERS list)
├── gcal_tool.py      # Calendar fetch + Magic Walk detection
├── weather_tool.py   # IP geolocation + Open-Meteo forecast
├── .github/
│   └── workflows/
│       └── morning-briefing.yml  # Scheduled GitHub Actions workflow
├── .env.example      # API key template
├── requirements.txt
└── README.md
```

## Setup

### 1. Clone and install

```bash
git clone https://github.com/neilrangwani/morning-briefing
cd morning-briefing
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Add your Anthropic API key

```bash
cp .env.example .env
# Edit .env:
# ANTHROPIC_API_KEY=sk-ant-...
```

Get a key at [console.anthropic.com](https://console.anthropic.com).

### 3. Create Google OAuth credentials

The app needs read-only access to Gmail and Google Calendar.

1. Go to [Google Cloud Console](https://console.cloud.google.com/)
2. Create a project and enable the **Gmail API** and **Google Calendar API**
3. Go to **APIs & Services → Credentials → Create Credentials → OAuth client ID**
   - Application type: **Desktop app**
4. Download the JSON and save it as `credentials.json` in this folder

> `credentials.json` is gitignored — never commit it.

### 4. First run

```bash
python main.py
```

A URL will be printed — open it in your browser to authorize Google access. A `token.json` is saved locally and reused on every future run.

### 5. Test with mock data

```bash
python main.py --dry-run
```

Uses hardcoded mock data and still calls Claude — useful for testing the prompt and output format without touching Google APIs.

---

## Customizing newsletters

Edit the `NEWSLETTERS` list in `gmail_tool.py`. Each entry controls what gets fetched and how Claude should summarize it:

```python
{
    "name": "Display name",
    "from_match": ["keyword in From header"],  # OR logic, case-insensitive
    "subject_match": ["keyword in Subject"],   # OR logic; omit to skip
    "interest": "What to extract — passed directly to Claude as an instruction",
    "include_links": False,  # True = Claude includes URLs in output
}
```

---

## Scheduling

### Option A: Local cron (runs on your machine)

```bash
# Run at 9:00 AM daily
(crontab -l 2>/dev/null; echo "0 9 * * * cd $HOME/morning-briefing && $HOME/morning-briefing/.venv/bin/python main.py >> $HOME/morning-briefing/briefing.log 2>&1") | crontab -
```

### Option B: GitHub Actions (runs in the cloud, free)

1. Push to GitHub
2. Add three repository secrets (**Settings → Secrets and variables → Actions**):

| Secret | Value |
|---|---|
| `ANTHROPIC_API_KEY` | Your Anthropic API key |
| `GOOGLE_CREDENTIALS_JSON` | Full contents of `credentials.json` |
| `GOOGLE_TOKEN_JSON` | Full contents of `token.json` |

3. The workflow in `.github/workflows/morning-briefing.yml` runs automatically at 9 AM PT. Trigger a manual run anytime via **Actions → Morning Briefing → Run workflow**.

> The refresh token in `token.json` is permanent — GitHub Actions will automatically get fresh access tokens on every run without any manual intervention.
