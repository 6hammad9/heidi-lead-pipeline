"""URL normalising, used for deduplication and fetching."""

import re
from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from pipeline import config

_WEB_SCHEMES = {"http", "https"}
# Unicode word characters keep umlaut domains (müller-verwaltung.de) valid; spaces are not.
_HOST = re.compile(r"[\w-]+(\.[\w-]+)+")


def normalize_url(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    url = url.strip()
    if "://" not in url:
        if _has_non_web_scheme(url):
            return None
        url = "https://" + url
    parts = urlsplit(url)
    if parts.scheme.lower() not in _WEB_SCHEMES or parts.username or parts.password:
        return None
    host = (parts.hostname or "").lower().removeprefix("www.")
    if not _HOST.fullmatch(host):
        return None
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/"), "", ""))


def _has_non_web_scheme(url: str) -> bool:
    """mailto:, tel:, javascript: … have no dot or slash before the first colon (host:port has)."""
    head, sep, _ = url.partition(":")
    return bool(sep) and "." not in head and "/" not in head


def domain_of(url: str | None) -> str | None:
    normalized = normalize_url(url)
    return urlsplit(normalized).hostname if normalized else None


def is_platform_domain(domain: str, platforms: Iterable[str] = config.PLATFORM_DOMAINS) -> bool:
    return any(domain == p or domain.endswith("." + p) for p in platforms)


def is_same_site(url: str | None, site_domain: str) -> bool:
    """True for the company's own domain and its subdomains; the agent may fetch nothing else."""
    domain = domain_of(url)
    return bool(domain) and (domain == site_domain or domain.endswith("." + site_domain))


def company_id(website: str | None, source: str, source_id: str) -> str:
    """Company domain if it has its own site, else a source-scoped id."""
    domain = domain_of(website)
    if domain and not is_platform_domain(domain):
        return domain
    return f"{source}:{source_id}"
