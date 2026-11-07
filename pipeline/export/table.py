"""The sheet's tables as plain rows, shared by the Excel and Google Sheets writers. Pure."""

from datetime import datetime

from pipeline import config
from pipeline.models import Company, Fact
from pipeline.scoring import LeadScore, UnitModel, known
from pipeline.utils.urls import domain_of, is_platform_domain

LEAD_COLUMNS = [
    "Rank", "Company", "Website", "Lead score", "Confidence", "Data completeness",
    "Contact status", "Contact", "Contact role", "Contact email", "Contact LinkedIn",
    "Units managed", "Units status", "Residential share", "Buyer type", "Software",
    "Association", "Growth signal", "Employees", "Properties", "Remote reading mentioned",
    "Metering provider", "Phone", "General email", "Street", "Postcode", "Evidence",
    "Research status", "Research notes", "Found via",
]  # fmt: skip

_ORDER = {"OK": 0, "Low": 1, "Not researched": 2, "Excluded": 3}

KPI_DEFINITIONS = [
    ["KPI", "Tier / weight", "Scale", "Why it matters to Heidi"],
    ["Units managed", "Critical / 3", "1–5 by quintile of published values",
     "Heidi bills per unit per year: units = revenue potential"],
    ["Residential share", "Important / 2", "mainly residential 5, mixed 3, mainly commercial 1",
     "Proxy for buildings with HeizkostenV billing duties"],
    ["Buyer type", "Important / 2",
     "rental-focused 5, WEG-focused/unclear 4, cooperative 3, own portfolio 3, municipal 2",
     "Who signs the metering contract and how fast (WEG needs an owners' resolution)"],
    ["Software", "Useful / 1", "Heidi integration (Domus, Immoware24, Wodis, Immocloud) 5, other 2",
     "Easier onboarding through existing integrations"],
    ["Association (bonus)", "+3", "VDIV / BVI / IVD membership", "Professionalism and a channel"],
    ["Growth signal (bonus)", "+3", "Job ads or stated expansion", "Growing portfolio"],
    ["Lead score", "0–100", "weighted average of known KPIs × 18.8 + bonuses",
     "Unknown KPIs are left out, never counted as 0"],
    ["Confidence", "OK / Low", "Low if < 50% of KPI weight known or units unknown",
     "A high score built on little data is flagged"],
    ["Evidence", "", "source page + verbatim quote per value, re-checked by code",
     "Every value is traceable; unconfirmed values count as unknown"],
]  # fmt: skip


def lead_rows(companies: list[Company], scores: list[LeadScore]) -> list[list[object]]:
    paired = sorted(zip(companies, scores, strict=True), key=_sort_key)
    return [_lead_row(rank, c, s) for rank, (c, s) in enumerate(paired, start=1)]


def _sort_key(pair: tuple[Company, LeadScore]) -> tuple[int, float, str]:
    company, score = pair
    return (_ORDER.get(score.confidence, 9), -(score.lead_score or 0), company.name.lower())


def _lead_row(rank: int, c: Company, s: LeadScore) -> list[object]:
    contact = next((p for p in c.contacts if p.verified), None)
    return [
        rank, c.name, c.website, s.lead_score, s.confidence,
        round(s.completeness * 100) if s.lead_score is not None else None,
        s.contact_status,
        contact.name if contact else None, contact.role if contact else None,
        contact.email if contact else None, contact.linkedin if contact else None,
        s.units, s.units_status if s.units is not None else None,
        _value(c.residential_share), _value(c.buyer_type), _value(c.software),
        _value(c.association), _value(c.growth), _value(c.employees), _value(c.properties),
        _value(c.remote_reading), _value(c.metering_provider),
        c.phone, _value(c.general_email) or c.email_general, c.street, c.postcode, _evidence(c),
        _status(c), c.research_notes,
        ", ".join(sorted({ref.source for ref in c.sources})),
    ]  # fmt: skip


def _status(c: Company) -> str:
    if c.research_status:
        return c.research_status
    domain = domain_of(c.website)
    has_site = domain is not None and not is_platform_domain(domain)
    return "not researched yet" if has_site else "no own website"


def _value(fact: Fact) -> object:
    return fact.value if known(fact) else None


def _evidence(c: Company) -> str | None:
    lines = [
        f"{name}: „{fact.quote}“ — {fact.source_url}"
        for name in (
            "units_managed",
            "residential_share",
            "buyer_type",
            "software",
            "association",
            "growth",
            "employees",
            "properties",
        )  # fmt: skip
        if known(fact := getattr(c, name))
    ]
    lines += [f"contact {p.name}: „{p.quote}“ — {p.source_url}" for p in c.contacts if p.verified]
    return "\n".join(lines) or None


def run_log_rows(
    companies: list[Company], scores: list[LeadScore], model: UnitModel, generated: datetime
) -> list[list[object]]:
    researched = [c for c in companies if c.research_status]
    by_confidence = {k: sum(s.confidence == k for s in scores) for k in _ORDER}
    return [
        ["Item", "Value"],
        ["Generated", generated.strftime("%Y-%m-%d %H:%M")],
        ["Companies found (Google Places + OpenStreetMap, deduplicated)", len(companies)],
        ["Researched by the agent", len(researched)],
        ["Submitted a record", sum(c.research_status == "submitted" for c in researched)],
        ["No usable website", sum(c.research_status == "no_pages" for c in researched)],
        *([f"Leads: {k}", v] for k, v in by_confidence.items()),
        ["Unit bands (quintile cut points, published values)", ", ".join(map(str, model.bands))],
        ["Units per employee (median)", f"{model.per_employee} (n={model.per_employee_sample})"],
        ["Units per property (median)", f"{model.per_property} (n={model.per_property_sample})"],
        ["Research model", config.AGENT_MODEL],
    ]
