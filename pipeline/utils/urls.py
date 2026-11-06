"""URL normalising, used for deduplication and fetching."""

from urllib.parse import urlsplit, urlunsplit


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
