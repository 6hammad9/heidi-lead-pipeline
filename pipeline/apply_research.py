"""Turns an agent submission into the company's facts and contacts. Pure."""

from enum import Enum

from pipeline.agent.schema import CLAIM_FIELDS, Claim, ContactClaim, ResearchSubmission
from pipeline.models import Company, Contact, Fact, Status


def apply_submission(company: Company, submission: ResearchSubmission) -> Company:
    facts = {name: _fact(getattr(submission, name)) for name in CLAIM_FIELDS}
    contacts = [_contact(c) for c in submission.contacts]
    return company.model_copy(update={**facts, "contacts": contacts}, deep=True)


def _fact(claim: Claim) -> Fact:
    value = claim.value.value if isinstance(claim.value, Enum) else claim.value
    if value is None:
        return Fact()
    return Fact(
        value=value, status=Status.PUBLISHED, source_url=claim.source_url, quote=claim.quote
    )


def _contact(claim: ContactClaim) -> Contact:
    return Contact(
        name=claim.name,
        role=claim.role,
        email=claim.email,
        linkedin=claim.linkedin,
        source_url=claim.source_url,
        quote=claim.quote,
    )
