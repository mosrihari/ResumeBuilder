import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config

import gspread


def get_gspread_client() -> gspread.Client:
    return gspread.service_account(filename=config.SERVICE_ACCOUNT_FILE)


def open_today_worksheet(gc: gspread.Client) -> gspread.Worksheet:
    sh = gc.open(config.SPREADSHEET_NAME)
    tab_name = config.today_tab_name()
    try:
        return sh.worksheet(tab_name)
    except gspread.exceptions.WorksheetNotFound:
        raise RuntimeError(
            f"Worksheet '{tab_name}' not found in spreadsheet '{config.SPREADSHEET_NAME}'. "
            "The 9AM job may not have run yet today."
        )


def find_col(headers: list[str], name: str) -> int | None:
    target = name.strip().lower()
    for i, h in enumerate(headers, start=1):
        if h.strip().lower() == target:
            return i
    return None


def ensure_output_headers(ws: gspread.Worksheet) -> dict[str, int]:
    headers = ws.row_values(2)
    existing = {h: find_col(headers, h) for h in config.OUTPUT_HEADERS}
    if all(v is not None for v in existing.values()):
        return existing

    start_col = len(headers) + 1
    end_col = start_col + len(config.OUTPUT_HEADERS) - 1
    cell_range = f"{gspread.utils.rowcol_to_a1(2, start_col)}:{gspread.utils.rowcol_to_a1(2, end_col)}"
    ws.update([config.OUTPUT_HEADERS], cell_range)

    headers = ws.row_values(2)
    return {h: find_col(headers, h) for h in config.OUTPUT_HEADERS}


def get_applied_rows(ws: gspread.Worksheet) -> list[dict]:
    values = ws.get_all_values()
    headers = values[1]  # real header row is row 2 (index 1); row 1 is a section banner
    applied_col = find_col(headers, config.APPLIED_HEADER)
    jd_col = find_col(headers, config.JD_HEADER)
    company_col = find_col(headers, config.COMPANY_HEADER)

    if applied_col is None:
        raise RuntimeError(f"Could not find '{config.APPLIED_HEADER}' header in row 2 of the sheet.")

    rows = []
    for row_number, row in enumerate(values[2:], start=3):
        if applied_col > len(row):
            continue
        if row[applied_col - 1].strip().upper() != "TRUE":
            continue
        company = row[company_col - 1] if company_col and company_col <= len(row) else ""
        job_description = row[jd_col - 1] if jd_col and jd_col <= len(row) else ""
        rows.append({"row_number": row_number, "company": company, "job_description": job_description})
    return rows


def write_row_result(
    ws: gspread.Worksheet,
    row_number: int,
    col_map: dict[str, int],
    resume_bullets: str,
    cover_letter: str,
    referral_request: str,
) -> None:
    start_col = col_map["Resume Bullet Points"]
    end_col = col_map["Referral Request"]
    cell_range = f"{gspread.utils.rowcol_to_a1(row_number, start_col)}:{gspread.utils.rowcol_to_a1(row_number, end_col)}"
    ws.update([[resume_bullets, cover_letter, referral_request]], cell_range)


def write_row_error(ws: gspread.Worksheet, row_number: int, col_map: dict[str, int], message: str) -> None:
    cell_range = gspread.utils.rowcol_to_a1(row_number, col_map["Resume Bullet Points"])
    ws.update([[f"ERROR: {message}"]], cell_range)
