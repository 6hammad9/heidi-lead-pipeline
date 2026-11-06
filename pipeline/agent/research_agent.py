"""The research agent: Claude reads one company's website and submits cited facts.

A manual loop rather than the SDK tool runner: it stops the moment an acceptable submit_record
arrives, instead of sending the result back for one more full-context (billed) call.
History is append-only, as Haiku/Sonnet 5.5 thinking blocks become invalid if earlier turns
change.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime

import anthropic
from pydantic import ValidationError

from pipeline import config
from pipeline.agent.contracts import PageSource, SpendEntry, SpendRecorder
from pipeline.agent.cost import cost_usd
from pipeline.agent.prompt import SYSTEM_PROMPT, build_user_message
from pipeline.agent.schema import ResearchRecord, ResearchSubmission
from pipeline.agent.tools import FETCH_PAGE, SUBMIT_RECORD, TOOLS, ToolBox
from pipeline.agent.validation import sanitize_submission
from pipeline.models import Company

log = logging.getLogger(__name__)

NUDGE = "Call submit_record now with what you found. Use null for anything the pages do not state."
NOT_RUN = "Not run: submit_record was called in the same turn."


@dataclass
class Turn:
    done: bool
    reply: list[dict]


class ResearchAgent:
    def __init__(
        self,
        client: anthropic.Anthropic,
        model: str,
        pages: PageSource,
        ledger: SpendRecorder,
        *,
        effort: str = config.AGENT_EFFORT,
        max_tokens: int = config.AGENT_MAX_TOKENS,
        max_turns: int = config.AGENT_MAX_TURNS,
        max_fetches: int = config.AGENT_MAX_FETCHES_PER_COMPANY,
        max_corrections: int = config.AGENT_MAX_SUBMIT_CORRECTIONS,
        max_cost_usd: float = config.AGENT_MAX_COST_PER_COMPANY_USD,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.client = client
        self.model = model
        self.pages = pages
        self.ledger = ledger
        self.effort = effort
        self.max_tokens = max_tokens
        self.max_turns = max_turns
        self.max_fetches = max_fetches
        self.max_corrections = max_corrections
        self.max_cost_usd = max_cost_usd
        self.today = today
        self._corrections = 0

    def research(self, company: Company) -> ResearchRecord:
        record = ResearchRecord(
            company_id=company.id,
            model=self.model,
            effort=self.effort,
            submission=None,
            stop="max_turns",
            finished_at=_now(),
        )
        fetched = self.pages.prefetch(company)
        given = [p for p in fetched if not p.error and p.text.strip()]
        if not given:
            record.stop = "no_pages"
            record.errors = [f"{p.requested_url}: {p.error or 'no text'}" for p in fetched]
            return self._finish(record, [])
        toolbox = ToolBox(self.pages, company, given, self.max_fetches)
        try:
            self._loop(company, toolbox, record)
        except anthropic.APIError as e:
            record.stop = "error"
            record.errors.append(f"{type(e).__name__}: {e}")
        return self._finish(record, [p.url for p in toolbox.pages])

    def _loop(self, company: Company, toolbox: ToolBox, record: ResearchRecord) -> None:
        text = build_user_message(company, toolbox.pages, self.today())
        messages: list[dict] = [{"role": "user", "content": [{"type": "text", "text": text}]}]
        self._corrections = 0
        for _ in range(self.max_turns):
            response = self._call(messages)
            self._account(company.id, response, record)
            if response.stop_reason == "refusal":
                record.stop = "refusal"
                return
            messages.append({"role": "assistant", "content": response.content})
            turn = self._handle(response, toolbox, record)
            if turn.done:
                return
            if record.cost_usd >= self.max_cost_usd:
                record.stop = "cost_cap"
                return
            messages.append({"role": "user", "content": turn.reply})
        record.stop = "max_turns"

    def _call(self, messages: list[dict]):  # -> anthropic.types.Message
        return self.client.messages.create(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[
                {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
            ],
            tools=TOOLS,
            messages=messages,
            cache_control={"type": "ephemeral"},  # automatic breakpoint on the growing tail
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort},
        )

    def _account(self, company_id: str, response, record: ResearchRecord) -> None:
        """First thing after every response: each billed call reaches the ledger."""
        usage = response.usage
        cost = cost_usd(usage, self.model)
        entry = SpendEntry(
            at=_now(),
            model=self.model,
            company_id=company_id,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_creation_tokens=usage.cache_creation_input_tokens or 0,
            cache_read_tokens=usage.cache_read_input_tokens or 0,
            cost_usd=cost,
            request_id=getattr(response, "_request_id", None),
        )
        self.ledger.record(entry)
        record.turns += 1
        record.input_tokens += entry.input_tokens
        record.output_tokens += entry.output_tokens
        record.cache_creation_tokens += entry.cache_creation_tokens
        record.cache_read_tokens += entry.cache_read_tokens
        record.cost_usd += cost

    def _handle(self, response, toolbox: ToolBox, record: ResearchRecord) -> Turn:
        tool_uses = [b for b in response.content if b.type == "tool_use"]
        submit = next((b for b in tool_uses if b.name == SUBMIT_RECORD), None)
        if submit is not None:
            return self._handle_submit(submit, tool_uses, toolbox, record)
        if tool_uses:
            return Turn(False, [_run_tool(block, toolbox) for block in tool_uses])
        return Turn(False, [{"type": "text", "text": NUDGE}])

    def _handle_submit(self, submit, tool_uses, toolbox: ToolBox, record: ResearchRecord) -> Turn:
        submission, problems = _check(submit.input, toolbox.seen_urls)
        if not problems:
            record.submission, record.stop = submission, "submitted"
            return Turn(True, [])
        if self._corrections < self.max_corrections:
            self._corrections += 1
            feedback = "Fix these problems and call submit_record again:\n- " + "\n- ".join(
                problems
            )
            reply = [
                _result(b.id, feedback, True) if b is submit else _result(b.id, NOT_RUN, True)
                for b in tool_uses
            ]
            return Turn(False, reply)
        record.errors.extend(problems)
        record.submission = submission
        record.stop = "submitted_sanitized" if submission else "invalid_submission"
        return Turn(True, [])

    def _finish(self, record: ResearchRecord, page_urls: list[str]) -> ResearchRecord:
        record.page_urls = page_urls
        record.finished_at = _now()
        log.info(
            "%s: %s after %d call(s), %d page(s), $%.4f",
            record.company_id,
            record.stop,
            record.turns,
            len(page_urls),
            record.cost_usd,
        )
        return record


def _check(raw: object, seen_urls: set[str]) -> tuple[ResearchSubmission | None, list[str]]:
    try:
        submission = ResearchSubmission.model_validate(raw)
    except ValidationError as e:
        return None, [f"{'.'.join(map(str, err['loc']))}: {err['msg']}" for err in e.errors()[:5]]
    return sanitize_submission(submission, seen_urls)


def _run_tool(block, toolbox: ToolBox) -> dict:
    if block.name == FETCH_PAGE:
        content, is_error = toolbox.fetch_page(str(block.input.get("url", "")))
    else:
        content, is_error = f"Unknown tool {block.name}", True
    return _result(block.id, content, is_error)


def _result(tool_use_id: str, content: str, is_error: bool) -> dict:
    return {
        "type": "tool_result",
        "tool_use_id": tool_use_id,
        "content": content,
        "is_error": is_error,
    }


def _now() -> datetime:
    return datetime.now(UTC)
