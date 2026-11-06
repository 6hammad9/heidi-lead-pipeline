from datetime import UTC, date, datetime

import pytest

from pipeline import config
from pipeline.agent import prompt
from pipeline.agent.schema import CLAIM_FIELDS
from pipeline.models import Company, Link, Page

NOW = datetime(2026, 11, 7, tzinfo=UTC)


def page(url: str, text: str = "Text", links: list[Link] | None = None, **kw: object) -> Page:
    return Page(url=url, requested_url=url, fetched_at=NOW, text=text, links=links or [], **kw)


def company() -> Company:
    return Company(
        id="hv-mueller.de",
        name="HV Müller GmbH",
        website="https://hv-mueller.de",
        street="Musterstraße 1",
        postcode="10115",
        city="Berlin",
    )


def test_system_prompt_names_every_submission_field() -> None:
    for field in (*CLAIM_FIELDS, "contacts", "notes"):
        assert field in prompt.SYSTEM_PROMPT, field


def test_system_prompt_is_identical_for_every_company() -> None:
    # It is the cached prefix: anything company- or run-specific would break caching.
    assert "Müller" not in prompt.SYSTEM_PROMPT
    assert "Today is" not in prompt.SYSTEM_PROMPT


def test_user_message_contains_company_pages_date_and_links() -> None:
    home = page(
        "https://hv-mueller.de",
        "Wir verwalten 2.400 Einheiten.",
        links=[Link(url="https://hv-mueller.de/team", text="Team")],
    )
    message = prompt.build_user_message(company(), [home], date(2026, 11, 7))
    assert "Today is 2026-11-07." in message
    assert "HV Müller GmbH" in message
    assert "Musterstraße 1, 10115 Berlin" in message
    assert '<page url="https://hv-mueller.de">' in message
    assert "Wir verwalten 2.400 Einheiten." in message
    assert "- Team: https://hv-mueller.de/team" in message


def test_truncated_page_is_marked() -> None:
    assert "[page text truncated]" in prompt.format_page(page("https://a.de", truncated=True))


def test_remaining_links_skip_provided_pages_and_duplicates() -> None:
    home = page(
        "https://a.de",
        links=[
            Link(url="https://a.de/impressum", text="Impressum"),
            Link(url="https://a.de/team", text="Team"),
            Link(url="https://a.de/team", text="Unser Team"),
        ],
    )
    impressum = page("https://a.de/impressum")
    links = prompt.remaining_links([home, impressum])
    assert [link.url for link in links] == ["https://a.de/team"]


def test_remaining_links_are_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "PAGE_LINKS_MAX", 2)
    links = [Link(url=f"https://a.de/p{i}", text=str(i)) for i in range(5)]
    assert len(prompt.remaining_links([page("https://a.de", links=links)])) == 2


def test_no_links_message() -> None:
    message = prompt.build_user_message(company(), [page("https://a.de")], date(2026, 11, 7))
    assert "No further links on this site." in message
