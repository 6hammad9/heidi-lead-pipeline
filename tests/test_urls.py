import pytest

from pipeline.utils.urls import domain_of, normalize_url


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


@pytest.mark.parametrize("raw", [None, "", "   ", "localhost", "not a url"])
def test_normalize_url_rejects_invalid(raw: str | None) -> None:
    assert normalize_url(raw) is None


def test_domain_of_ignores_www_scheme_and_path() -> None:
    variants = ["http://www.example.de", "https://example.de/impressum", "example.de/"]
    assert {domain_of(v) for v in variants} == {"example.de"}
