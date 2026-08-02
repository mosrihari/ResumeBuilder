import datetime
import io
import json
import os
import time
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from google import genai
from google.genai import types
from google.genai.errors import APIError
import gspread
import pdfplumber
from tavily import TavilyClient

# Load Environment Variables
load_dotenv()

TAVILY_KEY = os.getenv("TAVILY_API_KEY")
GEMINI_KEY = os.getenv("GOOGLE_API_KEY")
RESUME_FILE_ID = os.getenv("GOOGLE_DRIVE_RESUME_ID")
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Job_Application_Tracker")
SERVICE_ACCOUNT_FILE = "service_account.json"

# Search Parameters
TARGET_ROLES = ["Data Scientist", "Machine Learning Engineer", "AI Specialist"]
TARGET_LOCATION = "Singapore"
MAX_DAILY_MATCHES = 20

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
# STEP 3: SOURCE JOBS VIA TAVILY (1 Credit)
# ------------------------------------------------------------------
def source_jobs_tavily():
    print("[3/5] Querying Tavily for Singapore ATS postings...")
    tavily = TavilyClient(api_key=TAVILY_KEY)
    domains = [
        "boards.greenhouse.io",
        "jobs.lever.co",
        "jobs.ashbyhq.com",
        "jobs.smartrecruiters.com",
        "myworkdayjobs.com",
        "icims.com",
        "apply.workable.com",
    ]

    roles_query = " OR ".join([f'"{role}"' for role in TARGET_ROLES])
    query_str = f"({roles_query}) {TARGET_LOCATION}"

    response = tavily.search(
        query=query_str,
        include_domains=domains,
        search_depth="basic",
        max_results=30,
    )
    return response.get("results", [])


# ------------------------------------------------------------------
# STEP 4: CONSOLIDATE & SCORE WITH GEMINI
# ------------------------------------------------------------------
def analyze_and_score(master_cv, raw_hits):
    print("[4/5] Evaluating fit and generating application assets...")
    client = genai.Client(api_key=GEMINI_KEY)

    prompt = f"""
    You are an AI Executive Recruiter evaluating job matches for a candidate.

    CANDIDATE MASTER CV:
    {master_cv}

    RAW JOB LISTINGS:
    {json.dumps(raw_hits, indent=2)}

    INSTRUCTIONS:
    1. Deduplicate roles and filter strictly for {TARGET_LOCATION}.
    2. Calculate a Match Score (0-100%) against the Master CV.
    3. Select strictly the TOP {MAX_DAILY_MATCHES} highest-scoring roles.
    4. For EACH selected role generate:
       - 3 tailored XYZ-format resume bullet points using ONLY verified facts from the Master CV (DO NOT LIE/FABRICATE).
       - A 3-sentence LinkedIn referral/outreach message.
       - A 3-paragraph tailored cover letter addressing specific requirements in the posting.

    Return STRICTLY a JSON array of up to {MAX_DAILY_MATCHES} objects:
    [
      {{
        "company": "Company Name",
        "job_title": "Clean Title",
        "match_score": 88,
        "url": "Direct Application URL",
        "skill_gaps": ["Missing Skill 1", "Missing Skill 2"],
        "tailored_bullets": ["Bullet 1", "Bullet 2", "Bullet 3"],
        "referral_message": "Referral text...",
        "cover_letter": "Cover letter text..."
      }}
    ]
    """

    for attempt in range(3):
        try:
            response = client.models.generate_content(
                model="gemini-3.6-flash",
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json"
                ),
            )
            return json.loads(response.text)
        except APIError as e:
            if "429" in str(e):
                print(f"⚠️ Rate limit hit. Waiting {(attempt + 1) * 15}s...")
                time.sleep((attempt + 1) * 15)
            else:
                raise e
    return []


# ------------------------------------------------------------------
# STEP 5: PUSH TO GOOGLE SHEETS (TAB FORMAT: YYYY-MM-DD_job_track)
# ------------------------------------------------------------------
def push_to_google_sheet(evaluated_jobs):
    print("[5/5] Writing top 20 matches to Google Sheets...")
    gc = gspread.service_account(filename=SERVICE_ACCOUNT_FILE)
    sh = gc.open(SPREADSHEET_NAME)

    # Dynamic Tab Name Format: YYYY-MM-DD_job_track
    today_str = datetime.datetime.now().strftime("%Y-%m-%d")
    tab_name = f"{today_str}_job_track"

    try:
        worksheet = sh.add_worksheet(title=tab_name, rows="50", cols="10")
    except gspread.exceptions.APIError:
        worksheet = sh.worksheet(tab_name)

    # Sheet Column Structure
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

    # Append Top 20 Job Rows
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
        f"  -> Successfully updated sheet tab '{tab_name}' with {len(evaluated_jobs)} jobs!"
    )


# ------------------------------------------------------------------
# MAIN PIPELINE EXECUTION
# ------------------------------------------------------------------
if __name__ == "__main__":
    # 1. Download Master CV from Drive
    pdf_buffer = fetch_resume_from_drive()

    # 2. Extract CV text via pdfplumber
    master_cv_text = parse_resume_text(pdf_buffer)

    # 3. Fetch jobs via Tavily
    raw_hits = source_jobs_tavily()

    # 4. Filter, score, and draft with Gemini
    top_jobs = analyze_and_score(master_cv_text, raw_hits)

    # 5. Push to Google Sheets under tab: YYYY-MM-DD_job_track
    if top_jobs:
        push_to_google_sheet(top_jobs)
    else:
        print("No valid jobs returned.")