# ResumeBuilder — Daily Resume Tailoring Pipeline

Automates the second half of a daily job-search workflow:

1. **9AM IST (external, not in this repo)** — a Sarvam "interactive portal" job runs job-search + market-research prompts and writes results into a Google Sheet (`Job_Application_Tracker`), one tab per day named `JobTracker_YYMMDD`.
2. **You** mark the `Applied` column `TRUE` for any row you've applied to.
3. **6PM IST (this repo, via GitHub Actions)** — reads today's tab, finds every row with `Applied == TRUE`, and for each one uses Sarvam's `sarvam-105b` model to generate tailored resume bullet points, a cover letter, and a referral request message against that specific job description — then writes the results back into the same row.

## How it works

```mermaid
flowchart TD
    A["9AM IST daily<br/>Sarvam interactive portal<br/>(external, not in this repo)"] -->|writes daily tab| B[("Google Sheet<br/>Job_Application_Tracker<br/>tab: JobTracker_YYMMDD")]
    B --> C{"You mark<br/>Applied = TRUE<br/>on rows you applied to"}
    C --> D["6PM IST daily<br/>GitHub Actions cron<br/>(resume_tailor.yml)"]
    D --> E["Fetch detailed resume<br/>from Google Drive<br/>(.txt or PDF)"]
    D --> F["Read today's tab<br/>filter rows where Applied == TRUE"]
    E --> G["For each Job Description:<br/>call Sarvam sarvam-105b"]
    F --> G
    G --> H["Parse JSON response:<br/>resume_bullets, cover_letter,<br/>referral_request"]
    H --> I[("Write back into the same row<br/>3 new columns in the sheet")]
```

## Repo structure

```
src/
  automation/           # the production pipeline
    config.py           # env vars, constants, today's tab-name logic
    sheet_client.py      # Google Sheets read/write (gspread)
    drive_client.py       # downloads the detailed resume text from Google Drive
    sarvam_client.py      # calls Sarvam AI (sarvam-105b) with retry/backoff
    response_parser.py    # parses Sarvam's JSON response robustly
    prompt.py              # renders the resume_enhance_prompt.txt template
    run_pipeline.py         # entrypoint — orchestrates the whole run
  prompts/
    resume_enhance_prompt.txt   # the LLM prompt template
  scratch/                # exploratory trial scripts (reference only, not used in production)
.github/workflows/
  resume_tailor.yml       # daily cron (6PM IST) + manual trigger
requirements.txt
Dockerfile, docker-compose.yml
```

## Prerequisites

- A Google Cloud **service account** with:
  - Access scopes: Google Drive (read) and Google Sheets
  - Shared as an editor on the `Job_Application_Tracker` Google Sheet
  - Shared as a viewer on the Google Drive file containing your detailed resume (plain `.txt` or a `.pdf` export both work)
- A **Sarvam AI** API subscription key (`sarvam-105b` access)
- Python 3.12+ (if running locally without Docker) or Docker

## Setup

1. Copy `.env.example` to `.env` and fill in the values:
   ```
   SARVAM_API_KEY=...
   DETAILED_RESUME_TXT_ID=...   # Google Drive file ID of your detailed_resume.txt
   SPREADSHEET_NAME=Job_Application_Tracker   # optional, this is the default
   ```
2. Download your Google service account's JSON key and save it as `service_account.json` in the repo root (already gitignored — never commit this file).

## Running locally

**Without Docker:**
```
python -m venv venv
venv/Scripts/activate        # Windows; use `source venv/bin/activate` on macOS/Linux
pip install -r requirements.txt
python src/automation/run_pipeline.py
```

**With Docker:**
```
docker compose run --rm resume-tailor
```
This builds the image, mounts your `service_account.json` read-only, loads `.env`, and runs the pipeline once. It does not schedule anything by itself — scheduling is handled by GitHub Actions (see below) or you can trigger it manually whenever you want.

The pipeline is safe to run at any time: it always looks at the tab matching today's date (`JobTracker_YYMMDD` in Asia/Kolkata time) and only touches rows where `Applied == TRUE`. If today's tab doesn't exist yet (the 9AM job hasn't run), it aborts cleanly with a clear error instead of guessing.

## GitHub Actions (automated daily run)

The workflow at `.github/workflows/resume_tailor.yml` runs daily at 12:30 UTC (18:00 IST) and can also be triggered manually.

Before it can run, create these repository secrets (**Settings → Secrets and variables → Actions → New repository secret**):

| Secret name | Value |
|---|---|
| `GOOGLE_SERVICE_ACCOUNT_JSON` | Full contents of your `service_account.json` |
| `SARVAM_API_KEY` | Your Sarvam API key |
| `DETAILED_RESUME_TXT_ID` | Google Drive file ID of your detailed resume `.txt` |

These are encrypted secrets — safe to use even on a public repo, since this workflow only uses `schedule`/`workflow_dispatch` triggers (never `pull_request`), so forks never get access to them.

To test before trusting the schedule: **Actions tab → "Daily Resume Tailor" → "Run workflow"**.

## Expected Google Sheet schema

Each `JobTracker_YYMMDD` tab is expected to have its real header row on **row 2** (row 1 may be a section title/banner), with at least these columns:

`Company | ... | Job Description (full JD text) | Applied`

The pipeline appends three more columns the first time it runs against a tab: `Resume Bullet Points | Cover Letter | Referral Request`.

## Troubleshooting

- **`Worksheet '...' not found`** — today's tab hasn't been created yet by the 9AM job. Wait for it or check the upstream job.
- **A row gets `ERROR: ...` in its Resume Bullet Points cell** — that row's Sarvam call or JSON parsing failed after retries; other rows are unaffected. Check the Actions run log for the full error.
- **Sarvam returns empty content / `finish_reason=length`** — `sarvam-105b` is a reasoning model that can spend its whole token budget on internal reasoning before answering. `sarvam_client.py` already sets `reasoning_effort="low"` and `max_tokens=4096` (the starter-tier ceiling) to avoid this; if you're on a higher tier you can raise `SARVAM_MAX_TOKENS` in `config.py`.
- **`UnicodeDecodeError` fetching the resume** — `drive_client.py` auto-detects PDF vs. plain text (by checking for the `%PDF-` header) and extracts text accordingly via `pypdf`. If this still fails, the Drive file may be some other binary format (e.g. `.docx`) that isn't supported yet.
