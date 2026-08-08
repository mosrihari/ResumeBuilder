import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
import docgen
import drive_client
import full_resume_prompt
import prompt
import response_parser
import sarvam_client
import sheet_client


def process_row(sarvam, resume_text, row):
    messages = prompt.build_messages(row["job_description"], resume_text)
    raw = sarvam_client.call_sarvam(sarvam, messages)

    try:
        parsed = response_parser.parse_response(raw)
    except response_parser.ResponseParseError:
        repair_messages = messages + [
            {
                "role": "user",
                "content": "Your previous reply was not valid JSON. Return ONLY the JSON object, no prose, no code fences.",
            }
        ]
        raw2 = sarvam_client.call_sarvam(sarvam, repair_messages)
        parsed = response_parser.parse_response(raw2)

    return parsed


def generate_docs(sarvam, drive_service, resume_text, row, cover_letter):
    full_resume_messages = full_resume_prompt.build_messages(row["job_description"], resume_text)
    full_resume_text = sarvam_client.call_sarvam(sarvam, full_resume_messages)

    resume_bytes = docgen.build_resume_docx(full_resume_text)
    cover_letter_bytes = docgen.build_cover_letter_docx(cover_letter)

    company = drive_client.sanitize_name(row["company"] or f"row{row['row_number']}")
    role = drive_client.sanitize_name(row["role"] or "role")
    folder_name = f"{company}_{role}"

    folder_id = drive_client.get_or_create_folder(drive_service, config.DRIVE_OUTPUT_FOLDER_ID, folder_name)

    resume_filename = f"{config.CANDIDATE_FILE_PREFIX}_{company}_{role}.docx"
    cover_letter_filename = f"{config.CANDIDATE_FILE_PREFIX}_{company}_{role}_CoverLetter.docx"

    drive_client.upload_or_replace_file(drive_service, folder_id, resume_filename, resume_bytes, drive_client.DOCX_MIME_TYPE)
    cover_letter_file = drive_client.upload_or_replace_file(
        drive_service, folder_id, cover_letter_filename, cover_letter_bytes, drive_client.DOCX_MIME_TYPE
    )

    return cover_letter_file.get("webViewLink") or f"https://drive.google.com/drive/folders/{folder_id}"


def main():
    print("Fetching detailed resume from Google Drive...")
    resume_text = drive_client.fetch_detailed_resume_text()
    print(f"  -> Loaded {len(resume_text)} characters.")

    gc = sheet_client.get_gspread_client()
    ws = sheet_client.open_today_worksheet(gc)
    col_map = sheet_client.ensure_output_headers(ws)

    rows = sheet_client.get_applied_rows(ws)
    print(f"Found {len(rows)} row(s) with Applied == TRUE.")

    if not rows:
        print("Nothing to process.")
    else:
        sarvam = sarvam_client.get_client()
        drive_write_service = drive_client.get_drive_write_service()

        failures = []
        skipped = []
        docs_failures = []
        for row in rows:
            company = row["company"] or f"row {row['row_number']}"
            if not row["job_description"].strip():
                print(f"[skip] {company} (row {row['row_number']}): empty job description")
                skipped.append(company)
                continue

            try:
                parsed = process_row(sarvam, resume_text, row)
                sheet_client.write_row_result(
                    ws,
                    row["row_number"],
                    col_map,
                    parsed["resume_bullets"],
                    parsed["cover_letter"],
                    parsed["referral_request"],
                )
                keywords_matched = ", ".join(parsed.get("keywords_added") or [])
                sheet_client.write_row_metadata(
                    ws, row["row_number"], col_map, keywords_matched, parsed.get("changes_summary", "")
                )
                print(f"[ok] {company} (row {row['row_number']})")
            except Exception as e:
                print(f"[error] {company} (row {row['row_number']}): {e}")
                sheet_client.write_row_error(ws, row["row_number"], col_map, str(e))
                failures.append(company)
                time.sleep(config.SARVAM_INTER_CALL_DELAY_SECONDS)
                continue

            try:
                folder_link = generate_docs(sarvam, drive_write_service, resume_text, row, parsed["cover_letter"])
                sheet_client.write_docs_folder_link(ws, row["row_number"], col_map, folder_link)
                print(f"[docs ok] {company} (row {row['row_number']})")
            except Exception as e:
                print(f"[docs error] {company} (row {row['row_number']}): {e}")
                sheet_client.write_docs_error(ws, row["row_number"], col_map, str(e))
                docs_failures.append(company)

            time.sleep(config.SARVAM_INTER_CALL_DELAY_SECONDS)

        succeeded = len(rows) - len(failures) - len(skipped)
        print(f"Done. {succeeded} succeeded, {len(failures)} failed: {failures}, {len(skipped)} skipped: {skipped}")
        if docs_failures:
            print(f"  ({len(docs_failures)} row(s) had doc-generation failures despite succeeding overall: {docs_failures})")

    ws.hide()
    print(f"Hid worksheet tab '{ws.title}'.")


if __name__ == "__main__":
    main()
