import os
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

SERVICE_ACCOUNT_FILE = "service_account.json"
SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

def get_file_id_by_name(file_name="resume.txt"):
    creds = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    drive_service = build("drive", "v3", credentials=creds)

    # Search for non-trashed files matching the exact name
    query = f"name = '{file_name}' and trashed = false"
    results = drive_service.files().list(
        q=query, fields="files(id, name, mimeType)"
    ).execute()
    
    files = results.get("files", [])

    if not files:
        print(f"❌ No file found with name '{file_name}'. Make sure it's shared with your service account!")
        return None

    for f in files:
        print(f"✅ Found File: {f['name']}")
        print(f"   ID: {f['id']}")
        print(f"   MIME Type: {f['mimeType']}\n")
    
    return files[0]['id']

if __name__ == "__main__":
    get_file_id_by_name("detailed_resume.txt")