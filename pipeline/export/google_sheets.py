"""Writes the same tables straight into a Google Sheet, the format Heidi prefers.

Auth is a service account: key file path in GOOGLE_SERVICE_ACCOUNT_FILE, sheet id in
GOOGLE_SHEET_ID, and the sheet shared with the service account's email as editor. Each run
replaces the tab contents, so the shared link always shows the latest data.
"""

import os

import gspread

SHEET_ID_ENV = "GOOGLE_SHEET_ID"
KEY_FILE_ENV = "GOOGLE_SERVICE_ACCOUNT_FILE"


def sheets_configured() -> bool:
    return bool(os.environ.get(SHEET_ID_ENV) and os.environ.get(KEY_FILE_ENV))


def write_google_sheet(
    tabs: dict[str, list[list[object]]], client: gspread.Client | None = None
) -> str:
    """tabs: title -> rows including the header row. Returns the sheet's URL."""
    gc = client or gspread.service_account(filename=os.environ[KEY_FILE_ENV])
    spreadsheet = gc.open_by_key(os.environ[SHEET_ID_ENV])
    for title, rows in tabs.items():
        width = max(len(row) for row in rows)
        worksheet = _worksheet(spreadsheet, title, len(rows), width)
        worksheet.clear()
        worksheet.update(
            range_name="A1",
            values=[[_cell(value) for value in row] for row in rows],
            value_input_option="RAW",
        )
        worksheet.freeze(rows=1)
        worksheet.format("1:1", {"textFormat": {"bold": True}})
    return spreadsheet.url


def _worksheet(spreadsheet: gspread.Spreadsheet, title: str, rows: int, cols: int):
    try:
        worksheet = spreadsheet.worksheet(title)
    except gspread.WorksheetNotFound:
        return spreadsheet.add_worksheet(title=title, rows=rows, cols=cols)
    worksheet.resize(rows=rows, cols=cols)
    return worksheet


def _cell(value: object) -> object:
    if value is None:
        return ""
    return value if isinstance(value, int | float) else str(value)
