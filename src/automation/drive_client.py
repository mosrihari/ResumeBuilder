import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload


def fetch_detailed_resume_text() -> str:
    if not config.DETAILED_RESUME_TXT_ID:
        raise ValueError("Missing environment variable: 'DETAILED_RESUME_TXT_ID' not found in .env")

    creds = Credentials.from_service_account_file(
        config.SERVICE_ACCOUNT_FILE, scopes=config.SCOPES
    )
    drive_service = build("drive", "v3", credentials=creds)

    request = drive_service.files().get_media(fileId=config.DETAILED_RESUME_TXT_ID)
    file_bytes = io.BytesIO()
    downloader = MediaIoBaseDownload(file_bytes, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    return file_bytes.getvalue().decode("utf-8")
