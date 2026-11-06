from datetime import UTC, datetime

import pytest

from pipeline.agent.schema import CLAIM_FIELDS, ResearchSubmission
from pipeline.apply_research import apply_submission
from pipeline.models import Company, Page, Status
from pipeline.verify import numbers_in, quote_on_page, verify_company

SITE = "https://hv-mueller.de"
TEXT = (
    "Wir verwalten über 2.400 Einheiten in Berlin.\n"
    "Geschäftsführerin: Dr. Anna Müller, a.mueller@hv-mueller.de\n"
    "Mitglied im VDIV Berlin-Brandenburg"
)
PAGE = Page(url=f"{SITE}/", requested_url=SITE, fetched_at=datetime.now(UTC), text=TEXT)
EMPTY = {"value": None, "source_url": None, "quote": None}


def submission(contacts: list[dict] | None = None, **claims: dict) -> ResearchSubmission:
    payload: dict = {n: dict(EMPTY) for n in CLAIM_FIELDS} | {"contacts": contacts or []}
    return ResearchSubmission.model_validate(payload | {"notes": None} | claims)


def researched(sub: ResearchSubmission) -> Company:
    return apply_submission(Company(id="hv-mueller.de", name="HV Müller", website=SITE), sub)


def anna(**overrides: object) -> dict:
    base = {
        "name": "Anna Müller",
        "role": "Geschäftsführerin",
        "email": "a.mueller@hv-mueller.de",
        "linkedin": None,
        "source_url": SITE,
        "quote": "Geschäftsführerin: Dr. Anna Müller",
    }
    return base | overrides


@pytest.mark.parametrize(
    ("quote", "expected"),
    [
        ("über 2.400 Einheiten", True),
        ("WIR  VERWALTEN über 2.400", True),  # case and whitespace
        ("„Mitglied im VDIV Berlin–Brandenburg“", True),  # typography
        ("Wir verwalten über 2.400 Einheiten in Brlin", True),  # long: fuzzy allowed
        ("VDIV Hamburg", False),  # short: must be exact
        ("", False),
    ],
)
def test_quote_on_page(quote: str, expected: bool) -> None:
    assert quote_on_page(quote, TEXT) is expected


def test_numbers_in_handles_separators_without_inventing_numbers() -> None:
    assert numbers_in("über 2.400 Einheiten, 2,400 WE, 2 400 Wohnungen") == {2400}
    assert numbers_in("1,5 Mio. m²") == {1, 5}


def test_correct_claim_is_verified_and_wrong_number_is_rejected() -> None:
    good = {"value": 2400, "source_url": SITE, "quote": "über 2.400 Einheiten"}
    wrong = {"value": 2500, "source_url": SITE, "quote": "über 2.400 Einheiten"}
    company, stats = verify_company(researched(submission(units_managed=good)), [PAGE])
    assert company.units_managed.verified and company.units_managed.status is Status.PUBLISHED
    company, stats = verify_company(researched(submission(units_managed=wrong)), [PAGE])
    assert company.units_managed.status is Status.UNKNOWN
    assert company.units_managed.value == 2500  # kept for audit, no longer scored
    assert stats.failures == ["units_managed: number 2500 not in the quote"]


def test_quote_from_another_page_or_unfetched_page_fails() -> None:
    claim = {"value": "VDIV", "source_url": f"{SITE}/team", "quote": "Mitglied im VDIV"}
    company, stats = verify_company(researched(submission(association=claim)), [PAGE])
    assert company.association.status is Status.UNKNOWN
    assert "never fetched" in stats.failures[0]


def test_contacts_need_their_name_in_a_quote_on_the_page() -> None:
    sub = submission(contacts=[anna(), anna(name="Bob Schulz")])
    company, stats = verify_company(researched(sub), [PAGE])
    assert [c.name for c in company.contacts] == ["Anna Müller"]
    assert company.contacts[0].email_published and stats.emails_published == 1


def test_email_not_on_the_page_is_removed() -> None:
    sub = submission(contacts=[anna(email="anna@hv-mueller.de")])
    company, _ = verify_company(researched(sub), [PAGE])
    assert company.contacts[0].email is None and not company.contacts[0].email_published


def test_apply_maps_enums_and_unknowns() -> None:
    claim = {"value": "mainly_residential", "source_url": SITE, "quote": "x"}
    company = researched(submission(residential_share=claim))
    assert company.residential_share.value == "mainly_residential"
    assert company.residential_share.status is Status.PUBLISHED
    assert company.units_managed.status is Status.UNKNOWN


def test_inputs_are_not_mutated() -> None:
    company = researched(submission(contacts=[anna()]))
    verify_company(company, [PAGE])
    assert company.contacts[0].verified is None
