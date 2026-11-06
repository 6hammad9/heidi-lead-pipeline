import logging
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime, timedelta

import pytest

from pipeline.agent.contracts import SpendEntry
from pipeline.agent.schema import ResearchRecord
from pipeline.models import Company
from pipeline.research_step import RunSummary, run_research, select_companies

LOGGER = "pipeline.research_step"


def site(cid: str) -> Company:
    return Company(id=cid, name=f"Hausverwaltung {cid}", website=f"https://www.{cid}/")


def sites(*ids: str) -> list[Company]:
    return [site(cid) for cid in ids]


def listed(cid: str, website: str | None) -> Company:
    return Company(id=cid, name=f"Hausverwaltung {cid}", website=website)


def ids(companies: list[Company]) -> list[str]:
    return [c.id for c in companies]


class FakeLedger:
    def __init__(self, spent_usd: float) -> None:
        self.entries: list[SpendEntry] = []
        self._spent_usd = spent_usd

    def record(self, entry: SpendEntry) -> None:
        self.entries.append(entry)
        self._spent_usd += entry.cost_usd

    def total_usd(self) -> float:
        return self._spent_usd


class FakeAgent:
    """Spends cost_usd per company through the ledger, as the real agent does per API call."""

    model = "fake-model"

    def __init__(
        self, ledger: FakeLedger, cost_usd: float, fail: set[str], stops: Mapping[str, str]
    ) -> None:
        self.ledger = ledger
        self.cost_usd = cost_usd
        self.fail = fail
        self.stops = stops
        self.calls: list[str] = []

    def research(self, company: Company) -> ResearchRecord:
        self.calls.append(company.id)
        if company.id in self.fail:
            raise RuntimeError(f"boom {company.id}")
        now = datetime.now(UTC)
        self.ledger.record(
            SpendEntry(
                at=now,
                model=self.model,
                company_id=company.id,
                input_tokens=1000,
                output_tokens=100,
                cache_creation_tokens=0,
                cache_read_tokens=0,
                cost_usd=self.cost_usd,
            )
        )
        return ResearchRecord(
            company_id=company.id,
            model=self.model,
            effort="medium",
            submission=None,
            cost_usd=self.cost_usd,
            stop=self.stops.get(company.id, "submitted"),
            finished_at=now,
        )


class FakeCheckpoints:
    def __init__(self, done: Iterable[str]) -> None:
        self.done = set(done)
        self.saved: list[ResearchRecord] = []

    def is_done(self, company_id: str) -> bool:
        return company_id in self.done

    def save(self, record: ResearchRecord) -> None:
        self.saved.append(record)
        self.done.add(record.company_id)

    def load_all(self) -> list[ResearchRecord]:
        return list(self.saved)


class Harness:
    def __init__(
        self,
        *,
        spent_usd: float = 0.0,
        cost_usd: float = 0.25,
        done: Iterable[str] = (),
        fail: Iterable[str] = (),
        stops: Mapping[str, str] | None = None,
    ) -> None:
        self.ledger = FakeLedger(spent_usd)
        self.agent = FakeAgent(self.ledger, cost_usd, set(fail), stops or {})
        self.checkpoints = FakeCheckpoints(done)

    def run(
        self,
        companies: list[Company],
        *,
        budget_usd: float = 4.0,
        reserve_usd: float = 0.5,
        limit: int | None = None,
        only_ids: set[str] | None = None,
    ) -> RunSummary:
        return run_research(
            companies,
            self.agent,
            self.checkpoints,
            self.ledger,
            budget_usd=budget_usd,
            reserve_per_company_usd=reserve_usd,
            limit=limit,
            only_ids=only_ids,
        )


# Selection


def test_only_companies_with_their_own_website_are_selected() -> None:
    companies = [
        site("b.de"),
        listed("osm:node/1", None),
        listed("google_places:x", "https://www.facebook.com/hv-x"),
        listed("osm:node/2", "https://hv-x.business.site"),
        listed("osm:node/3", "mailto:info@hv-x.de"),
        site("a.de"),
    ]
    selected, skipped, missing = select_companies(companies, None)
    assert (ids(selected), skipped, missing) == (["a.de", "b.de"], 4, [])


def test_selection_is_sorted_by_id_whatever_the_input_order() -> None:
    selected, _, _ = select_companies(sites("c.de", "a.de", "b.de"), None)
    assert ids(selected) == ["a.de", "b.de", "c.de"]


def test_only_ids_keeps_requested_companies_and_reports_missing_ids() -> None:
    only = {"c.de", "a.de", "zz-gone.de", "gone.de"}
    selected, skipped, missing = select_companies(sites("a.de", "b.de", "c.de"), only)
    assert (ids(selected), skipped, missing) == (["a.de", "c.de"], 0, ["gone.de", "zz-gone.de"])


def test_requested_company_without_website_is_skipped_not_missing() -> None:
    companies = [site("a.de"), listed("osm:node/1", None), listed("osm:node/2", None)]
    selected, skipped, missing = select_companies(companies, {"a.de", "osm:node/1"})
    assert (ids(selected), skipped, missing) == (["a.de"], 1, [])


# Run order and checkpoints


def test_agent_runs_in_id_order_and_every_record_is_checkpointed() -> None:
    h = Harness()
    summary = h.run(sites("c.de", "a.de", "b.de"))
    assert h.agent.calls == ["a.de", "b.de", "c.de"]
    assert [r.company_id for r in h.checkpoints.saved] == ["a.de", "b.de", "c.de"]
    assert summary.stopped == "complete"


def test_finished_companies_are_skipped_without_an_agent_call() -> None:
    h = Harness(done={"b.de"})
    summary = h.run(sites("a.de", "b.de", "c.de"))
    assert h.agent.calls == ["a.de", "c.de"]
    assert (summary.already_done, summary.processed) == (1, 2)


# Budget


def test_no_agent_call_when_spent_plus_reserve_would_exceed_the_budget(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = Harness(spent_usd=3.75)
    with caplog.at_level(logging.INFO, logger=LOGGER):
        summary = h.run(sites("a.de", "b.de", "c.de"), budget_usd=4.0, reserve_usd=0.5)
    assert (h.agent.calls, h.checkpoints.saved) == ([], [])
    assert (summary.stopped, summary.processed, summary.remaining) == ("budget", 0, 3)
    [warning] = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert "3 companies remain" in warning.getMessage()


def test_spent_plus_reserve_exactly_at_the_budget_still_runs() -> None:
    h = Harness(spent_usd=3.5, cost_usd=0.25)
    summary = h.run(sites("a.de", "b.de"), budget_usd=4.0, reserve_usd=0.5)
    assert h.agent.calls == ["a.de"]  # 3.5 + 0.5 == 4.0 runs, then 3.75 + 0.5 > 4.0 stops
    assert (summary.stopped, summary.remaining) == ("budget", 1)


def test_spend_never_exceeds_the_budget_when_no_company_costs_more_than_the_reserve() -> None:
    h = Harness(cost_usd=0.5)
    summary = h.run(sites("a.de", "b.de", "c.de", "d.de", "e.de"), budget_usd=1.5, reserve_usd=0.5)
    assert h.agent.calls == ["a.de", "b.de", "c.de"]
    assert h.ledger.total_usd() == 1.5
    assert (summary.stopped, summary.remaining) == ("budget", 2)


def test_budget_stop_is_reported_before_the_batch_limit() -> None:
    h = Harness(cost_usd=0.5)
    summary = h.run(sites("a.de", "b.de"), budget_usd=0.75, reserve_usd=0.5, limit=1)
    assert h.agent.calls == ["a.de"]
    assert summary.stopped == "budget"


# Batch limit


def test_batch_limit_stops_the_run_at_info_level_and_logs_what_remains(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = Harness()
    with caplog.at_level(logging.INFO, logger=LOGGER):
        summary = h.run(sites("a.de", "b.de", "c.de", "d.de", "e.de"), limit=2)
    assert h.agent.calls == ["a.de", "b.de"]
    assert (summary.stopped, summary.processed, summary.remaining) == ("batch_limit", 2, 3)
    assert all(r.levelno == logging.INFO for r in caplog.records)
    assert any("3 companies remain" in r.getMessage() for r in caplog.records)


def test_finished_companies_do_not_count_toward_the_batch_limit() -> None:
    h = Harness(done={"a.de", "b.de"})
    summary = h.run(sites("a.de", "b.de", "c.de", "d.de"), limit=1)
    assert h.agent.calls == ["c.de"]
    assert (summary.stopped, summary.already_done, summary.remaining) == ("batch_limit", 2, 1)


def test_limit_reached_with_nothing_left_to_research_completes_the_run() -> None:
    h = Harness(done={"c.de"})
    summary = h.run(sites("a.de", "b.de", "c.de"), limit=2)
    assert h.agent.calls == ["a.de", "b.de"]
    assert (summary.stopped, summary.already_done, summary.remaining) == ("complete", 1, 0)


# Failures


def test_agent_exception_becomes_an_error_record_and_the_run_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    h = Harness(fail={"b.de"})
    with caplog.at_level(logging.INFO, logger=LOGGER):
        summary = h.run(sites("a.de", "b.de", "c.de"))
    assert h.agent.calls == ["a.de", "b.de", "c.de"]
    error = h.checkpoints.saved[1]
    assert (error.company_id, error.stop, error.model, error.effort, error.submission) == (
        "b.de",
        "error",
        "fake-model",
        "",
        None,
    )
    assert error.errors == ["RuntimeError('boom b.de')"]
    assert error.finished_at.utcoffset() == timedelta(0)
    assert summary.by_stop == {"submitted": 2, "error": 1}
    [logged] = [r for r in caplog.records if r.levelno == logging.ERROR]
    assert "b.de" in logged.getMessage()
    assert logged.exc_info is not None


def test_error_records_count_toward_the_batch_limit() -> None:
    h = Harness(fail={"a.de"})
    summary = h.run(sites("a.de", "b.de"), limit=1)
    assert h.agent.calls == ["a.de"]
    assert (summary.processed, summary.stopped) == (1, "batch_limit")


# Summary


def test_summary_counts_every_selected_company_once() -> None:
    companies = [*sites("a.de", "b.de", "c.de", "d.de", "e.de", "f.de", "g.de")]
    companies.append(listed("osm:node/1", None))
    only = {c.id for c in companies} | {"gone.de"}
    h = Harness(done={"b.de", "f.de"}, fail={"c.de"}, stops={"d.de": "max_turns"})
    summary = h.run(companies, limit=3, only_ids=only)
    assert h.agent.calls == ["a.de", "c.de", "d.de"]
    assert summary == RunSummary(
        selected=7,
        skipped_without_website=1,
        missing_ids=["gone.de"],
        already_done=2,
        processed=3,
        remaining=2,
        by_stop={"submitted": 1, "error": 1, "max_turns": 1},
        cost_usd=0.5,
        stopped="batch_limit",
    )
    assert summary.selected == summary.already_done + summary.processed + summary.remaining


def test_nothing_to_research_completes_with_zero_counts() -> None:
    summary = Harness().run([listed("osm:node/1", None)])
    assert summary == RunSummary(selected=0, skipped_without_website=1, missing_ids=[])
    assert summary.stopped == "complete"
