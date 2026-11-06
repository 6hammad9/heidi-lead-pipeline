"""Interfaces between the research agent and its collaborators.

The agent depends only on these protocols, so page fetching, spend recording and the agent
loop can be built and tested independently (tests pass fakes).
"""

from datetime import datetime
from typing import Protocol

from pydantic import BaseModel

from pipeline.models import Company, Page


class SpendEntry(BaseModel):
    """One Anthropic API call as billed: written to the append-only spend ledger."""

    at: datetime
    model: str
    company_id: str
    input_tokens: int
    output_tokens: int
    cache_creation_tokens: int
    cache_read_tokens: int
    cost_usd: float
    request_id: str | None = None


class UsageLike(Protocol):
    """The fields of anthropic's response.usage that cost depends on."""

    input_tokens: int
    output_tokens: int
    cache_creation_input_tokens: int | None
    cache_read_input_tokens: int | None


class PageSource(Protocol):
    def prefetch(self, company: Company) -> list[Page]:
        """Homepage plus keyword-selected pages of the company's own site. Never raises for
        HTTP/robots problems: such pages come back with `error` set."""
        ...

    def fetch(self, company_id: str, url: str) -> Page:
        """One page, from the store if already fetched. Never raises for HTTP/robots problems."""
        ...


class SpendRecorder(Protocol):
    def record(self, entry: SpendEntry) -> None: ...

    def total_usd(self) -> float:
        """Everything spent so far, across all runs."""
        ...
