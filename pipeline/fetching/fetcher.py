"""Downloads company pages for the research agent; never raises for HTTP or robots problems.

Redirects are followed by hand so every hop is checked: http(s) only, robots.txt, and no
private or local addresses (a website must not be able to point us at the home network).
"""

import ipaddress
import logging
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import requests

from pipeline import config
from pipeline.fetching.html_text import html_to_text, select_prefetch_links, truncate_text
from pipeline.fetching.page_store import PageStore
from pipeline.fetching.robots import RobotsPolicy
from pipeline.models import Company, Page
from pipeline.utils.http import HttpClient, RetryableStatusError
from pipeline.utils.urls import domain_of

log = logging.getLogger(__name__)

MAX_REDIRECTS = 5
HTML_TYPES = ("text/html", "application/xhtml+xml")


def is_public_host(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return True  # unresolvable: the request itself will fail and be reported
    return all(ipaddress.ip_address(info[4][0]).is_global for info in infos)


class PageFetcher:
    def __init__(
        self,
        client: HttpClient,
        store: PageStore,
        robots: RobotsPolicy,
        is_public: Callable[[str], bool] = is_public_host,
    ) -> None:
        self.client = client
        self.store = store
        self.robots = robots
        self.is_public = is_public

    def prefetch(self, company: Company) -> list[Page]:
        if not company.website:
            return []
        home = self.fetch(company.id, company.website)
        if home.error:
            return [home]
        links = select_prefetch_links(
            home.links, config.PREFETCH_KEYWORD_GROUPS, config.PREFETCH_MAX_PAGES - 1
        )
        return [home, *(self.fetch(company.id, link.url) for link in links)]

    def fetch(self, company_id: str, url: str) -> Page:
        if cached := self.store.get(company_id, url):
            return cached
        page = self._download(url)
        self.store.put(company_id, page)
        return page

    def _download(self, url: str) -> Page:
        current = url
        for _ in range(MAX_REDIRECTS + 1):
            if problem := self._blocked(current):
                return _error_page(url, current, problem)
            try:
                resp = self.client.get(current, stream=True, allow_redirects=False)
            except requests.HTTPError as e:
                status = e.response.status_code if e.response is not None else None
                return _error_page(url, current, f"HTTP {status}", status)
            except RetryableStatusError as e:
                return _error_page(url, current, f"HTTP {e.status}", e.status)
            except requests.RequestException as e:
                return _error_page(url, current, f"request failed: {type(e).__name__}")
            if not resp.is_redirect:
                return self._to_page(url, current, resp)
            resp.close()
            current = urljoin(current, resp.headers.get("Location", ""))
        return _error_page(url, current, "too many redirects")

    def _blocked(self, url: str) -> str | None:
        parts = urlsplit(url)
        if parts.scheme not in ("http", "https") or not parts.hostname:
            return "not an http(s) URL"
        if not self.is_public(parts.hostname):
            return "points to a private or local address"
        if not self.robots.allowed(url):
            return "blocked by robots.txt"
        return None

    def _to_page(self, requested: str, final: str, resp: requests.Response) -> Page:
        content_type = resp.headers.get("Content-Type", "")
        if not content_type.lower().startswith(HTML_TYPES):
            resp.close()
            return _error_page(requested, final, f"not an HTML page: {content_type or 'unknown'}")
        body = _read_capped(resp, config.PAGE_MAX_BYTES)
        text, links = html_to_text(body, final, domain_of(final) or "", _charset(content_type))
        text, truncated = truncate_text(text, config.PAGE_TEXT_MAX_CHARS)
        return Page(
            url=final,
            requested_url=requested,
            fetched_at=datetime.now(UTC),
            status=resp.status_code,
            text=text,
            truncated=truncated,
            links=links,
        )


def _read_capped(resp: requests.Response, max_bytes: int) -> bytes:
    """Stops downloading at the cap instead of loading a huge response into memory."""
    chunks, size = [], 0
    try:
        for chunk in resp.iter_content(64 * 1024):
            chunks.append(chunk)
            size += len(chunk)
            if size >= max_bytes:
                break
    finally:
        resp.close()
    return b"".join(chunks)[:max_bytes]


def _charset(content_type: str) -> str | None:
    for part in content_type.split(";")[1:]:
        key, _, value = part.strip().partition("=")
        if key.lower() == "charset" and value:
            return value.strip("\"' ")
    return None


def _error_page(requested: str, final: str, error: str, status: int | None = None) -> Page:
    log.info("Page not usable %s: %s", final, error)
    return Page(
        url=final, requested_url=requested, fetched_at=datetime.now(UTC), status=status, error=error
    )
