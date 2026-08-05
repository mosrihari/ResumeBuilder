import io
import os
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Load environment variables from .env
load_dotenv()

# Read the file ID specifically from DETAILED_RESUME_TXT_ID
RESUME_FILE_ID = os.getenv("DETAILED_RESUME_TXT_ID")
SERVICE_ACCOUNT_FILE = "service_account.json"

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

def fetch_detailed_resume_from_drive():
    if not RESUME_FILE_ID:
        raise ValueError(
            "❌ Missing environment variable: 'DETAILED_RESUME_TXT_ID' not found in .env"
        )

    print("[1/1] Fetching detailed resume (.txt) from Google Drive...")
    
    # Authenticate with Google Drive API
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    drive_service = build("drive", "v3", credentials=creds)

    # Download file contents
    request = drive_service.files().get_media(fileId=RESUME_FILE_ID)
    file_bytes = io.BytesIO()
    downloader = MediaIoBaseDownload(file_bytes, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    # Decode bytes directly to UTF-8 text string
    resume_text = file_bytes.getvalue().decode("utf-8")
    
    print(f"  -> Success! Loaded {len(resume_text)} characters from Drive.")
    return resume_text


if __name__ == "__main__":
    try:
        detailed_resume_text = fetch_detailed_resume_from_drive()
        print("\n--- RESUME PREVIEW (First 300 chars) ---")
        print(detailed_resume_text[:300] + "...\n")
    except Exception as e:
        print(f"❌ Error downloading file: {e}")