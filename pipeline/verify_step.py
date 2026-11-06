"""Applies each company's research record and re-verifies every claim against stored pages."""

from pipeline.agent.schema import ResearchRecord
from pipeline.apply_research import apply_submission
from pipeline.fetching.page_store import PageStore
from pipeline.models import Company
from pipeline.verify import VerificationStats, verify_company


def build_verified(
    companies: list[Company], records: list[ResearchRecord], pages: PageStore
) -> tuple[list[Company], VerificationStats]:
    by_id = {record.company_id: record for record in records}
    total = VerificationStats()
    result: list[Company] = []
    for company in companies:
        record = by_id.get(company.id)
        if record is None:
            result.append(company)
            continue
        status = {"research_status": record.stop}
        if record.submission is None:
            result.append(company.model_copy(update=status))
            continue
        applied = apply_submission(company, record.submission)
        checked, stats = verify_company(applied, pages.all(company.id))
        total.add(stats)
        notes = {"research_notes": record.submission.notes}
        result.append(checked.model_copy(update=status | notes))
    return result, total
