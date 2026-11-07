"""Accuracy test: the agent's verified answers against values a person checked by hand.

The person fills a blank template (never seeing the agent's answers, to avoid anchoring).
A field counts as correct when both agree, including both saying "unknown".
"""

from pathlib import Path

from openpyxl import Workbook, load_workbook
from pydantic import BaseModel

from pipeline.models import Company
from pipeline.scoring import known

EVAL_FIELDS = ["units_managed", "residential_share", "buyer_type", "software", "association"]
CHOICES = {
    "residential_share": "mainly_residential | mixed | mainly_commercial",
    "buyer_type": (
        "third_party_rental | third_party_weg | third_party_unclear | cooperative | "
        "private_landlord | municipal | not_property_manager"
    ),
}
UNITS_TOLERANCE = 0.1  # "über 2.000" vs 2.100 on another page still agrees


class FieldResult(BaseModel):
    field: str
    correct: int
    total: int
    misses: list[str]


def write_template(path: Path, companies: list[Company]) -> None:
    wb = Workbook()
    ws = wb.active
    ws.title = "Ground truth"
    ws.append(["company_id", "company", "website", *EVAL_FIELDS, "contact_name"])
    for company in companies:
        ws.append([company.id, company.name, company.website])
    notes = wb.create_sheet("How to fill")
    notes.append(["Check each company's own website. Leave a cell empty if the site does not say."])
    notes.append(["units_managed", "number of units managed, e.g. 2400"])
    for field, choices in CHOICES.items():
        notes.append([field, choices])
    notes.append(["software / association", "name as stated, e.g. Domus / IVD"])
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def read_truth(path: Path) -> dict[str, dict[str, object]]:
    rows = list(load_workbook(path, read_only=True)["Ground truth"].iter_rows(values_only=True))
    header = list(rows[0])
    return {str(row[0]): dict(zip(header, row, strict=False)) for row in rows[1:] if row[0]}


def compare(truth: dict[str, dict[str, object]], companies: list[Company]) -> list[FieldResult]:
    by_id = {c.id: c for c in companies}
    results = []
    for field in EVAL_FIELDS:
        misses = []
        checked = [cid for cid in truth if cid in by_id]
        for cid in checked:
            expected, fact = truth[cid].get(field), getattr(by_id[cid], field)
            got = fact.value if known(fact) else None
            if not _agrees(field, expected, got):
                misses.append(f"{cid}: expected {expected!r}, agent {got!r}")
        correct = len(checked) - len(misses)
        results.append(FieldResult(field=field, correct=correct, total=len(checked), misses=misses))
    return results


def _agrees(field: str, expected: object, got: object) -> bool:
    if expected in (None, "") or got is None:
        return expected in (None, "") and got is None
    if field == "units_managed":
        e, g = float(str(expected)), float(str(got))
        return abs(e - g) <= UNITS_TOLERANCE * e
    e, g = str(expected).strip().casefold(), str(got).strip().casefold()
    return e == g or e in g or g in e  # "IVD" vs "IVD Berlin-Brandenburg"
