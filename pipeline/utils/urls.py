"""URL normalising, used for deduplication and fetching."""

from collections.abc import Iterable
from urllib.parse import urlsplit, urlunsplit

from pipeline import config


def normalize_url(url: str | None) -> str | None:
    if not url or not url.strip():
        return None
    url = url.strip()
    if "://" not in url:
        url = "https://" + url
    parts = urlsplit(url)
    host = (parts.hostname or "").lower().removeprefix("www.")
    if "." not in host:
        return None
    return urlunsplit((parts.scheme.lower(), host, parts.path.rstrip("/"), "", ""))


def domain_of(url: str | None) -> str | None:
    normalized = normalize_url(url)
    return urlsplit(normalized).hostname if normalized else None


def is_platform_domain(domain: str, platforms: Iterable[str] = config.PLATFORM_DOMAINS) -> bool:
    return any(domain == p or domain.endswith("." + p) for p in platforms)


def company_id(website: str | None, source: str, source_id: str) -> str:
    """Company domain if it has its own site, else a source-scoped id."""
    domain = domain_of(website)
    if domain and not is_platform_domain(domain):
        return domain
    return f"{source}:{source_id}"
