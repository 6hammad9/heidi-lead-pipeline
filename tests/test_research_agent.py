from datetime import UTC, date, datetime
from types import SimpleNamespace

import anthropic
import httpx2
import pytest

from pipeline.agent.contracts import SpendEntry
from pipeline.agent.prompt import SYSTEM_PROMPT
from pipeline.agent.research_agent import NUDGE, ResearchAgent
from pipeline.agent.schema import CLAIM_FIELDS
from pipeline.agent.tools import TOOLS
from pipeline.models import Company, Link, Page

SITE = "https://hv-mueller.de"
NOW = datetime(2026, 11, 7, tzinfo=UTC)
EMPTY = {"value": None, "source_url": None, "quote": None}


def page(url: str, text: str = "Wir verwalten 2.400 Einheiten.", **kw: object) -> Page:
    return Page(url=url, requested_url=url, fetched_at=NOW, text=text, **kw)


HOME = page(SITE, links=[Link(url=f"{SITE}/team", text="Team")])
COMPANY = Company(id="hv-mueller.de", name="HV Müller", website=SITE)


def submission(**claims: dict) -> dict:
    payload: dict = {name: dict(EMPTY) for name in CLAIM_FIELDS} | {"contacts": [], "notes": None}
    return payload | claims


GOOD = submission(units_managed={"value": 2400, "source_url": SITE, "quote": "2.400 Einheiten"})
BAD = submission(units_managed={"value": 2400, "source_url": SITE, "quote": None})


def tool_use(name: str, payload: dict, tid: str = "t1") -> SimpleNamespace:
    return SimpleNamespace(type="tool_use", id=tid, name=name, input=payload)


def response(*blocks: SimpleNamespace, stop: str = "tool_use", out: int = 100) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=out,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    thinking = SimpleNamespace(type="thinking", thinking="", signature="sig")
    return SimpleNamespace(
        content=[thinking, *blocks], stop_reason=stop, usage=usage, _request_id="req"
    )


class FakeClient:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.calls: list[dict] = []
        self.messages = self

    def create(self, **kwargs: object) -> SimpleNamespace:
        self.calls.append(kwargs | {"messages": list(kwargs["messages"])})
        result = self.responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class FakePages:
    def __init__(self, given: list[Page], more: dict[str, Page] | None = None) -> None:
        self.given = given
        self.more = more or {}
        self.fetched: list[str] = []

    def prefetch(self, company: Company) -> list[Page]:
        return self.given

    def fetch(self, company_id: str, url: str) -> Page:
        self.fetched.append(url)
        return self.more.get(url) or page(url, text="", error="HTTP 404")


class FakeLedger:
    def __init__(self) -> None:
        self.entries: list[SpendEntry] = []

    def record(self, entry: SpendEntry) -> None:
        self.entries.append(entry)

    def total_usd(self) -> float:
        return sum(e.cost_usd for e in self.entries)


def agent(client: FakeClient, pages: FakePages | None = None, **kw: object) -> ResearchAgent:
    return ResearchAgent(
        client,
        "claude-haiku-5-5",
        pages or FakePages([HOME]),
        FakeLedger(),
        today=lambda: date(2026, 11, 7),
        **kw,
    )


def test_happy_path_sends_the_documented_request_and_stops_at_once() -> None:
    client = FakeClient(response(tool_use("submit_record", GOOD)))
    record = agent(client).research(COMPANY)
    assert record.stop == "submitted" and record.submission.units_managed.value == 2400
    assert record.turns == 1 and len(client.calls) == 1
    call = client.calls[0]
    assert call["system"] == [
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    ]
    assert call["cache_control"] == {"type": "ephemeral"}
    assert call["thinking"] == {"type": "adaptive"}
    assert call["output_config"] == {"effort": "medium"}
    assert call["tools"] is TOOLS
    assert not {"temperature", "top_p", "top_k", "tool_choice"} & set(call)


def test_every_call_is_recorded_in_the_ledger() -> None:
    a = agent(FakeClient(response(stop="end_turn"), response(tool_use("submit_record", GOOD))))
    record = a.research(COMPANY)
    assert len(a.ledger.entries) == 2
    assert record.cost_usd == pytest.approx(a.ledger.total_usd())


def test_fetch_then_submit_keeps_history_append_only() -> None:
    team = page(f"{SITE}/team", text="Anna Müller, Geschäftsführerin")
    first = response(tool_use("fetch_page", {"url": f"{SITE}/team"}))
    client = FakeClient(first, response(tool_use("submit_record", GOOD, "t2")))
    record = agent(client, FakePages([HOME], {f"{SITE}/team": team})).research(COMPANY)
    assert record.stop == "submitted"
    one, two = client.calls[0]["messages"], client.calls[1]["messages"]
    assert two[: len(one)] == one
    assert two[1] == {"role": "assistant", "content": first.content}  # thinking block kept
    (result,) = two[2]["content"]
    assert result["tool_use_id"] == "t1" and not result["is_error"]
    assert "Anna Müller" in result["content"]
    assert record.page_urls == [SITE, f"{SITE}/team"]


def test_invalid_submission_gets_one_correction() -> None:
    client = FakeClient(
        response(tool_use("submit_record", BAD)), response(tool_use("submit_record", GOOD, "t2"))
    )
    record = agent(client).research(COMPANY)
    assert record.stop == "submitted"
    (feedback,) = client.calls[1]["messages"][-1]["content"]
    assert feedback["is_error"] and "units_managed" in feedback["content"]


def test_corrections_exhausted_keeps_sanitized_record() -> None:
    client = FakeClient(
        response(tool_use("submit_record", BAD)), response(tool_use("submit_record", BAD, "t2"))
    )
    record = agent(client).research(COMPANY)
    assert record.stop == "submitted_sanitized"
    assert record.submission.units_managed.value is None
    assert record.errors


def test_fetch_rules_off_site_limit_and_already_seen() -> None:
    blocks = [
        tool_use("fetch_page", {"url": "https://evil.example/x"}, "a"),
        tool_use("fetch_page", {"url": SITE + "/"}, "b"),
        tool_use("fetch_page", {"url": f"{SITE}/missing"}, "c"),
        tool_use("fetch_page", {"url": f"{SITE}/other"}, "d"),
    ]
    pages = FakePages([HOME])
    client = FakeClient(response(*blocks), response(tool_use("submit_record", GOOD, "e")))
    agent(client, pages, max_fetches=1).research(COMPANY)
    results = client.calls[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == ["a", "b", "c", "d"]  # one message, every id
    assert [r["is_error"] for r in results] == [True, False, True, True]
    assert "already provided" in results[1]["content"]
    assert "Fetch limit" in results[3]["content"]
    assert pages.fetched == [f"{SITE}/missing"]


def test_end_turn_without_tool_gets_a_nudge() -> None:
    client = FakeClient(response(stop="end_turn"), response(tool_use("submit_record", GOOD)))
    agent(client).research(COMPANY)
    assert client.calls[1]["messages"][-1]["content"] == [{"type": "text", "text": NUDGE}]


def test_turn_cap_cost_cap_and_refusal() -> None:
    nudge = [response(stop="end_turn") for _ in range(3)]
    assert agent(FakeClient(*nudge), max_turns=3).research(COMPANY).stop == "max_turns"
    expensive = response(stop="end_turn", out=1_000_000)
    assert agent(FakeClient(expensive)).research(COMPANY).stop == "cost_cap"
    assert agent(FakeClient(response(stop="refusal"))).research(COMPANY).stop == "refusal"


def test_api_error_is_recorded_not_raised() -> None:
    error = anthropic.APIConnectionError(request=httpx2.Request("POST", "https://api"))
    record = agent(FakeClient(error)).research(COMPANY)
    assert record.stop == "error" and "APIConnectionError" in record.errors[0]


def test_no_usable_pages_means_no_api_call() -> None:
    client = FakeClient()
    pages = FakePages([page(SITE, text="", error="blocked by robots.txt")])
    record = agent(client, pages).research(COMPANY)
    assert record.stop == "no_pages" and client.calls == []
    assert "robots" in record.errors[0]
