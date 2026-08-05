# Daily Resume-Tailoring Pipeline via GitHub Actions

## Context

An external "Sarvam interactive portal" job already runs at 9AM IST, doing job search + market research, and writes results into a Google Sheet (`Job_Application_Tracker`) as a new tab each day (`JobTracker_YYMMDD`). That part is out of scope — it's not code in this repo and won't be touched.

What's missing is the second half: at 7PM IST, look at today's tab, find the rows the user has manually marked `Applied = TRUE`, and for each one, tailor the resume + write a cover letter + referral request against that specific job description using Sarvam's `sarvam-105b` model, then write the results back into the same row. Currently none of this exists — no `requirements.txt`, no `.github/workflows/`, no production package (only trial scripts in `src/scratch/`).

I read the live sheet directly (read-only) to confirm its real structure rather than guessing, since getting the schema wrong would silently corrupt output. Key finding: it's not one flat table — it's two stacked sections ("PROMPT 1 — HIRING SIGNALS" and "PROMPT 2 — RECENT JOBS") separated by banner/blank rows, sharing one header row (row 2, not row 1). The `Applied` column holds literal text `"TRUE"`/`"FALSE"`. Filtering directly on `Applied == "TRUE"` cleanly selects real data rows from both sections without needing to special-case banners or blanks.

User decisions already made (not open questions):
- No idempotency/skip logic — each day's tab is fresh, so it's fine to (re)write output columns for every `Applied == TRUE` row on every run.
- Extend `resume_enhance_prompt.txt` to also produce a referral request, so **one** Sarvam call per JD returns all three outputs.
- Repo can stay public — GitHub encrypted secrets are safe here because the workflow only uses `schedule`/`workflow_dispatch` triggers, never `pull_request`, so there's no fork-secret-leak exposure.

## New Python package: `src/automation/`

Flat modules (no `__init__.py`, matching the existing flat style of `src/scratch/`), each doing a local `sys.path` bootstrap so they import each other and run standalone via `python src/automation/run_pipeline.py`.

**`config.py`** — env loading (`load_dotenv()`), constants: `SERVICE_ACCOUNT_FILE`, `SPREADSHEET_NAME` (default `"Job_Application_Tracker"`), `DETAILED_RESUME_TXT_ID`, `SARVAM_API_KEY`, `SARVAM_MODEL = "sarvam-105b"`, Sheets+Drive `SCOPES`, header-name constants (`APPLIED_HEADER = "Applied"`, `JD_HEADER = "Job Description (full JD text)"`, `COMPANY_HEADER = "Company"`), `OUTPUT_HEADERS = ["Resume Bullet Points", "Cover Letter", "Referral Request"]`, retry knobs (`SARVAM_MAX_ATTEMPTS = 3`, backoff `[5, 15, 30]`, inter-call delay `2s`), and `today_tab_name()` using `datetime.now(ZoneInfo("Asia/Kolkata"))` → `f"JobTracker_{dt:%y%m%d}"`.

**`sheet_client.py`** — reuses the `gspread.service_account(filename=...)` auth pattern from `src/scratch/google_scope.py`:
- `open_today_worksheet(gc)` — opens `sh.worksheet(config.today_tab_name())`; raises if the tab doesn't exist (fatal — the 9AM job should have created it).
- `find_col(headers, name)` — case-insensitive header lookup, never hardcode column letters.
- `ensure_output_headers(ws)` — reads row 2, appends `OUTPUT_HEADERS` at `len(headers)+1` if not already present (idempotent across repeat runs), returns a `{header: col_index}` map.
- `get_applied_rows(ws)` — reads all values, headers = row 2 (index 1), iterates rows from index 2 onward, keeps a row only if its `Applied` cell (by header lookup) `== "TRUE"`. Returns `[{"row_number", "company", "job_description"}, ...]`.
- `write_row_result(ws, row_number, col_map, resume_bullets, cover_letter, referral_request)` — single batched `update()` call over the 3-column range (via `gspread.utils.rowcol_to_a1`).
- `write_row_error(ws, row_number, col_map, message)` — writes `f"ERROR: {message}"` into just the "Resume Bullet Points" cell for that row.

**`drive_client.py`** — reuses `src/scratch/fetch_detailed_resume.py` verbatim: `fetch_detailed_resume_text()` downloads via `drive_service.files().get_media(fileId=DETAILED_RESUME_TXT_ID)` + `MediaIoBaseDownload`, decodes UTF-8. Raises on failure (treated as fatal by the caller).

**`sarvam_client.py`** — `get_client()` (`SarvamAI(api_subscription_key=...)`), `call_sarvam(client, messages)` using the confirmed signature `client.chat.completions(model="sarvam-105b", messages=[...])` → `response.choices[0].message.content`, wrapped in a 3-attempt retry loop with backoff `[5, 15, 30]`s.

**`response_parser.py`** — `strip_code_fence(text)` (regex strips ```` ``` ```` / ```` ```json ```` fences), `parse_response(raw_text)` (try `json.loads`, on failure slice from first `{` to last `}` and retry, else raise `ResponseParseError`). Validates required keys `resume_bullets`, `cover_letter`, `referral_request` are present.

**`prompt.py`** — `load_template()` reads `src/prompts/resume_enhance_prompt.txt` once. `render(job_description, detailed_resume_text)` uses **`.replace()`, not `str.format()`** — the new prompt's JSON example is full of literal `{ }` braces that would break `str.format()`. `build_messages(...)` wraps it into the system+user message list.

**`run_pipeline.py`** (entrypoint, run via `python src/automation/run_pipeline.py`):
1. Fetch resume text (fatal if it fails — nothing to tailor against).
2. Open today's worksheet (fatal if tab missing), ensure output headers, get applied rows.
3. For each row: skip if JD is empty; else call Sarvam, parse JSON (one forced-JSON repair retry on parse failure), write results; on any exception, log it and write an `ERROR:` marker into that row only — **never abort the whole run over one bad row**. Small sleep between rows.
4. Print a final `N succeeded / M failed` summary; exits non-zero only on the fatal cases (missing resume / missing tab), not on individual row failures.

## Prompt update: `src/prompts/resume_enhance_prompt.txt`

Extend the existing prompt (rewrite CV + cover letter) to also request a referral request, and switch the output contract to strict JSON so it can be parsed reliably:

```
Act as a Senior Technical Recruiter and resume strategist hiring for this role.

Job Description:
{job_description}

Candidate's Detailed Resume:
{detailed_resume_text}

Task:
Using ONLY verified facts from the candidate's resume above, produce three things tailored specifically to this job description:
1. Rewritten resume bullet points that maximize match for this role.
2. A kickass, concise cover letter for this role.
3. A short referral request message the candidate could send to a contact or employee at the hiring company, asking for a referral for this specific role.

Rules:
1) Mirror keywords and phrases from the job description.
2) Reframe the candidate's real experience to align with their requirements.
3) Remove or minimize irrelevant experience.
4) Quantify impact wherever the resume provides numbers to support it.
5) Keep resume bullets ATS-friendly and concise (aim for content that fits 1 page, maximum 1.5 pages).
6) Where relevant and truthful, mention the candidate's Singapore experience and the COMPASS project mentioned in their resume.
7) Keep the cover letter brief, focused on the role and how the candidate is a good fit for it, not a restatement of the whole resume.
8) Keep the referral request brief (3-5 sentences), warm and specific to the role and company, not generic.
9) Never hallucinate or state anything false. Credibility and trust are of utmost importance — use only what is explicitly supported by the resume above.

Output format — this will be parsed by a program:
Return ONLY a single valid JSON object and nothing else. No markdown code fences, no prose before or after.
{
  "resume_bullets": "Tailored bullets as one string, bullets separated by newline, each starting with '- '.",
  "cover_letter": "Full cover letter as one string, paragraphs separated by two newlines.",
  "referral_request": "Full referral request message as one string.",
  "keywords_added": ["keyword1", "keyword2"],
  "changes_summary": "Brief explanation of the changes made."
}
Ensure the JSON is syntactically valid: escape quotes/newlines correctly inside string values.
```
(`keywords_added` / `changes_summary` are logged to console for visibility but not written to the sheet — only 3 output columns per spec.)

## Sheet write-back

New headers appended once at row 2 (dynamically, not hardcoded to H/I/J, so it stays correct if the 9AM job's column count ever changes): `Resume Bullet Points | Cover Letter | Referral Request`. Since section 2 shares the same columns with no repeated header, this needs no per-section handling — rows are written by row number directly regardless of which section they're in.

## `requirements.txt` (new file)

Pinned to versions already verified installed in the local venv:
```
gspread>=6.2.1,<7
google-api-python-client>=2.198.0,<3
google-auth>=2.56.2,<3
sarvamai>=0.1.30,<0.2
python-dotenv>=1.2.2,<2
tzdata>=2025.2
```
`tzdata` is required for `zoneinfo.ZoneInfo("Asia/Kolkata")` to work on Windows (confirmed it's missing locally); harmless no-op on the Linux Actions runner.

## GitHub Actions workflow: `.github/workflows/resume_tailor.yml`

```yaml
name: Daily Resume Tailor

on:
  schedule:
    - cron: "30 13 * * *"   # 13:30 UTC = 19:00 IST daily (IST has no DST, so this offset never needs adjustment)
  workflow_dispatch: {}

jobs:
  tailor:
    runs-on: ubuntu-latest
    timeout-minutes: 20
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - name: Install dependencies
        run: pip install -r requirements.txt
      - name: Reconstruct service account credentials
        env:
          GOOGLE_SERVICE_ACCOUNT_JSON: ${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON }}
        run: printf '%s' "$GOOGLE_SERVICE_ACCOUNT_JSON" > service_account.json
      - name: Run resume tailoring pipeline
        env:
          SARVAM_API_KEY: ${{ secrets.SARVAM_API_KEY }}
          DETAILED_RESUME_TXT_ID: ${{ secrets.DETAILED_RESUME_TXT_ID }}
        run: python src/automation/run_pipeline.py
      - name: Clean up credentials
        if: always()
        run: rm -f service_account.json
```

**GitHub Secrets to create manually** (Settings → Secrets and variables → Actions — the user does this via GitHub UI, no secret values are ever committed or pasted into the repo):
- `GOOGLE_SERVICE_ACCOUNT_JSON` — full contents of `service_account.json`
- `SARVAM_API_KEY`
- `DETAILED_RESUME_TXT_ID`

Public-repo safety note: these are encrypted secrets, masked in logs, and only injected for workflow runs triggered from the base repo. Since this workflow never uses `pull_request`, there's no path for a fork to exfiltrate them — safe to keep the repo public.

Caveats to flag to the user: GitHub Actions cron can be delayed several minutes under platform load (not exact-second); GitHub auto-disables scheduled workflows after 60 days of repo inactivity (no commits) until manually re-enabled or a new push occurs.

## Error handling

- Drive resume fetch fails → fatal, abort before touching the sheet (nothing to tailor against).
- Today's tab doesn't exist → fatal, abort (signals an upstream 9AM-job problem).
- Empty JD on an `Applied=TRUE` row → skip that row only, log it, continue.
- Sarvam call fails or returns unparseable JSON after one repair retry → caught per-row, `ERROR: ...` written to that row's Resume Bullet Points cell only, loop continues. A single bad row never aborts the run.
- Rate limiting: 2s delay between rows, 3-attempt exponential backoff (5/15/30s) per Sarvam call; sheet writes batched to one `update()` per row, well under Sheets API quota for expected ~20-40 rows/day.
- `timeout-minutes: 20` as a hard backstop on the Actions job.

## Verification plan

**Local dry run first:**
1. `venv/Scripts/python.exe -m pip install tzdata` (only new dependency needed locally — everything else already installed).
2. Add `resume_enhance_prompt.txt` update, create `src/automation/*.py`, `requirements.txt`.
3. Run `venv/Scripts/python.exe src/automation/run_pipeline.py` from repo root against today's real tab; confirm `[ok]`/`[skip]`/`[error]` console output per row, then check the sheet: columns for Resume Bullet Points/Cover Letter/Referral Request populated only on `Applied == TRUE` rows, untouched elsewhere.
4. Test failure paths: bogus `SARVAM_API_KEY` → confirm one row gets `ERROR:` and run still completes; bogus `DETAILED_RESUME_TXT_ID` → confirm whole run aborts cleanly with no partial writes.

**End-to-end in GitHub Actions before trusting the schedule:**
1. Push workflow + code, create the 3 repo secrets via GitHub UI.
2. Actions tab → "Daily Resume Tailor" → "Run workflow" (`workflow_dispatch`) to trigger manually.
3. Check run logs match local dry-run behavior; check the live sheet for correct write-back.
4. Only trust the 13:30 UTC daily schedule after a clean manual run, and watch the first couple of scheduled runs' logs afterward.

### Files to create
- `src/automation/config.py`, `sheet_client.py`, `drive_client.py`, `sarvam_client.py`, `response_parser.py`, `prompt.py`, `run_pipeline.py`
- `src/prompts/resume_enhance_prompt.txt` (modified)
- `requirements.txt` (new)
- `.github/workflows/resume_tailor.yml` (new)
