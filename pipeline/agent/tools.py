"""The research agent's two tools and their execution.

fetch_page is limited to the company's own site and a fixed number of pages, so text from a
web page (untrusted) can never send the agent elsewhere.
"""

from pipeline.agent.contracts import PageSource
from pipeline.agent.prompt import format_page
from pipeline.agent.schema import submission_json_schema
from pipeline.models import Company, Page
from pipeline.utils.urls import domain_of, is_same_site, normalize_url

FETCH_PAGE = "fetch_page"
SUBMIT_RECORD = "submit_record"

FETCH_PAGE_TOOL = {
    "name": FETCH_PAGE,
    "description": (
        "Fetch one more page of the company's own website and get its text. Only URLs on the "
        "same site; the number of fetches per company is limited."
    ),
    "strict": True,
    "input_schema": {
        "type": "object",
        "properties": {"url": {"type": "string", "description": "Absolute URL on the same site"}},
        "required": ["url"],
        "additionalProperties": False,
    },
}

SUBMIT_RECORD_TOOL = {
    "name": SUBMIT_RECORD,
    "description": (
        "Submit the research record for this company. Call exactly once, at the end. Use null "
        "for anything the pages do not state."
    ),
    "strict": True,
    "input_schema": submission_json_schema(),
}

TOOLS = [FETCH_PAGE_TOOL, SUBMIT_RECORD_TOOL]  # fixed order: part of the cached prefix


class ToolBox:
    """Executes fetch_page for one company and remembers every page the agent has seen."""

    def __init__(self, source: PageSource, company: Company, given: list[Page], max_fetches: int):
        self.source = source
        self.company = company
        self.max_fetches = max_fetches
        self.fetches = 0
        # The homepage may redirect to a new domain: both count as the company's site.
        first = given[0].url if given else None
        self.site_domains = {d for d in (domain_of(company.website), domain_of(first)) if d}
        self.pages: list[Page] = []
        self.seen_urls: set[str] = set()
        for page in given:
            self._add(page)

    def fetch_page(self, url: str) -> tuple[str, bool]:
        """Returns (content, is_error)."""
        if not any(is_same_site(url, domain) for domain in self.site_domains):
            return f"Only pages of {', '.join(sorted(self.site_domains))} can be fetched.", True
        if normalize_url(url) in {normalize_url(u) for u in self.seen_urls}:
            return "This page was already provided above.", False
        if self.fetches >= self.max_fetches:
            return f"Fetch limit of {self.max_fetches} reached. Call submit_record now.", True
        self.fetches += 1
        page = self.source.fetch(self.company.id, url)
        if page.error or not page.text.strip():
            return f"Could not use {url}: {page.error or 'page has no text'}", True
        self._add(page)
        return format_page(page), False

    def _add(self, page: Page) -> None:
        self.pages.append(page)
        self.seen_urls |= {page.url, page.requested_url}
