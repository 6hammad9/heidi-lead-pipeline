from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeline.agent.contracts import SpendEntry
from pipeline.agent.ledger import CorruptLedgerError, SpendLedger


def entry(cost: float, company: str = "a.de") -> SpendEntry:
    return SpendEntry(
        at=datetime(2026, 11, 7, tzinfo=UTC),
        model="claude-haiku-5-5",
        company_id=company,
        input_tokens=100,
        output_tokens=10,
        cache_creation_tokens=0,
        cache_read_tokens=0,
        cost_usd=cost,
    )


def test_missing_file_means_nothing_spent(tmp_path: Path) -> None:
    assert SpendLedger(tmp_path / "spend.jsonl").total_usd() == 0.0


def test_total_covers_all_instances_and_runs(tmp_path: Path) -> None:
    path = tmp_path / "spend.jsonl"
    first = SpendLedger(path)
    first.record(entry(0.01))
    assert first.total_usd() == pytest.approx(0.01)
    second = SpendLedger(path)
    second.record(entry(0.02, "b.de"))
    assert second.total_usd() == pytest.approx(0.03)
    assert first.total_usd() == pytest.approx(0.03)
    assert [e.company_id for e in first.entries()] == ["a.de", "b.de"]


@pytest.mark.parametrize("bad", ["{not json}", '{"cost_usd": "NaN"}'])
def test_unreadable_line_stops_instead_of_counting_zero(tmp_path: Path, bad: str) -> None:
    path = tmp_path / "spend.jsonl"
    SpendLedger(path).record(entry(0.01))
    with path.open("a", encoding="utf-8") as f:
        f.write(bad + "\n")
    with pytest.raises(CorruptLedgerError, match="line 2"):
        SpendLedger(path).total_usd()


def test_cut_off_last_line_does_not_swallow_next_entry(tmp_path: Path) -> None:
    path = tmp_path / "spend.jsonl"
    path.write_text('{"partial', encoding="utf-8")
    SpendLedger(path).record(entry(0.01))
    with pytest.raises(CorruptLedgerError):
        SpendLedger(path).total_usd()  # the cut-off line is reported, not ignored
