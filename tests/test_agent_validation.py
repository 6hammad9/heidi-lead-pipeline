from pipeline.agent.schema import CLAIM_FIELDS, ResearchSubmission
from pipeline.agent.validation import sanitize_submission, validate_submission

HOME = "https://hv-mueller.de"
TEAM = "https://hv-mueller.de/team"
SEEN = {HOME, TEAM}
EMPTY = {"value": None, "source_url": None, "quote": None}


def submission(**claims: dict) -> ResearchSubmission:
    payload: dict = {name: dict(EMPTY) for name in CLAIM_FIELDS}
    payload |= {"contacts": [], "notes": None}
    payload |= claims
    return ResearchSubmission.model_validate(payload)


def contact(**overrides: object) -> dict:
    base = {
        "name": "Anna Müller",
        "role": "Geschäftsführerin",
        "email": None,
        "linkedin": None,
        "source_url": TEAM,
        "quote": "Anna Müller, Geschäftsführerin",
    }
    return base | overrides


def test_all_unknown_is_valid() -> None:
    assert validate_submission(submission(), SEEN) == []


def test_evidenced_value_is_valid_even_with_www_and_slash_variants() -> None:
    units = {"value": 2400, "source_url": "https://www.hv-mueller.de/", "quote": "2.400 WE"}
    assert validate_submission(submission(units_managed=units), SEEN) == []


def test_value_without_quote_is_rejected_and_nulled() -> None:
    sub = submission(units_managed={"value": 2400, "source_url": HOME, "quote": None})
    cleaned, problems = sanitize_submission(sub, SEEN)
    assert problems and problems[0].startswith("units_managed:")
    assert cleaned.units_managed.value is None


def test_source_not_among_given_pages_is_rejected() -> None:
    claim = {"value": "Domus", "source_url": "https://other.de/jobs", "quote": "Domus"}
    problems = validate_submission(submission(software=claim), SEEN)
    assert problems == [
        "software: source_url 'https://other.de/jobs' is not one of the pages you were given"
    ]


def test_non_positive_numbers_and_blank_text_are_rejected() -> None:
    sub = submission(
        employees={"value": 0, "source_url": HOME, "quote": "0"},
        growth={"value": "  ", "source_url": HOME, "quote": "x"},
    )
    problems = validate_submission(sub, SEEN)
    assert {p.split(":")[0] for p in problems} == {"employees", "growth"}


def test_overlong_quote_is_rejected() -> None:
    claim = {"value": "VDIV", "source_url": HOME, "quote": "x" * 301}
    assert "longer than" in validate_submission(submission(association=claim), SEEN)[0]


def test_null_value_with_leftover_evidence_is_tidied_without_problem() -> None:
    sub = submission(software={"value": None, "source_url": HOME, "quote": "Domus"})
    cleaned, problems = sanitize_submission(sub, SEEN)
    assert problems == []
    assert (cleaned.software.source_url, cleaned.software.quote) == (None, None)


def test_bad_contacts_are_dropped_good_ones_kept() -> None:
    sub = submission(
        contacts=[
            contact(),
            contact(name="Bob", source_url="https://elsewhere.de"),
            contact(name="Cem", email="cem at hv-mueller.de"),
        ]
    )
    cleaned, problems = sanitize_submission(sub, SEEN)
    assert [c.name for c in cleaned.contacts] == ["Anna Müller"]
    assert len(problems) == 2


def test_sanitize_does_not_mutate_input() -> None:
    sub = submission(units_managed={"value": 5, "source_url": None, "quote": None})
    sanitize_submission(sub, SEEN)
    assert sub.units_managed.value == 5
