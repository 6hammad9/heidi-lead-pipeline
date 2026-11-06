from datetime import datetime
from pathlib import Path

from openpyxl import load_workbook

from pipeline.export.excel import write_workbook
from pipeline.export.table import KPI_DEFINITIONS, LEAD_COLUMNS, lead_rows, run_log_rows
from pipeline.models import Company, Contact, Fact, Status
from pipeline.scoring import score_all


def fact(value: object) -> Fact:
    return Fact(
        value=value, status=Status.PUBLISHED, source_url="https://a.de", quote="q", verified=True
    )


def researched(cid: str, units: int, **extra: object) -> Company:
    return Company(
        id=cid,
        name=cid,
        website=f"https://{cid}",
        research_status="submitted",
        units_managed=fact(units),
        buyer_type=fact("third_party_rental"),
        residential_share=fact("mainly_residential"),
        **extra,
    )


COMPANIES = [
    Company(id="fresh.de", name="Fresh", website="https://fresh.de"),
    researched("small.de", 100),
    researched(
        "big.de",
        5000,
        contacts=[
            Contact(name="Anna", verified=True, quote="Anna, GF", source_url="https://big.de")
        ],
    ),
    researched("broker.de", 50).model_copy(update={"buyer_type": fact("not_property_manager")}),
]


def column(rows: list[list[object]], name: str) -> list[object]:
    return [row[LEAD_COLUMNS.index(name)] for row in rows]


def test_rows_are_ranked_scored_first_then_unresearched_then_excluded() -> None:
    scores, _ = score_all(COMPANIES)
    rows = lead_rows(COMPANIES, scores)
    assert all(len(row) == len(LEAD_COLUMNS) for row in rows)
    assert column(rows, "Company") == ["big.de", "small.de", "Fresh", "broker.de"]
    assert column(rows, "Rank") == [1, 2, 3, 4]
    assert column(rows, "Contact")[0] == "Anna"


def test_evidence_lists_quote_and_source_per_known_value() -> None:
    scores, _ = score_all(COMPANIES)
    evidence = column(lead_rows(COMPANIES, scores), "Evidence")[0]
    assert "units_managed: „q“ — https://a.de" in evidence
    assert "contact Anna: „Anna, GF“ — https://big.de" in evidence


def test_workbook_has_three_tabs_and_readable_rows(tmp_path: Path) -> None:
    scores, model = score_all(COMPANIES)
    path = tmp_path / "leads.xlsx"
    run_log = run_log_rows(COMPANIES, scores, model, datetime(2026, 11, 7))
    write_workbook(path, lead_rows(COMPANIES, scores), KPI_DEFINITIONS, run_log)
    wb = load_workbook(path)
    assert wb.sheetnames == ["Leads", "KPI definitions", "Run log"]
    leads = wb["Leads"]
    assert [c.value for c in leads[1]] == LEAD_COLUMNS
    assert leads.max_row == len(COMPANIES) + 1
    assert leads["C2"].hyperlink.target == "https://big.de"
