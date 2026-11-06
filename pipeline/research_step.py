"""Run the research agent over the company list within the Anthropic budget, one checkpoint each.

Companies are researched in id order and finished ones are skipped, so a run that stopped at the
budget, the batch limit or a crash continues where it left off. Before every agent call the
ledger total (all Anthropic spend, all runs) plus a worst-case reserve for one more company must
still fit the budget: the run stops before a call that could overspend, not after it.
"""

import logging
from datetime import UTC, datetime
from typing import Literal, Protocol

from pydantic import BaseModel, Field

from pipeline.agent.contracts import SpendRecorder
from pipeline.agent.schema import ResearchRecord
from pipeline.models import Company
from pipeline.utils.urls import domain_of, is_platform_domain

log = logging.getLogger(__name__)

StopReason = Literal["complete", "batch_limit", "budget"]


class Researcher(Protocol):
    model: str

    def research(self, company: Company) -> ResearchRecord: ...


class Checkpoints(Protocol):
    def is_done(self, company_id: str) -> bool: ...

    def save(self, record: ResearchRecord) -> None: ...

    def load_all(self) -> list[ResearchRecord]: ...


class RunSummary(BaseModel):
    """What one run did. Each selected company is counted once:
    selected = already_done + processed + remaining."""

    selected: int
    skipped_without_website: int
    missing_ids: list[str]
    already_done: int = 0  # had a checkpoint when reached (or, after a stop, when counted)
    processed: int = 0  # agent runs in this run, error records included
    remaining: int = 0  # still without a checkpoint when the run stopped
    by_stop: dict[str, int] = Field(default_factory=dict)
    cost_usd: float = 0.0  # sum over this run's records
    stopped: StopReason = "complete"


def select_companies(
    companies: list[Company], only_ids: set[str] | None
) -> tuple[list[Company], int, list[str]]:
    """Companies the agent can research, sorted by id.

    Only a company's own website can be researched (RULEBOOK: no agent run without one). With
    only_ids the list is narrowed first, so skipped_without_website counts requested companies
    only, and a requested company without its own website is skipped, not missing.
    Returns (selected, skipped_without_website, requested ids not in the list).
    """
    in_scope = companies if only_ids is None else [c for c in companies if c.id in only_ids]
    missing = [] if only_ids is None else sorted(only_ids - {c.id for c in companies})
    selected = sorted((c for c in in_scope if _has_own_website(c)), key=lambda c: c.id)
    return selected, len(in_scope) - len(selected), missing


def _has_own_website(company: Company) -> bool:
    domain = domain_of(company.website)
    return domain is not None and not is_platform_domain(domain)


def run_research(
    companies: list[Company],
    agent: Researcher,
    checkpoints: Checkpoints,
    ledger: SpendRecorder,
    *,
    budget_usd: float,
    reserve_per_company_usd: float,
    limit: int | None,
    only_ids: set[str] | None = None,
) -> RunSummary:
    """Research the selected companies in id order until each has a checkpoint, the budget has
    no room for one more company, or `limit` companies were processed in this run (None: no
    batch limit)."""
    selected, without_website, missing = select_companies(companies, only_ids)
    summary = RunSummary(
        selected=len(selected), skipped_without_website=without_website, missing_ids=missing
    )
    _log_start(summary, agent.model, ledger.total_usd(), budget_usd)
    for index, company in enumerate(selected):
        if checkpoints.is_done(company.id):
            summary.already_done += 1
            continue
        spent_usd = ledger.total_usd()
        reason = _stop_reason(
            spent_usd, reserve_per_company_usd, budget_usd, summary.processed, limit
        )
        if reason is not None:
            _mark_stopped(summary, reason, selected[index:], checkpoints)
            _log_stop(summary, spent_usd, reserve_per_company_usd, budget_usd, limit)
            break
        record = _research_one(agent, company)
        checkpoints.save(record)
        _add_record(summary, record)
    _log_finish(summary, ledger.total_usd(), budget_usd)
    return summary


def _stop_reason(
    spent_usd: float, reserve_usd: float, budget_usd: float, processed: int, limit: int | None
) -> StopReason | None:
    """Budget first: the next company only starts if its worst-case cost still fits."""
    if spent_usd + reserve_usd > budget_usd:
        return "budget"
    if limit is not None and processed >= limit:
        return "batch_limit"
    return None


def _research_one(agent: Researcher, company: Company) -> ResearchRecord:
    """The agent's record, or an error record: one failing company never stops the run."""
    try:
        return agent.research(company)
    except Exception as exc:
        log.exception("Research failed for %s (%s)", company.id, company.name)
        return _error_record(company.id, agent.model, exc)


def _error_record(company_id: str, model: str, exc: Exception) -> ResearchRecord:
    return ResearchRecord(
        company_id=company_id,
        model=model,
        effort="",
        submission=None,
        stop="error",
        errors=[repr(exc)],
        finished_at=datetime.now(UTC),
    )


def _add_record(summary: RunSummary, record: ResearchRecord) -> None:
    summary.processed += 1
    summary.by_stop[record.stop] = summary.by_stop.get(record.stop, 0) + 1
    summary.cost_usd += record.cost_usd
    log.info(
        "Researched %s: %s, $%.4f (%d this run, $%.4f)",
        record.company_id,
        record.stop,
        record.cost_usd,
        summary.processed,
        summary.cost_usd,
    )


def _mark_stopped(
    summary: RunSummary, reason: StopReason, rest: list[Company], checkpoints: Checkpoints
) -> None:
    """rest starts at the company that was not started; finished ones after it count as done."""
    summary.stopped = reason
    summary.remaining = sum(1 for company in rest if not checkpoints.is_done(company.id))
    summary.already_done += len(rest) - summary.remaining


def _log_start(summary: RunSummary, model: str, spent_usd: float, budget_usd: float) -> None:
    log.info(
        "Research with %s: %d companies selected, %d without their own website skipped; "
        "$%.4f of the $%.2f budget spent so far",
        model,
        summary.selected,
        summary.skipped_without_website,
        spent_usd,
        budget_usd,
    )
    if summary.missing_ids:
        log.warning("Requested ids not in the company list: %s", ", ".join(summary.missing_ids))


def _log_stop(
    summary: RunSummary, spent_usd: float, reserve_usd: float, budget_usd: float, limit: int | None
) -> None:
    if summary.stopped == "budget":
        log.warning(
            "Budget stop: $%.4f spent + $%.4f reserve for the next company exceeds the $%.2f "
            "budget; %d companies remain",
            spent_usd,
            reserve_usd,
            budget_usd,
            summary.remaining,
        )
    else:
        log.info(
            "Batch limit of %s companies reached; %d companies remain, run again to continue",
            limit,
            summary.remaining,
        )


def _log_finish(summary: RunSummary, spent_usd: float, budget_usd: float) -> None:
    log.info(
        "Research run ended (%s): %d processed %s for $%.4f, %d already done, %d remain; "
        "$%.4f of the $%.2f budget spent in total",
        summary.stopped,
        summary.processed,
        summary.by_stop,
        summary.cost_usd,
        summary.already_done,
        summary.remaining,
        spent_usd,
        budget_usd,
    )
