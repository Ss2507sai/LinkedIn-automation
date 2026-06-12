# Wavity LinkedIn Sales Navigator Automation

Production-ready macOS automation that processes LinkedIn Sales Navigator prospects, extracts profile data, generates personalized Wavity outreach via ChatGPT (in your existing browser tab), and saves results to Excel and CSV.

**No LinkedIn API. No OpenAI API.** Everything runs through browser automation against your logged-in Chrome session.

## Prerequisites

- macOS
- Python 3.10+
- Google Chrome (logged into LinkedIn Sales Navigator and ChatGPT)
- LinkedIn Sales Navigator subscription

## Installation

1. Clone the repository and enter the project directory:

   ```bash
   cd LinkedIn-automation
   ```

2. Create and activate a virtual environment:

   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```

3. Install Python dependencies:

   ```bash
   pip install -r requirements.txt
   playwright install chrome
   ```

4. Copy the example environment file and adjust if needed:

   ```bash
   cp .env.example .env
   ```

## Setup

### 1. Launch Chrome with remote debugging

The automation attaches to your **existing** Chrome session via CDP. Chrome must be started with remote debugging enabled.

**Quit Chrome completely** (Cmd+Q), then launch:

```bash
chmod +x scripts/launch_chrome.sh
./scripts/launch_chrome.sh
```

Or manually:

```bash
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222
```

### 2. Open required tabs

Before starting the automation:

1. Open **LinkedIn Sales Navigator** and navigate to your saved search results page.
2. Open **ChatGPT** in another tab (stay logged in).

Leave both tabs open. The bot finds them automatically by URL pattern.

### 3. Verify CDP connection

With Chrome running, visit `http://127.0.0.1:9222/json` in another browser — you should see a JSON list of open tabs.

## Verify installation

Before connecting to your live Chrome session, confirm the project is wired correctly:

```bash
# Static + functional checks (no browser)
python -m src.main --verify

# Launch isolated Chrome and verify CDP + tab discovery
python -m src.main --smoke-browser
```

Both commands should exit with code 0.

## Running

### Test mode (recommended first run)

Processes only the first 3 prospects, saves results, then stops:

```bash
python -m src.main --test
```

Or via `.env`:

```bash
TEST_MODE=true python -m src.main
```

### Full mode

Processes all visible prospects, paginates through results, and runs until stopped (Ctrl+C):

```bash
python -m src.main --full
```

## What the bot does

For each prospect on the Sales Navigator results page:

1. Opens the profile in a new tab
2. Extracts name, title, company, headline, about, experience, location, and URL
3. Switches to the ChatGPT tab
4. Pastes the Wavity master prompt with profile data
5. Waits for ChatGPT to finish generating (DOM monitoring + stability checks)
6. Parses the structured response
7. Saves immediately to `results.xlsx` and `results.csv`
8. Records the profile URL in `processed_profiles.json` (duplicate prevention)
9. Returns to Sales Navigator and continues

After all visible prospects are done, it clicks **Next** and continues.

## Output files

| File | Purpose |
|------|---------|
| `results.xlsx` | Excel export with all outreach fields |
| `results.csv` | CSV export (same columns) |
| `processed_profiles.json` | Processed LinkedIn URLs for resume/duplicate skip |
| `logs/automation.log` | Detailed run log |
| `screenshots/` | Timestamped screenshots on errors |

### Result columns

Timestamp, Name, Title, Company, Location, Profile URL, Connection Request, Message 1, Message 2, Message 3, Likely Challenge, Wavity Use Case, Personalization Reason, Status

## Resume after crash

Restart the automation with the same Chrome session and Sales Navigator page:

```bash
python -m src.main --full
```

The bot loads `processed_profiles.json` and skips already-processed profiles automatically.

## Configuration

All settings are in `.env`. Key options:

| Variable | Default | Description |
|----------|---------|-------------|
| `CDP_URL` | `http://127.0.0.1:9222` | Chrome DevTools Protocol endpoint |
| `DELAY_MIN` / `DELAY_MAX` | `1.0` / `3.0` | Random human-like delay range (seconds) |
| `RETRY_COUNT` | `1` | Retries per prospect on failure |
| `TEST_MODE` | `false` | Limit run to `TEST_MODE_LIMIT` profiles |
| `HEADLESS` | `false` | Headless mode (persistent launch fallback only) |
| `CHATGPT_RESPONSE_TIMEOUT_SEC` | `180` | Max wait for ChatGPT response |

## Project structure

```
├── config/           # Settings and prompt templates
├── scrapers/         # Sales Navigator and LinkedIn profile extraction
├── chatgpt/          # ChatGPT tab interaction, waiting, parsing
├── storage/          # Excel, CSV, processed profile tracking
├── src/              # Browser manager, orchestrator, entry point
├── logs/             # automation.log
├── screenshots/      # Error screenshots
├── scripts/          # Chrome launch helper
├── requirements.txt
├── .env.example
└── README.md
```

## Troubleshooting

### "Could not connect to Chrome"

- Quit Chrome completely (Cmd+Q), then relaunch with `./scripts/launch_chrome.sh`
- Confirm `http://127.0.0.1:9222/json` returns tab data
- Check `CDP_URL` in `.env` matches your debug port

### "No open tab matching linkedin.com/sales"

- Open Sales Navigator search results in Chrome before starting
- Adjust `SALES_NAV_URL_PATTERN` in `.env` if your URL differs

### "No open tab matching chatgpt.com"

- Open ChatGPT in a Chrome tab before starting
- Adjust `CHATGPT_URL_PATTERN` if using a different URL

### ChatGPT timeout or empty response

- Ensure ChatGPT is logged in and not showing a login wall
- Increase `CHATGPT_RESPONSE_TIMEOUT_SEC`
- Check `logs/automation.log` and `screenshots/` for details

### LinkedIn layout changes

LinkedIn updates their DOM frequently. If extraction fails:

- Check screenshots in `screenshots/`
- Review `logs/automation.log` for selector errors
- Update selectors in `scrapers/sales_navigator.py` and `scrapers/linkedin_profile.py`

### Duplicate processing

Profiles are tracked by normalized LinkedIn URL in `processed_profiles.json`. Delete this file to reprocess all prospects.

### Stopping the bot

Press **Ctrl+C** for graceful shutdown. Results saved so far are preserved.

## Security notes

- Do not commit `.env` or output files containing prospect data
- This tool automates your personal browser session — use responsibly and in compliance with LinkedIn's Terms of Service
- Rate limiting via `DELAY_MIN` / `DELAY_MAX` helps avoid aggressive automation patterns

## Legacy React app

The `src/App.jsx` React outreach generator (Matterbeam) remains in the repo but is separate from this Python automation. Run it with `npm install && npm run dev` if needed.
