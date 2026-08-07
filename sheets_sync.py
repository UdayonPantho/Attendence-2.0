"""
Pushes a date-wise attendance table for a course into a shared Google Sheet.
One tab (worksheet) per course. Every sync fully rebuilds that course's tab
from attendance.db, so it always reflects the latest data.

One-time setup (see README.md for the full walkthrough):
  1. Google Cloud project -> enable "Google Sheets API"
  2. Create a Service Account -> download its JSON key as credentials.json
  3. Create a Google Sheet, share it with the service account's email
     (found inside credentials.json) as an Editor
  4. Set environment variables:
       GOOGLE_CREDENTIALS_FILE=credentials.json
       GOOGLE_SHEETS_SPREADSHEET_ID=<the long ID from the sheet's URL>

Usage from bot.py: sync_course_to_sheets("CSE2201DMS")
Usage standalone:   python sheets_sync.py CSE2201DMS
"""

import os
import sqlite3
import sys
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "attendance.db")
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "credentials.json")
SPREADSHEET_ID = os.environ.get("GOOGLE_SHEETS_SPREADSHEET_ID")

SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]

SHEETS_ENABLED = bool(SPREADSHEET_ID) and os.path.exists(CREDENTIALS_FILE)

if SHEETS_ENABLED:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build


# --------------------------------------------------------------------------
# DB helpers (standalone, independent of bot.py to avoid circular imports)
# --------------------------------------------------------------------------
def _conn():
    return sqlite3.connect(DB_PATH)


def _fetch_course_data(course_code: str):
    course_code = course_code.upper()
    conn = _conn()
    c = conn.cursor()

    c.execute("SELECT course_id FROM courses WHERE code=?", (course_code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return None

    course_id = row[0]

    c.execute(
        """SELECT u.user_id, u.first_name FROM users u
           JOIN enrollments e ON u.user_id = e.user_id
           WHERE e.course_id=? ORDER BY u.first_name""",
        (course_id,),
    )
    students = c.fetchall()  # [(user_id, first_name), ...]

    c.execute(
        "SELECT session_id, created_at FROM sessions WHERE course_id=? ORDER BY created_at",
        (course_id,),
    )
    sessions = c.fetchall()  # [(session_id, created_at), ...]

    responses = {}
    if sessions:
        session_ids = [s[0] for s in sessions]
        placeholders = ",".join("?" * len(session_ids))
        c.execute(
            f"SELECT session_id, user_id, response FROM attendance "
            f"WHERE session_id IN ({placeholders})",
            session_ids,
        )
        for session_id, user_id, response in c.fetchall():
            responses[(session_id, user_id)] = response

    conn.close()
    return {"students": students, "sessions": sessions, "responses": responses}


# --------------------------------------------------------------------------
# Build the 2D grid that gets written into the sheet
# --------------------------------------------------------------------------
def build_course_table(course_code: str):
    """
    Returns a list-of-lists (rows) ready to write straight into a Sheets tab:
        Date       | Alice | Bob
        03-Aug     | P     | A*
        05-Aug     | P     | -
        Attendance%| 100.0%| 0.0%

    Symbol meaning:
      P  = answered yes (present)
      A  = answered no (absent)
      A* = record exists but never answered a button -- counted as absent
      -  = wasn't enrolled yet when this particular class happened,
           correctly excluded from that student's total.

    This must stay logically identical to attendance_stats() in bot.py, or
    the sheet and the /attendance command would show different percentages
    for the same student.
    """
    data = _fetch_course_data(course_code)
    if data is None:
        raise ValueError(f"Course {course_code} not found")

    students = data["students"]
    sessions = data["sessions"]
    responses = data["responses"]

    if not students:
        raise ValueError(f"{course_code}-এ এখনো কোনো student নেই")

    header = ["Date"] + [name or f"User{uid}" for uid, name in students]
    rows = [header]

    SYMBOL = {"yes": "P", "no": "A", None: "A*"}
    per_student_attended = {uid: 0 for uid, _ in students}
    per_student_total = {uid: 0 for uid, _ in students}

    for session_id, created_at in sessions:
        date_str = datetime.fromisoformat(created_at).strftime("%d-%b-%Y")
        row = [date_str]
        for uid, _ in students:
            key = (session_id, uid)
            if key in responses:
                resp = responses[key]
                row.append(SYMBOL[resp])
                per_student_total[uid] += 1
                if resp == "yes":
                    per_student_attended[uid] += 1
            else:
                row.append("-")  # not enrolled yet at the time of this class
        rows.append(row)

    pct_row = ["Attendance %"]
    for uid, _ in students:
        total = per_student_total[uid]
        pct = round((per_student_attended[uid] / total) * 100, 1) if total else 0
        pct_row.append(f"{pct}%")
    rows.append(pct_row)

    return rows


# --------------------------------------------------------------------------
# Google Sheets API helpers
# --------------------------------------------------------------------------
def _get_service():
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=SCOPES
    )
    return build("sheets", "v4", credentials=creds)


def _get_sheet_id_by_title(service, title: str):
    spreadsheet = service.spreadsheets().get(spreadsheetId=SPREADSHEET_ID).execute()
    for sheet in spreadsheet.get("sheets", []):
        props = sheet["properties"]
        if props["title"] == title:
            return props["sheetId"]
    return None


def _ensure_tab_exists(service, title: str):
    sheet_id = _get_sheet_id_by_title(service, title)
    if sheet_id is not None:
        return sheet_id

    result = service.spreadsheets().batchUpdate(
        spreadsheetId=SPREADSHEET_ID,
        body={"requests": [{"addSheet": {"properties": {"title": title}}}]},
    ).execute()
    return result["replies"][0]["addSheet"]["properties"]["sheetId"]


def _clear_tab(service, title: str):
    service.spreadsheets().values().clear(
        spreadsheetId=SPREADSHEET_ID, range=f"'{title}'"
    ).execute()


def _write_table(service, title: str, rows):
    service.spreadsheets().values().update(
        spreadsheetId=SPREADSHEET_ID,
        range=f"'{title}'!A1",
        valueInputOption="USER_ENTERED",
        body={"values": rows},
    ).execute()


def _bold_header_and_summary_row(service, sheet_id: int, last_row_index: int):
    requests = [
        {
            "repeatCell": {
                "range": {"sheetId": sheet_id, "startRowIndex": 0, "endRowIndex": 1},
                "cell": {
                    "userEnteredFormat": {
                        "textFormat": {"bold": True, "foregroundColor": {"red": 1, "green": 1, "blue": 1}},
                        "backgroundColor": {"red": 0.29, "green": 0.44, "blue": 0.65},
                    }
                },
                "fields": "userEnteredFormat.textFormat,userEnteredFormat.backgroundColor",
            }
        },
        {
            "repeatCell": {
                "range": {
                    "sheetId": sheet_id,
                    "startRowIndex": last_row_index,
                    "endRowIndex": last_row_index + 1,
                },
                "cell": {"userEnteredFormat": {"textFormat": {"bold": True}}},
                "fields": "userEnteredFormat.textFormat",
            }
        },
    ]
    try:
        service.spreadsheets().batchUpdate(
            spreadsheetId=SPREADSHEET_ID, body={"requests": requests}
        ).execute()
    except Exception:
        pass  # formatting is a nice-to-have, don't fail the whole sync over it


# --------------------------------------------------------------------------
# Public entry point
# --------------------------------------------------------------------------
def sync_course_to_sheets(course_code: str):
    if not SHEETS_ENABLED:
        raise RuntimeError(
            "Sheets sync is not configured (missing GOOGLE_SHEETS_SPREADSHEET_ID "
            "or credentials.json). See README.md."
        )

    course_code = course_code.upper()
    rows = build_course_table(course_code)

    service = _get_service()
    sheet_id = _ensure_tab_exists(service, course_code)
    _clear_tab(service, course_code)
    _write_table(service, course_code, rows)
    _bold_header_and_summary_row(service, sheet_id, last_row_index=len(rows) - 1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python sheets_sync.py CSE2201DMS")
        sys.exit(1)
    sync_course_to_sheets(sys.argv[1])
    print(f"Synced {sys.argv[1].upper()} to Google Sheets.")
