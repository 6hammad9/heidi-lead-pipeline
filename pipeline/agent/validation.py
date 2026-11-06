"""The evidence rules applied to a submission before it is accepted. Pure.

A claim with a value needs a source_url from the pages the agent was given and a quote. The
agent gets the problems back once to correct them; after that, sanitize_submission nulls the
offending claims and drops the offending contacts, so one bad field never loses the company.
"""

import re

from pipeline import config
from pipeline.agent.schema import CLAIM_FIELDS, Claim, ContactClaim, ResearchSubmission
from pipeline.utils.urls import normalize_url

_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")


def validate_submission(submission: ResearchSubmission, seen_urls: set[str]) -> list[str]:
    return sanitize_submission(submission, seen_urls)[1]


def sanitize_submission(
    submission: ResearchSubmission, seen_urls: set[str]
) -> tuple[ResearchSubmission, list[str]]:
    seen = {u for u in map(normalize_url, seen_urls) if u}
    problems: list[str] = []
    updates: dict[str, object] = {}
    for name in CLAIM_FIELDS:
        claim = getattr(submission, name)
        if problem := _claim_problem(claim, seen):
            problems.append(f"{name}: {problem}")
            updates[name] = claim.model_copy(update=_EMPTY)
        elif claim.value is None and (claim.source_url or claim.quote):
            updates[name] = claim.model_copy(update=_EMPTY)  # tidy only, not a problem
    contacts: list[ContactClaim] = []
    for index, contact in enumerate(submission.contacts):
        if problem := _contact_problem(contact, seen):
            problems.append(f"contacts[{index}] ({contact.name}): {problem}")
        else:
            contacts.append(contact)
    updates["contacts"] = contacts
    return submission.model_copy(update=updates), problems


_EMPTY = {"value": None, "source_url": None, "quote": None}


def _claim_problem(claim: Claim, seen: set[str]) -> str | None:
    if claim.value is None:
        return None
    if isinstance(claim.value, str) and not claim.value.strip():
        return "empty value; use null when the pages do not state it"
    if isinstance(claim.value, int) and claim.value <= 0:
        return "must be a positive number or null"
    return _evidence_problem(claim.source_url, claim.quote, seen)


def _contact_problem(contact: ContactClaim, seen: set[str]) -> str | None:
    if not contact.name.strip():
        return "empty name"
    if contact.email and not _EMAIL.fullmatch(contact.email.strip()):
        return "email is not an email address; use null unless the page shows the address"
    return _evidence_problem(contact.source_url, contact.quote, seen)


def _evidence_problem(source_url: str | None, quote: str | None, seen: set[str]) -> str | None:
    if not source_url or not quote or not quote.strip():
        return "a value needs source_url and quote; use null when the pages do not state it"
    if normalize_url(source_url) not in seen:
        return f"source_url {source_url!r} is not one of the pages you were given"
    if len(quote) > config.QUOTE_MAX_CHARS:
        return f"quote is longer than {config.QUOTE_MAX_CHARS} characters"
    return None
