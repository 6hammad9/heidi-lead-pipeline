from datetime import UTC, datetime

import pytest

from pipeline import config
from pipeline.agent.schema import CLAIM_FIELDS, ResearchRecord, ResearchSubmission
from pipeline.models import Company
from pipeline.quality_gate import GateResult, evaluate
from pipeline.research_step import run_research
from pipeline.verify import VerificationStats
from tests.test_research_step import FakeCheckpoints, FakeLedger

EMPTY = {"value": None, "source_url": None, "quote": None}


VALUES = {
    "units_managed": 5,
    "employees": 5,
    "properties": 5,
    "residential_share": "mixed",
    "buyer_type": "municipal",
}


def submission(found: int) -> ResearchSubmission:
    """The first `found` claim fields carry a value."""
    payload: dict = {name: dict(EMPTY) for name in CLAIM_FIELDS}
    for name in CLAIM_FIELDS[:found]:
        payload[name] = {"value": VALUES.get(name, "x"), "source_url": "u", "quote": "q"}
    return ResearchSubmission.model_validate(payload | {"contacts": [], "notes": None})


def record(stop: str = "submitted", cost: float = 0.002, found: int = 3) -> ResearchRecord:
    return ResearchRecord(
        company_id="c",
        model="m",
        effort="medium",
        submission=submission(found) if stop.startswith("submitted") else None,
        stop=stop,
        cost_usd=cost,
        finished_at=datetime.now(UTC),
    )


GOOD_STATS = VerificationStats(claims_checked=10, claims_verified=10)


def test_healthy_run_passes() -> None:
    result = evaluate([record() for _ in range(10)], GOOD_STATS)
    assert result.passed and result.metrics["avg_cost_usd"] == pytest.approx(0.002)


def test_no_pages_companies_do_not_count() -> None:
    assert evaluate([record("no_pages", cost=0)] * 5, VerificationStats()).passed


@pytest.mark.parametrize(
    ("records", "stats", "failing"),
    [
        ([record("max_turns")] * 3 + [record()] * 7, GOOD_STATS, "failure_rate"),
        ([record()] * 10, VerificationStats(claims_checked=10, claims_verified=5), "verified_rate"),
        ([record(found=0)] * 10, GOOD_STATS, "unknown_rate"),
        ([record(cost=0.05)] * 10, GOOD_STATS, "avg_cost_usd"),
    ],
)
def test_each_limit_stops_the_run(records: list, stats: VerificationStats, failing: str) -> None:
    result = evaluate(records, stats)
    assert not result.passed and result.reasons[0].startswith(failing)


class OneRecordAgent:
    model = "m"

    def __init__(self) -> None:
        self.calls = 0

    def research(self, company: Company) -> ResearchRecord:
        self.calls += 1
        return record().model_copy(update={"company_id": company.id})


def test_failing_gate_stops_the_run_after_the_configured_number(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "GATE_AFTER_COMPANIES", 2)
    companies = [
        Company(id=f"c{i}.de", name=f"Hausverwaltung {i}", website=f"https://c{i}.de")
        for i in range(5)
    ]
    agent = OneRecordAgent()
    summary = run_research(
        companies,
        agent,
        FakeCheckpoints(()),
        FakeLedger(0.0),
        budget_usd=4.0,
        reserve_per_company_usd=0.05,
        limit=None,
        gate=lambda records: GateResult(passed=False, reasons=["bad"], metrics={}),
    )
    assert agent.calls == 2
    assert (summary.stopped, summary.remaining) == ("quality_gate", 3)
