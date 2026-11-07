"""Lead score per company, exactly as RULEBOOK.md Step 3 defines it. Pure.

Only verified facts count. Unknown KPIs leave the weighted average instead of scoring 0;
bonus signals sit outside the average so they can only add.
"""

import statistics
from bisect import bisect_right

from pydantic import BaseModel, Field

from pipeline import config
from pipeline.models import Company, Fact, Status

TOTAL_WEIGHT = sum(config.TIER_WEIGHTS[tier] for tier in config.KPI_TIERS.values())


class UnitModel(BaseModel):
    """Unit bands from published values and the ratios used to estimate missing units."""

    bands: list[float] = Field(default_factory=list)
    per_employee: float | None = None
    per_employee_sample: int = 0
    per_property: float | None = None
    per_property_sample: int = 0


class LeadScore(BaseModel):
    company_id: str
    lead_score: float | None
    base: float | None
    bonus: int
    completeness: float
    confidence: str  # OK | Low | Excluded | Not researched
    units: int | None
    units_status: str  # published | estimated | unknown
    sub_scores: dict[str, int] = Field(default_factory=dict)
    contact_status: str


def known(fact: Fact) -> bool:
    return fact.status is Status.PUBLISHED and fact.verified is not False


def build_unit_model(companies: list[Company]) -> UnitModel:
    published = [int(c.units_managed.value) for c in companies if known(c.units_managed)]
    per_employee = _ratios(companies, "employees")
    per_property = _ratios(companies, "properties")
    return UnitModel(
        bands=statistics.quantiles(published, n=5) if len(published) >= 2 else [],
        per_employee=statistics.median(per_employee) if per_employee else None,
        per_employee_sample=len(per_employee),
        per_property=statistics.median(per_property) if per_property else None,
        per_property_sample=len(per_property),
    )


def _ratios(companies: list[Company], field: str) -> list[float]:
    return [
        int(c.units_managed.value) / int(getattr(c, field).value)
        for c in companies
        if known(c.units_managed) and known(getattr(c, field)) and int(getattr(c, field).value)
    ]


def estimate_units(company: Company, model: UnitModel) -> tuple[int | None, str]:
    if known(company.units_managed):
        return int(company.units_managed.value), "published"
    for field, ratio, sample in (
        ("employees", model.per_employee, model.per_employee_sample),
        ("properties", model.per_property, model.per_property_sample),
    ):
        fact = getattr(company, field)
        if ratio and sample >= config.UNIT_ESTIMATION_MIN_SAMPLE and known(fact):
            return round(int(fact.value) * ratio), "estimated"
    return None, "unknown"


def score_company(company: Company, model: UnitModel) -> LeadScore:
    units, units_status = estimate_units(company, model)
    common = {
        "company_id": company.id,
        "units": units,
        "units_status": units_status,
        "contact_status": contact_status(company),
    }
    if company.research_status is None:
        return _unscored("Not researched", common)
    if known(company.buyer_type) and company.buyer_type.value == "not_property_manager":
        return _unscored("Excluded", common)
    subs = _sub_scores(company, units, model)
    weights = {kpi: config.TIER_WEIGHTS[config.KPI_TIERS[kpi]] for kpi in subs}
    known_weight = sum(weights.values())
    base = sum(weights[k] * s for k, s in subs.items()) / known_weight if known_weight else None
    bonus = _bonus(company)
    completeness = known_weight / TOTAL_WEIGHT
    low = completeness < config.LOW_CONFIDENCE_COMPLETENESS or units is None
    return LeadScore(
        lead_score=round(base * config.BASE_SCALE_FACTOR + bonus, 1) if base is not None else None,
        base=base,
        bonus=bonus,
        completeness=completeness,
        confidence="Low" if low else "OK",
        sub_scores=subs,
        **common,
    )


def _unscored(confidence: str, common: dict) -> LeadScore:
    return LeadScore(
        lead_score=None, base=None, bonus=0, completeness=0.0, confidence=confidence, **common
    )


def _sub_scores(company: Company, units: int | None, model: UnitModel) -> dict[str, int]:
    subs: dict[str, int] = {}
    if units is not None and model.bands:
        subs["units_managed"] = bisect_right(model.bands, units) + 1
    if known(company.residential_share):
        subs["residential_share"] = config.RESIDENTIAL_SHARE_SCORES[company.residential_share.value]
    if known(company.buyer_type) and company.buyer_type.value in config.BUYER_TYPE_SCORES:
        subs["buyer_type"] = config.BUYER_TYPE_SCORES[company.buyer_type.value]
    if known(company.software):
        name = str(company.software.value).lower()
        integrated = any(s in name for s in config.INTEGRATED_SOFTWARE)
        subs["software"] = config.SOFTWARE_SCORES["integrated" if integrated else "other"]
    return subs


def _bonus(company: Company) -> int:
    return sum(
        points for field, points in config.BONUS_POINTS.items() if known(getattr(company, field))
    )


def contact_status(company: Company) -> str:
    named = [c for c in company.contacts if c.verified]
    if any(c.email_published for c in named):
        return "Named + email"
    if any(c.linkedin for c in named):
        return "Named + LinkedIn"
    if named:
        return "Named only"
    return "Generic only" if known(company.general_email) or company.email_general else "None"


def score_all(companies: list[Company]) -> tuple[list[LeadScore], UnitModel]:
    model = build_unit_model(companies)
    return [score_company(c, model) for c in companies], model
