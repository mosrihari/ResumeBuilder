import io
import os
from dotenv import load_dotenv
import pdfplumber
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseDownload

# Load Environment Variables
load_dotenv()

RESUME_FILE_ID = os.getenv("GOOGLE_DRIVE_RESUME_ID")
SERVICE_ACCOUNT_FILE = "service_account.json"
OUTPUT_TXT_PATH = "resume.txt"

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]


def download_resume_from_drive():
    print("[1/2] Fetching resume PDF from Google Drive...")
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
    print("  -> Downloaded PDF successfully into memory.")
    return pdf_bytes


def convert_pdf_to_txt(pdf_stream, output_file_path=OUTPUT_TXT_PATH):
    print(f"[2/2] Extracting text with pdfplumber and writing to '{output_file_path}'...")
    extracted_text = ""

    with pdfplumber.open(pdf_stream) as pdf:
        for page_num, page in enumerate(pdf.pages, start=1):
            # layout=True preserves whitespace and multi-column visual layout
            page_text = page.extract_text(layout=True)
            if page_text:
                extracted_text += f"--- PAGE {page_num} ---\n" + page_text + "\n\n"

    # Save to local text file with UTF-8 encoding
    with open(output_file_path, "w", encoding="utf-8") as f:
        f.write(extracted_text)

    print(f"  -> Done! Saved {len(extracted_text)} characters to '{output_file_path}'.")


if __name__ == "__main__":
    try:
        pdf_buffer = download_resume_from_drive()
        convert_pdf_to_txt(pdf_buffer)
    except Exception as e:
        print(f"❌ Error extracting resume: {e}")