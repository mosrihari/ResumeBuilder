import os
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

load_dotenv()

SERVICE_ACCOUNT_FILE = "service_account.json"
SPREADSHEET_NAME = os.getenv("SPREADSHEET_NAME", "Job_Application_Tracker")
DETAILED_RESUME_TXT_ID = os.getenv("DETAILED_RESUME_TXT_ID")
SARVAM_API_KEY = os.getenv("SARVAM_API_KEY")
SARVAM_MODEL = "sarvam-105b"
SARVAM_REASONING_EFFORT = "low"
SARVAM_MAX_TOKENS = 4096  # starter-tier ceiling for sarvam-105b

SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets",
]

PROMPT_PATH = Path(__file__).resolve().parents[1] / "prompts" / "resume_enhance_prompt.txt"

APPLIED_HEADER = "Applied"
JD_HEADER = "Job Description (full JD text)"
COMPANY_HEADER = "Company"

OUTPUT_HEADERS = ["Resume Bullet Points", "Cover Letter", "Referral Request"]

SARVAM_MAX_ATTEMPTS = 5
SARVAM_BACKOFF_SECONDS = [5, 15, 30, 30]
SARVAM_INTER_CALL_DELAY_SECONDS = 2

IST = ZoneInfo("Asia/Kolkata")


def today_tab_name() -> str:
    return f"JobTracker_{datetime.now(IST):%y%m%d}"
