import pytest

from pipeline.utils.urls import (
    company_id,
    domain_of,
    is_platform_domain,
    is_same_site,
    normalize_url,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("www.Example.de", "https://example.de"),
        ("http://www.example.de/", "http://example.de"),
        ("https://example.de/berlin/", "https://example.de/berlin"),
        ("https://example.de/?utm_source=x#team", "https://example.de"),
        ("  https://EXAMPLE.de  ", "https://example.de"),
        ("https://www.example.de:443/kontakt", "https://example.de/kontakt"),
    ],
)
def test_normalize_url(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        "",
        "   ",
        "localhost",
        "not a url",
        "foo bar.de",
        "mailto:info@hv-mueller.de",
        "tel:+493012345",
        "javascript:void(0)",
        "ftp://hv-mueller.de/file",
        "https://user:pass@hv-mueller.de",
        "https://evil.com@hv-mueller.de",
    ],
)
def test_normalize_url_rejects_invalid(raw: str | None) -> None:
    assert normalize_url(raw) is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("müller-verwaltung.de", "https://müller-verwaltung.de"),
        ("hv-mueller.de:8080/kontakt", "https://hv-mueller.de/kontakt"),
    ],
)
def test_normalize_url_keeps_umlaut_domains_and_drops_port(raw: str, expected: str) -> None:
    assert normalize_url(raw) == expected


def test_domain_of_ignores_www_scheme_and_path() -> None:
    variants = ["http://www.example.de", "https://example.de/impressum", "example.de/"]
    assert {domain_of(v) for v in variants} == {"example.de"}


@pytest.mark.parametrize(
    ("domain", "expected"),
    [
        ("facebook.com", True),
        ("de-de.facebook.com", True),
        ("mueller.wixsite.com", True),
        ("hausverwaltung-mueller.de", False),
        ("notfacebook.com", False),
    ],
)
def test_is_platform_domain(domain: str, expected: bool) -> None:
    assert is_platform_domain(domain) is expected


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://hv-mueller.de/impressum", True),
        ("http://www.hv-mueller.de/team/", True),
        ("https://karriere.hv-mueller.de/jobs", True),
        ("https://evil-hv-mueller.de/", False),
        ("https://hv-mueller.de.evil.com/", False),
        ("https://facebook.com/hv-mueller.de", False),
        ("mailto:info@hv-mueller.de", False),
        (None, False),
    ],
)
def test_is_same_site(url: str | None, expected: bool) -> None:
    assert is_same_site(url, "hv-mueller.de") is expected


def test_company_id_uses_own_domain() -> None:
    assert company_id("https://www.hv-mueller.de/kontakt", "osm", "node/1") == "hv-mueller.de"


@pytest.mark.parametrize("website", [None, "https://www.facebook.com/hvmueller", "not a url"])
def test_company_id_falls_back_to_source_id(website: str | None) -> None:
    assert company_id(website, "osm", "node/1") == "osm:node/1"
