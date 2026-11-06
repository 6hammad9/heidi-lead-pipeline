from pathlib import Path

import pytest
import requests

from pipeline import config
from pipeline.fetching.fetcher import PageFetcher
from pipeline.fetching.html_text import html_to_text, select_prefetch_links, truncate_text
from pipeline.fetching.page_store import PageStore
from pipeline.fetching.robots import RobotsPolicy
from pipeline.models import Company, Link
from pipeline.utils.http import RetryableStatusError

SITE = "hv-mueller.de"


class FakeResponse:
    def __init__(self, status: int = 200, body: bytes = b"", headers: dict | None = None) -> None:
        self.status_code = status
        self.headers = {"Content-Type": "text/html; charset=utf-8"} | (headers or {})
        self.body = body
        self.text = body.decode("utf-8", errors="replace")
        self.closed = False

    @property
    def is_redirect(self) -> bool:
        return self.status_code in (301, 302, 303, 307, 308) and "Location" in self.headers

    def iter_content(self, size: int):
        for i in range(0, len(self.body), size):
            yield self.body[i : i + size]

    def close(self) -> None:
        self.closed = True


class FakeWeb:
    """url -> FakeResponse or exception; robots.txt defaults to 404 (allow all)."""

    def __init__(self, pages: dict) -> None:
        self.pages = pages
        self.requested: list[str] = []

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.requested.append(url)
        result = self.pages.get(url)
        if result is None and url.endswith("/robots.txt"):
            result = requests.HTTPError("404", response=FakeResponse(404))
        if result is None:
            raise requests.ConnectionError(url)
        if isinstance(result, Exception):
            raise result
        return result


def html(body: str) -> bytes:
    return f"<html><head><title>t</title></head><body>{body}</body></html>".encode()


def fetcher(web: FakeWeb, tmp_path: Path, public: bool = True) -> PageFetcher:
    return PageFetcher(web, PageStore(tmp_path), RobotsPolicy(web), is_public=lambda h: public)


# --- html_text ------------------------------------------------------------------------


def test_text_keeps_umlauts_in_latin1_pages_and_drops_scripts() -> None:
    page = (
        '<html><head><meta charset="iso-8859-1"></head><body><script>x()</script>'
        "<p>Über uns:   Hausverwaltung   Müller</p><footer>Impressum</footer></body></html>"
    ).encode("iso-8859-1")
    text, _ = html_to_text(page, f"https://{SITE}/", SITE)
    assert text == "Über uns: Hausverwaltung Müller\nImpressum"


def test_links_are_resolved_same_site_deduped_and_filtered() -> None:
    body = html(
        '<a href="/impressum">Impressum</a><a href="impressum#top">dup</a>'
        '<a href="https://www.hv-mueller.de/team">Team</a><a href="https://other.de/x">x</a>'
        '<a href="mailto:a@hv-mueller.de">mail</a><a href="/flyer.pdf">pdf</a>'
    )
    _, links = html_to_text(body, f"https://{SITE}/", SITE)
    assert [link.url for link in links] == [
        f"https://{SITE}/impressum",
        "https://www.hv-mueller.de/team",
    ]


def test_truncate_cuts_at_a_boundary() -> None:
    assert truncate_text("short", 10) == ("short", False)
    assert truncate_text("one two three", 9) == ("one two", True)


def test_prefetch_selection_follows_group_order_and_matches_umlauts() -> None:
    links = [
        Link(url=f"https://{SITE}/kontakt", text="Kontakt"),
        Link(url=f"https://{SITE}/wir", text="Über uns"),
        Link(url=f"https://{SITE}/impressum", text="Impressum"),
    ]
    groups = [["impressum"], ["ueber-uns"], ["team"]]
    assert [link.text for link in select_prefetch_links(links, groups, 5)] == [
        "Impressum",
        "Über uns",
    ]
    assert len(select_prefetch_links(links, groups, 1)) == 1


# --- robots ---------------------------------------------------------------------------


def test_robots_rules_404_and_5xx() -> None:
    web = FakeWeb(
        {
            "https://a.de/robots.txt": FakeResponse(body=b"User-agent: *\nDisallow: /private"),
            "https://down.de/robots.txt": RetryableStatusError(503, "", "u"),
        }
    )
    robots = RobotsPolicy(web)
    assert robots.allowed("https://a.de/team")
    assert not robots.allowed("https://a.de/private/x")
    assert robots.allowed("https://b.de/anything")  # 404: allowed
    assert not robots.allowed("https://down.de/x")  # 5xx: don't crawl
    robots.allowed("https://a.de/other")
    assert web.requested.count("https://a.de/robots.txt") == 1  # cached per host


# --- fetcher --------------------------------------------------------------------------


def test_fetch_reads_page_and_store_avoids_second_download(tmp_path: Path) -> None:
    web = FakeWeb({f"https://{SITE}/": FakeResponse(body=html("<p>Wir verwalten 900 WE</p>"))})
    f = fetcher(web, tmp_path)
    page = f.fetch("c1", f"https://{SITE}/")
    assert page.text == "Wir verwalten 900 WE" and page.error is None
    f.fetch("c1", f"https://{SITE}/")
    assert web.requested.count(f"https://{SITE}/") == 1


def test_redirect_to_private_address_is_refused(tmp_path: Path) -> None:
    web = FakeWeb(
        {f"https://{SITE}/": FakeResponse(302, headers={"Location": "http://192.168.0.1/"})}
    )
    f = PageFetcher(
        web, PageStore(tmp_path), RobotsPolicy(web), is_public=lambda h: h != "192.168.0.1"
    )
    page = f.fetch("c1", f"https://{SITE}/")
    assert page.error == "points to a private or local address"
    assert "http://192.168.0.1/" not in web.requested


def test_redirect_is_followed_and_final_url_kept(tmp_path: Path) -> None:
    web = FakeWeb(
        {
            f"https://{SITE}/": FakeResponse(301, headers={"Location": "https://neu.de/"}),
            "https://neu.de/": FakeResponse(body=html("<p>Neu</p>")),
        }
    )
    page = fetcher(web, tmp_path).fetch("c1", f"https://{SITE}/")
    assert (page.requested_url, page.url, page.text) == (
        f"https://{SITE}/",
        "https://neu.de/",
        "Neu",
    )


def test_non_html_http_errors_and_robots_give_error_pages(tmp_path: Path) -> None:
    web = FakeWeb(
        {
            "https://a.de/robots.txt": FakeResponse(body=b"User-agent: *\nDisallow: /no"),
            "https://a.de/doc": FakeResponse(headers={"Content-Type": "application/pdf"}),
            "https://a.de/gone": requests.HTTPError("404", response=FakeResponse(404)),
            "https://dead.de/robots.txt": requests.ConnectionError("cannot resolve dead.de"),
        }
    )
    f = fetcher(web, tmp_path)
    assert f.fetch("c", "https://a.de/doc").error.startswith("not an HTML page")
    assert f.fetch("c", "https://a.de/gone").status == 404
    assert f.fetch("c", "https://a.de/no").error == "blocked by robots.txt"
    assert f.fetch("c", "https://a.de/down").error.startswith("request failed")
    assert f.fetch("c", "https://dead.de/").error.startswith("site unreachable")


def test_size_cap_and_truncation(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "PAGE_TEXT_MAX_CHARS", 50)
    web = FakeWeb({"https://a.de/": FakeResponse(body=html("<p>" + "wort " * 100 + "</p>"))})
    page = fetcher(web, tmp_path).fetch("c", "https://a.de/")
    assert page.truncated and len(page.text) <= 50


def test_prefetch_fetches_homepage_then_keyword_pages(tmp_path: Path) -> None:
    home = html('<a href="/kontakt">Kontakt</a><a href="/impressum">Impressum</a>')
    web = FakeWeb(
        {
            f"https://{SITE}": FakeResponse(body=home),
            f"https://{SITE}/impressum": FakeResponse(body=html("<p>GF: Anna Müller</p>")),
        }
    )
    company = Company(id=SITE, name="HV", website=f"https://{SITE}")
    pages = fetcher(web, tmp_path).prefetch(company)
    assert [p.requested_url for p in pages] == [f"https://{SITE}", f"https://{SITE}/impressum"]
    assert pages[1].text == "GF: Anna Müller"


def test_prefetch_falls_back_to_site_root_when_listed_page_is_dead(tmp_path: Path) -> None:
    web = FakeWeb(
        {
            f"https://{SITE}/Betrug": requests.HTTPError("404", response=FakeResponse(404)),
            f"https://{SITE}/": FakeResponse(body=html("<p>Startseite</p>")),
        }
    )
    company = Company(id=SITE, name="HV", website=f"https://{SITE}/Betrug")
    pages = fetcher(web, tmp_path).prefetch(company)
    assert [(p.url, p.text) for p in pages] == [(f"https://{SITE}/", "Startseite")]


def test_store_lists_pages_once_per_final_url(tmp_path: Path) -> None:
    store = PageStore(tmp_path)
    web = FakeWeb({"https://a.de/": FakeResponse(body=html("<p>x</p>"))})
    PageFetcher(web, store, RobotsPolicy(web), is_public=lambda h: True).fetch("c", "https://a.de/")
    assert [p.url for p in store.all("c")] == ["https://a.de/"]
    assert store.all("unknown") == []
