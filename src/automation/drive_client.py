import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload
from pypdf import PdfReader


def _download_bytes(drive_service) -> bytes:
    request = drive_service.files().get_media(fileId=config.DETAILED_RESUME_TXT_ID)
    file_bytes = io.BytesIO()
    downloader = MediaIoBaseDownload(file_bytes, request)

    done = False
    while not done:
        _, done = downloader.next_chunk()

    return file_bytes.getvalue()


def _extract_pdf_text(raw: bytes) -> str:
    reader = PdfReader(io.BytesIO(raw))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def fetch_detailed_resume_text() -> str:
    if not config.DETAILED_RESUME_TXT_ID:
        raise ValueError("Missing environment variable: 'DETAILED_RESUME_TXT_ID' not found in .env")

    creds = Credentials.from_service_account_file(
        config.SERVICE_ACCOUNT_FILE, scopes=config.SCOPES
    )
    drive_service = build("drive", "v3", credentials=creds)

    raw = _download_bytes(drive_service)
    if raw.startswith(b"%PDF-"):
        return _extract_pdf_text(raw)

    # Retry on UnicodeDecodeError: an occasional transient network hiccup can corrupt
    # a byte in transit, and a fresh download is the fix (not a real encoding issue).
    last_error = None
    for _ in range(3):
        try:
            return raw.decode("utf-8")
        except UnicodeDecodeError as e:
            last_error = e
            raw = _download_bytes(drive_service)
    raise last_error
