"""HTML to plain text and same-site links; choosing which pages to prefetch. Pure."""

import re
from collections.abc import Callable
from urllib.parse import urldefrag, urljoin, urlsplit

from bs4 import BeautifulSoup

from pipeline.models import Link
from pipeline.utils.urls import is_same_site

_DROP_TAGS = ["script", "style", "noscript", "template", "svg", "iframe", "head"]
_NON_HTML = re.compile(
    r"\.(pdf|jpe?g|png|gif|webp|svg|ico|zip|rar|7z|docx?|xlsx?|pptx?|mp[34]|avi|mov|ics|vcf)$", re.I
)
_TRANSLITERATION = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"})
LINK_TEXT_MAX = 80


def html_to_text(
    html: bytes, base_url: str, site_domain: str, encoding: str | None = None
) -> tuple[str, list[Link]]:
    """Parsed from bytes so the charset comes from the HTTP header, a meta tag or detection."""
    soup = BeautifulSoup(html, "html.parser", from_encoding=encoding)
    for tag in soup(_DROP_TAGS):
        tag.decompose()
    links = _links(soup, base_url, site_domain)
    lines = (" ".join(line.split()) for line in soup.get_text("\n").splitlines())
    return "\n".join(line for line in lines if line), links


def _links(soup: BeautifulSoup, base_url: str, site_domain: str) -> list[Link]:
    found: dict[str, Link] = {}
    for anchor in soup.find_all("a", href=True):
        url = urldefrag(urljoin(base_url, anchor["href"].strip())).url
        if url in found or not _is_fetchable(url, site_domain):
            continue
        text = " ".join(anchor.get_text(" ").split()) or anchor.get("title", "")
        found[url] = Link(url=url, text=text[:LINK_TEXT_MAX])
    return list(found.values())


def _is_fetchable(url: str, site_domain: str) -> bool:
    parts = urlsplit(url)
    return (
        parts.scheme in ("http", "https")
        and is_same_site(url, site_domain)
        and not _NON_HTML.search(parts.path)
    )


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    cut = text[:max_chars]
    boundary = max(cut.rfind("\n"), cut.rfind(" "))
    return (cut[:boundary] if boundary > 0 else cut), True


def select_prefetch_links(
    links: list[Link], keyword_groups: list[list[str]], limit: int
) -> list[Link]:
    """One link per keyword group, in group order; a URL-path match beats a link-text match."""
    chosen: list[Link] = []
    for group in keyword_groups:
        if len(chosen) >= limit:
            break
        keywords = [_fold(k) for k in group]
        candidates = [link for link in links if link not in chosen]
        match = _first_match(candidates, keywords, lambda link: urlsplit(link.url).path)
        match = match or _first_match(candidates, keywords, lambda link: link.text)
        if match:
            chosen.append(match)
    return chosen


def _first_match(
    links: list[Link], keywords: list[str], field: Callable[[Link], str]
) -> Link | None:
    return next((link for link in links if any(k in _fold(field(link)) for k in keywords)), None)


def _fold(text: str) -> str:
    """'Über uns' and 'ueber-uns' compare equal."""
    return re.sub(r"[\s_]+", "-", text.lower().translate(_TRANSLITERATION))
