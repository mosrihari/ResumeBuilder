import io
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

from google.oauth2.credentials import Credentials as UserCredentials
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
from pypdf import PdfReader

_INVALID_NAME_CHARS_RE = re.compile(r"['\"/\\?*\x00-\x1f]")

DOCX_MIME_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"


def get_drive_service():
    creds = Credentials.from_service_account_file(
        config.SERVICE_ACCOUNT_FILE, scopes=config.SCOPES
    )
    return build("drive", "v3", credentials=creds)


def get_drive_write_service():
    if not (config.GOOGLE_OAUTH_CLIENT_ID and config.GOOGLE_OAUTH_CLIENT_SECRET and config.GOOGLE_OAUTH_REFRESH_TOKEN):
        raise ValueError(
            "Missing GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET / GOOGLE_OAUTH_REFRESH_TOKEN "
            "(required to write tailored docs to Drive under the user's own storage quota)."
        )
    creds = UserCredentials(
        token=None,
        refresh_token=config.GOOGLE_OAUTH_REFRESH_TOKEN,
        client_id=config.GOOGLE_OAUTH_CLIENT_ID,
        client_secret=config.GOOGLE_OAUTH_CLIENT_SECRET,
        token_uri="https://oauth2.googleapis.com/token",
        scopes=config.OAUTH_SCOPES,
    )
    return build("drive", "v3", credentials=creds)


def sanitize_name(text: str) -> str:
    cleaned = _INVALID_NAME_CHARS_RE.sub("", text or "").strip()
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned[:50].strip() or "Unknown"


def _escape_query_value(name: str) -> str:
    return name.replace("\\", "\\\\").replace("'", "\\'")


def get_or_create_folder(drive_service, parent_id: str, name: str) -> str:
    escaped = _escape_query_value(name)
    query = (
        f"'{parent_id}' in parents and name='{escaped}' "
        f"and mimeType='{FOLDER_MIME_TYPE}' and trashed=false"
    )
    results = drive_service.files().list(q=query, fields="files(id)", pageSize=1).execute()
    existing = results.get("files", [])
    if existing:
        return existing[0]["id"]

    metadata = {"name": name, "mimeType": FOLDER_MIME_TYPE, "parents": [parent_id]}
    folder = drive_service.files().create(body=metadata, fields="id").execute()
    return folder["id"]


def upload_or_replace_file(drive_service, folder_id: str, filename: str, content: bytes, mime_type: str) -> dict:
    escaped = _escape_query_value(filename)
    query = f"'{folder_id}' in parents and name='{escaped}' and trashed=false"
    results = drive_service.files().list(q=query, fields="files(id)", pageSize=1).execute()
    existing = results.get("files", [])

    media = MediaIoBaseUpload(io.BytesIO(content), mimetype=mime_type, resumable=False)

    if existing:
        return drive_service.files().update(
            fileId=existing[0]["id"], media_body=media, fields="id,webViewLink"
        ).execute()

    metadata = {"name": filename, "parents": [folder_id]}
    return drive_service.files().create(
        body=metadata, media_body=media, fields="id,webViewLink"
    ).execute()


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

    drive_service = get_drive_service()

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
