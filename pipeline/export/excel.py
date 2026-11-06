"""Writes the lead sheet as an Excel workbook (the fallback the case study allows)."""

from pathlib import Path

from openpyxl import Workbook
from openpyxl.formatting.rule import ColorScaleRule
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from pipeline.export.table import LEAD_COLUMNS

HEADER_FILL = PatternFill("solid", fgColor="1F3A5F")
HEADER_FONT = Font(bold=True, color="FFFFFF")
WIDE = {"Company": 34, "Website": 30, "Evidence": 70, "Research notes": 50, "Contact": 24}


def write_workbook(
    path: Path, leads: list[list[object]], kpis: list[list[object]], run_log: list[list[object]]
) -> None:
    wb = Workbook()
    _leads_sheet(wb.active, leads)
    _simple_sheet(wb.create_sheet("KPI definitions"), kpis, width=45)
    _simple_sheet(wb.create_sheet("Run log"), run_log, width=55)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def _leads_sheet(ws: Worksheet, rows: list[list[object]]) -> None:
    ws.title = "Leads"
    ws.append(LEAD_COLUMNS)
    for row in rows:
        ws.append(row)
    _style_header(ws)
    ws.freeze_panes = "C2"
    ws.auto_filter.ref = ws.dimensions
    for index, name in enumerate(LEAD_COLUMNS, start=1):
        ws.column_dimensions[get_column_letter(index)].width = WIDE.get(name, 16)
    score_col = get_column_letter(LEAD_COLUMNS.index("Lead score") + 1)
    ws.conditional_formatting.add(
        f"{score_col}2:{score_col}{len(rows) + 1}",
        ColorScaleRule(
            start_type="num",
            start_value=0,
            start_color="F8696B",
            mid_type="num",
            mid_value=50,
            mid_color="FFEB84",
            end_type="num",
            end_value=100,
            end_color="63BE7B",
        ),
    )
    _link_websites(ws, LEAD_COLUMNS.index("Website") + 1)
    for cell in ws[get_column_letter(LEAD_COLUMNS.index("Evidence") + 1)][1:]:
        cell.alignment = Alignment(wrap_text=True, vertical="top")


def _link_websites(ws: Worksheet, column: int) -> None:
    for (cell,) in ws.iter_rows(min_row=2, min_col=column, max_col=column):
        if isinstance(cell.value, str) and cell.value.startswith("http"):
            cell.hyperlink = cell.value
            cell.font = Font(color="0563C1", underline="single")


def _simple_sheet(ws: Worksheet, rows: list[list[object]], width: int) -> None:
    for row in rows:
        ws.append(row)
    _style_header(ws)
    for index in range(1, (max(len(r) for r in rows) if rows else 0) + 1):
        ws.column_dimensions[get_column_letter(index)].width = width
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.alignment = Alignment(wrap_text=True, vertical="top")


def _style_header(ws: Worksheet) -> None:
    for cell in ws[1]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(wrap_text=True, vertical="center")
