import datetime
import io
import json
import os
import time
from dotenv import load_dotenv
from google import genai
from google.genai import types
from google.genai.errors import APIError
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
import gspread
import pdfplumber

# Load Environment Variables
load_dotenv()

GEMINI_KEY = os.getenv("GOOGLE_API_KEY")
RESUME_FILE_ID = os.getenv("GOOGLE_DRIVE_RESUME_ID")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Job_Application_Tracker")
SERVICE_ACCOUNT_FILE = "service_account.json"

# Search Parameters
TARGET_ROLES = ["Data Scientist", "Machine Learning Engineer", "AI Specialist"]
TARGET_LOCATION = "Singapore"
MAX_DAILY_MATCHES = 20

# Primary supported model identifier
MODEL_NAME = "gemini-2.0-flash"

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]


# ------------------------------------------------------------------
# STEP 1: DOWNLOAD MASTER RESUME FROM GOOGLE DRIVE
# ------------------------------------------------------------------
def fetch_resume_from_drive():
    print("[1/5] Downloading Master Resume from Google Drive...")
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    drive_service = build("drive", "v3", credentials=creds)

    request = drive_service.files().get_media(fileId=RESUME_FILE_ID)
    pdf_bytes = io.BytesIO()
    downloader = MediaIoBaseDownload(pdf_bytes, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    pdf_bytes.seek(0)
    print("  -> Resume downloaded successfully into memory.")
    return pdf_bytes


# ------------------------------------------------------------------
# STEP 2: PARSE PDF WITH PDFPLUMBER
# ------------------------------------------------------------------
def parse_resume_text(pdf_stream):
    print("[2/5] Extracting text using pdfplumber...")
    extracted_text = ""
    with pdfplumber.open(pdf_stream) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                extracted_text += text + "\n"
    print(f"  -> Extracted {len(extracted_text)} characters.")
    return extracted_text


# ------------------------------------------------------------------
# STEP 3: LIGHTWEIGHT GROUNDED SEARCH (FETCH LIVE ATS LINKS ONLY)
# ------------------------------------------------------------------
def fetch_live_job_links():
    print("[3/5] Sourcing active ATS job links via Search Grounding...")
    client = genai.Client(api_key=GEMINI_KEY)
    roles_str = ", ".join(TARGET_ROLES)

    # Lightweight query prevents search rate-limit exhaustion
    search_prompt = f"""
    Search for active, live job postings in {TARGET_LOCATION} for the following roles: {roles_str}.
    Focus strictly on ATS portals (boards.greenhouse.io, jobs.lever.co, jobs.ashbyhq.com, jobs.smartrecruiters.com, myworkdayjobs.com).

    Return STRICTLY a JSON array of up to 25 objects:
    [
      {{
        "company": "Company Name",
        "job_title": "Job Title",
        "url": "Direct Active Application URL"
      }}
    ]
    """

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=search_prompt,
                config=types.GenerateContentConfig(
                    tools=[types.Tool(google_search=types.GoogleSearch())],
                    response_mime_type="application/json",
                ),
            )
            return json.loads(response.text)
        except APIError as e:
            if "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
                wait_time = (attempt + 1) * 20
                print(
                    f"⚠️ Search rate limit hit. Waiting {wait_time}s before retry..."
                )
                time.sleep(wait_time)
            else:
                raise e
        except json.JSONDecodeError:
            print("⚠️ Initial JSON parse failed. Retrying search...")
            time.sleep(5)

    print("❌ Failed to retrieve job links.")
    return []


# ------------------------------------------------------------------
# STEP 4: EVALUATE FIT & DRAFT ASSETS (NO SEARCH GROUNDING TOOL)
# ------------------------------------------------------------------
def analyze_and_score_jobs(master_cv, raw_jobs):
    print("[4/5] Scoring match quality and generating resume/cover letter assets...")
    if not raw_jobs:
        return []

    client = genai.Client(api_key=GEMINI_KEY)

    eval_prompt = f"""
    You are an AI Executive Recruiter evaluating job fit for a candidate.

    CANDIDATE MASTER CV:
    {master_cv}

    DISCOVERED JOB POSTINGS:
    {json.dumps(raw_jobs, indent=2)}

    INSTRUCTIONS:
    1. Filter out duplicate roles or non-{TARGET_LOCATION} positions.
    2. Score candidate fit from 0 to 100%.
    3. Select strictly the TOP {MAX_DAILY_MATCHES} highest-scoring positions.
    4. For EACH selected job generate:
       - 3 tailored XYZ-format resume bullet points strictly matching verified facts from the Master CV.
       - A 3-sentence LinkedIn referral outreach message.
       - A 3-paragraph tailored cover letter.

    Return STRICTLY a JSON array of up to {MAX_DAILY_MATCHES} objects:
    [
      {{
        "company": "Company Name",
        "job_title": "Clean Title",
        "match_score": 88,
        "url": "Direct Working Application URL",
        "skill_gaps": ["Missing Skill 1"],
        "tailored_bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
        "referral_message": "Referral text...",
        "cover_letter": "Cover letter text..."
      }}
    ]
    """

    for attempt in range(3):
        try:
            # Calling WITHOUT tools prevents hitting Search Rate Limits
            response = client.models.generate_content(
                model=MODEL_NAME,
                contents=eval_prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
            return json.loads(response.text)
        except APIError as e:
            if "429" in str(e):
                print(f"⚠️ API Limit hit. Waiting {(attempt + 1) * 15}s...")
                time.sleep((attempt + 1) * 15)
            else:
                raise e

    return []


# ------------------------------------------------------------------
# STEP 5: PUSH TO GOOGLE SHEETS (TAB: YYYY-MM-DD_job_track)
# ------------------------------------------------------------------
def push_to_google_sheet(evaluated_jobs):
    print("[5/5] Writing evaluated matches to Google Sheets...")
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    sh = gc.open(SPREADSHEET_NAME)

    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    tab_name = f"{today_str}_job_track"

    try:
        worksheet = sh.add_worksheet(title=tab_name, rows="50", cols="10")
    except gspread.exceptions.APIError:
        worksheet = sh.worksheet(tab_name)

    headers = [
        "Company",
        "Job Title",
        "Match Score (%)",
        "Application Link",
        "Skill Gaps",
        "Tailored Resume Bullets",
        "Referral Message",
        "Cover Letter",
        "Status",
    ]
    worksheet.append_row(headers)

    for job in evaluated_jobs:
        bullets_formatted = "\n• " + "\n• ".join(job.get("tailored_bullets", []))
        row = [
            job.get("company"),
            job.get("job_title"),
            f"{job.get('match_score')}%",
            job.get("url"),
            ", ".join(job.get("skill_gaps", [])),
            bullets_formatted,
            job.get("referral_message"),
            job.get("cover_letter"),
            "Pending Review",
        ]
        worksheet.append_row(row)

    print(
        f"  -> Successfully updated tab '{tab_name}' with {len(evaluated_jobs)} jobs!"
    )


# ------------------------------------------------------------------
# MAIN EXECUTION
# ------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Fetch CV from Google Drive
    pdf_buffer = fetch_resume_from_drive()

    # 2. Extract CV text
    master_cv_text = parse_resume_text(pdf_buffer)

    # 3. Step A: Search Grounding (Sourcing active URLs)
    raw_job_links = fetch_live_job_links()

    # 4. Step B: Gemini CV Analysis & Generation
    evaluated_jobs = analyze_and_score_jobs(master_cv_text, raw_job_links)

    # 5. Push output to Google Sheet
    if evaluated_jobs:
        push_to_google_sheet(evaluated_jobs)
    else:
        print("❌ No valid job matches processed.")