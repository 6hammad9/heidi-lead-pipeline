"""Re-checks every agent claim against the stored text of the page it cites. Pure.

This is where "evidence or unknown" is enforced by code: a claim whose quote is not on the
cited page, or whose number is not in its quote, becomes unknown (value kept for audit).
"""

import re
import unicodedata

from pydantic import BaseModel, Field
from rapidfuzz import fuzz

from pipeline import config
from pipeline.agent.schema import CLAIM_FIELDS, IntClaim, ResearchSubmission
from pipeline.models import Company, Contact, Fact, Page, Status
from pipeline.utils.urls import normalize_url

INT_FIELDS = {n for n, f in ResearchSubmission.model_fields.items() if f.annotation is IntClaim}
MIN_FUZZY_CHARS = 20  # shorter quotes must match exactly: fuzzy short matches mean nothing
_TYPOGRAPHY = str.maketrans(
    {"„": '"', "“": '"', "”": '"', "«": '"', "»": '"', "‚": "'", "‘": "'", "’": "'"}
    | {"–": "-", "—": "-", "­": None}
)
_NUMBER = re.compile(r"\d{1,3}(?:[.,   ]\d{3})+(?![\d,.]\d)|\d+")


class VerificationStats(BaseModel):
    claims_checked: int = 0
    claims_verified: int = 0
    contacts_checked: int = 0
    contacts_verified: int = 0
    emails_published: int = 0
    failures: list[str] = Field(default_factory=list)

    def add(self, other: "VerificationStats") -> None:
        for name in type(self).model_fields:
            setattr(self, name, getattr(self, name) + getattr(other, name))


def normalize_for_match(text: str) -> str:
    folded = unicodedata.normalize("NFKC", text).translate(_TYPOGRAPHY).casefold()
    return " ".join(folded.split())


def quote_on_page(quote: str, page_text: str) -> bool:
    q, t = normalize_for_match(quote), normalize_for_match(page_text)
    if not q:
        return False
    if q in t:
        return True
    return len(q) >= MIN_FUZZY_CHARS and fuzz.partial_ratio(q, t) >= config.QUOTE_MATCH_MIN_SCORE


def numbers_in(text: str) -> set[int]:
    """'2.400', '2,400', '2 400' and '2400' all give 2400; '1,5 Mio' gives 1 and 5, not 15."""
    return {int(re.sub(r"\D", "", m)) for m in _NUMBER.findall(text)}


def verify_company(company: Company, pages: list[Page]) -> tuple[Company, VerificationStats]:
    index = _index(pages)
    stats = VerificationStats()
    updates: dict[str, object] = {}
    for name in CLAIM_FIELDS:
        fact: Fact = getattr(company, name)
        if fact.status is Status.PUBLISHED:
            updates[name] = _verify_fact(name, fact, index, stats)
    updates["contacts"] = [
        checked for c in company.contacts if (checked := _verify_contact(c, index, stats))
    ]
    return company.model_copy(update=updates, deep=True), stats


def _index(pages: list[Page]) -> dict[str, Page]:
    index: dict[str, Page] = {}
    for page in pages:
        for url in (page.requested_url, page.url):
            if key := normalize_url(url):
                index[key] = page
    return index


def _verify_fact(name: str, fact: Fact, index: dict[str, Page], stats: VerificationStats) -> Fact:
    stats.claims_checked += 1
    if problem := _fact_problem(name, fact, index):
        stats.failures.append(f"{name}: {problem}")
        return fact.model_copy(update={"verified": False, "status": Status.UNKNOWN})
    stats.claims_verified += 1
    return fact.model_copy(update={"verified": True})


def _fact_problem(name: str, fact: Fact, index: dict[str, Page]) -> str | None:
    page = index.get(normalize_url(fact.source_url) or "")
    if page is None:
        return "cited page was never fetched"
    if not quote_on_page(fact.quote or "", page.text):
        return "quote not found on the cited page"
    if name in INT_FIELDS and fact.value not in numbers_in(fact.quote or ""):
        return f"number {fact.value} not in the quote"
    if name == "general_email" and str(fact.value).casefold() not in page.text.casefold():
        return "email address not on the cited page"
    return None


def _verify_contact(
    contact: Contact, index: dict[str, Page], stats: VerificationStats
) -> Contact | None:
    stats.contacts_checked += 1
    page = index.get(normalize_url(contact.source_url) or "")
    quote = contact.quote or ""
    if page is None or not quote_on_page(quote, page.text) or not _name_in(contact.name, quote):
        stats.failures.append(f"contact {contact.name}: not confirmed on the cited page")
        return None
    stats.contacts_verified += 1
    published = bool(contact.email) and contact.email.casefold() in page.text.casefold()
    stats.emails_published += published
    return contact.model_copy(
        update={
            "verified": True,
            "email": contact.email if published else None,
            "email_published": published,
        }
    )


def _name_in(name: str, quote: str) -> bool:
    words = [w for w in re.findall(r"\w+", normalize_for_match(name)) if len(w) > 1]
    text = normalize_for_match(quote)
    return bool(words) and all(w in text for w in words)
