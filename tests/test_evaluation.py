from pathlib import Path

from openpyxl import load_workbook

from pipeline.evaluation import EVAL_FIELDS, compare, read_truth, unreachable_ids, write_template
from pipeline.models import Company, Fact, Status


def fact(value: object) -> Fact:
    return Fact(value=value, status=Status.PUBLISHED, source_url="u", quote="q", verified=True)


def test_template_round_trip_and_comparison(tmp_path: Path) -> None:
    path = tmp_path / "truth.xlsx"
    write_template(path, [Company(id="a.de", name="A", website="https://a.de")])
    wb = load_workbook(path)
    ws = wb["Ground truth"]
    header = [c.value for c in ws[1]]
    ws.cell(2, header.index("units_managed") + 1, 2000)
    ws.cell(2, header.index("association") + 1, "IVD")
    ws.cell(2, header.index("buyer_type") + 1, "third_party_weg")
    wb.save(path)

    agent = Company(
        id="a.de",
        name="A",
        units_managed=fact(2100),  # within 10%
        association=fact("IVD Berlin-Brandenburg"),  # contains the expected name
        buyer_type=fact("third_party_rental"),  # wrong
        software=fact("Domus"),  # truth says unknown: wrong
    )
    results = {r.field: r for r in compare(read_truth(path), [agent])}
    assert set(results) == set(EVAL_FIELDS)
    assert results["units_managed"].correct == 1
    assert results["association"].correct == 1
    assert results["residential_share"].correct == 1  # both unknown
    assert results["buyer_type"].correct == 0 and results["software"].correct == 0
    assert "expected 'third_party_weg'" in results["buyer_type"].misses[0]


def test_unreachable_site_is_not_counted(tmp_path: Path) -> None:
    path = tmp_path / "truth.xlsx"
    write_template(path, [Company(id="a.de", name="A"), Company(id="b.de", name="B")])
    wb = load_workbook(path)
    wb["Ground truth"].cell(2, 4, 1600)  # a.de units: the agent could not see the site
    wb.save(path)
    blocked = Company(id="a.de", name="A", research_status="no_pages")
    researched = Company(id="b.de", name="B", research_status="submitted")
    truth = read_truth(path)
    results = compare(truth, [blocked, researched])
    assert unreachable_ids(truth, [blocked, researched]) == ["a.de"]
    assert all(r.total == 1 and r.correct == 1 for r in results)


def test_unverified_agent_value_counts_as_unknown(tmp_path: Path) -> None:
    path = tmp_path / "truth.xlsx"
    write_template(path, [Company(id="a.de", name="A")])
    unverified = Fact(value="Domus", status=Status.UNKNOWN, verified=False)
    results = {
        r.field: r
        for r in compare(read_truth(path), [Company(id="a.de", name="A", software=unverified)])
    }
    assert results["software"].correct == 1
