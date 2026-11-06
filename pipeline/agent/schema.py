"""The research agent's submission: one claim per KPI, each with the evidence behind it.

A claim with a value must carry the page URL it came from and a verbatim quote from that page.
Code checks this (pipeline/agent/validation.py) and later re-verifies every quote against the
stored page text, so "evidence or unknown" is enforced by code, not by trusting the model.
"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class ResidentialShare(StrEnum):
    MAINLY_RESIDENTIAL = "mainly_residential"
    MIXED = "mixed"
    MAINLY_COMMERCIAL = "mainly_commercial"


class BuyerType(StrEnum):
    THIRD_PARTY_RENTAL = "third_party_rental"
    THIRD_PARTY_WEG = "third_party_weg"
    THIRD_PARTY_UNCLEAR = "third_party_unclear"
    COOPERATIVE = "cooperative"
    PRIVATE_LANDLORD = "private_landlord"
    MUNICIPAL = "municipal"


class _Strict(BaseModel):
    # Strict tool schemas need additionalProperties: false and every property required.
    model_config = ConfigDict(extra="forbid")


class IntClaim(_Strict):
    value: int | None
    source_url: str | None
    quote: str | None


class TextClaim(_Strict):
    value: str | None
    source_url: str | None
    quote: str | None


class ResidentialShareClaim(_Strict):
    value: ResidentialShare | None
    source_url: str | None
    quote: str | None


class BuyerTypeClaim(_Strict):
    value: BuyerType | None
    source_url: str | None
    quote: str | None


class ContactClaim(_Strict):
    name: str
    role: str | None
    email: str | None
    linkedin: str | None
    source_url: str
    quote: str


class ResearchSubmission(_Strict):
    units_managed: IntClaim
    residential_share: ResidentialShareClaim
    buyer_type: BuyerTypeClaim
    software: TextClaim
    association: TextClaim
    growth: TextClaim
    employees: IntClaim
    properties: IntClaim
    remote_reading: TextClaim
    metering_provider: TextClaim
    contacts: list[ContactClaim]
    notes: str | None


class ResearchRecord(BaseModel):
    """One company's research run: what the agent submitted, what it saw, what it cost."""

    company_id: str
    model: str
    effort: str
    submission: ResearchSubmission | None
    page_urls: list[str] = Field(default_factory=list)
    turns: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0
    cost_usd: float = 0.0
    stop: str  # submitted | max_turns | cost_cap | refusal | no_pages | error
    errors: list[str] = Field(default_factory=list)
    finished_at: datetime


CLAIM_FIELDS: tuple[str, ...] = tuple(
    name for name in ResearchSubmission.model_fields if name not in ("contacts", "notes")
)


def submission_json_schema() -> dict:
    """JSON schema for the strict submit_record tool, generated from the model above."""
    return _drop_keys(ResearchSubmission.model_json_schema(), {"title"})


def _drop_keys(node: object, keys: set[str]) -> object:
    if isinstance(node, dict):
        return {
            k: _drop_keys(v, keys)
            for k, v in node.items()
            if not (k in keys and not isinstance(v, dict))
        }
    if isinstance(node, list):
        return [_drop_keys(item, keys) for item in node]
    return node
