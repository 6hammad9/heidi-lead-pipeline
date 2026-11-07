"""The single data schema passed between all pipeline steps."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class Status(StrEnum):
    PUBLISHED = "published"
    ESTIMATED = "estimated"
    UNKNOWN = "unknown"


class Fact(BaseModel):
    """A KPI or info value with its evidence (RULEBOOK: every value needs a source)."""

    value: str | int | None = None
    status: Status = Status.UNKNOWN
    source_url: str | None = None
    quote: str | None = None
    verified: bool | None = None  # set by the quote-verification step, None = not checked yet


class SourceRef(BaseModel):
    source: str
    source_id: str
    url: str
    collected_at: datetime


class Contact(BaseModel):
    name: str
    role: str | None = None
    email: str | None = None
    email_published: bool = False  # False = pattern-guessed, never counted as "Named + email"
    linkedin: str | None = None
    source_url: str | None = None
    quote: str | None = None
    verified: bool | None = None


class Link(BaseModel):
    url: str
    text: str


class Page(BaseModel):
    """A fetched page exactly as the agent saw it; quote verification re-reads this text."""

    url: str  # final URL after redirects
    requested_url: str
    fetched_at: datetime
    status: int | None = None
    text: str = ""
    truncated: bool = False
    links: list[Link] = Field(default_factory=list)
    error: str | None = None


class Company(BaseModel):
    id: str
    name: str
    website: str | None = None
    phone: str | None = None
    email_general: str | None = None
    street: str | None = None
    postcode: str | None = None
    city: str | None = None
    sources: list[SourceRef] = Field(default_factory=list)

    units_managed: Fact = Field(default_factory=Fact)
    residential_share: Fact = Field(default_factory=Fact)
    buyer_type: Fact = Field(default_factory=Fact)
    software: Fact = Field(default_factory=Fact)
    association: Fact = Field(default_factory=Fact)
    growth: Fact = Field(default_factory=Fact)

    employees: Fact = Field(default_factory=Fact)
    properties: Fact = Field(default_factory=Fact)
    remote_reading: Fact = Field(default_factory=Fact)
    metering_provider: Fact = Field(default_factory=Fact)
    general_email: Fact = Field(default_factory=Fact)

    contacts: list[Contact] = Field(default_factory=list)
    research_status: str | None = None  # the agent's stop reason; None = not researched
    research_notes: str | None = None
    errors: list[str] = Field(default_factory=list)
