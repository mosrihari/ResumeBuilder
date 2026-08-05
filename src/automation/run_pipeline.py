import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config
import drive_client
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
        print("Nothing to process. Done.")
        return

    sarvam = sarvam_client.get_client()

    failures = []
    skipped = []
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
            print(f"[ok] {company} (row {row['row_number']})")
        except Exception as e:
            print(f"[error] {company} (row {row['row_number']}): {e}")
            sheet_client.write_row_error(ws, row["row_number"], col_map, str(e))
            failures.append(company)

        time.sleep(config.SARVAM_INTER_CALL_DELAY_SECONDS)

    succeeded = len(rows) - len(failures) - len(skipped)
    print(f"Done. {succeeded} succeeded, {len(failures)} failed: {failures}, {len(skipped)} skipped: {skipped}")


if __name__ == "__main__":
    main()
