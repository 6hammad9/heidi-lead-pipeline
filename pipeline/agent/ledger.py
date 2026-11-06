"""Append-only spend ledger: one JSON line per billed Anthropic API call, summed for the budget.

Each line is fsynced before record() returns, so a crash never loses spend. The total never
under-reports: a line that cannot be read stops the run instead of counting as zero.
"""

import logging
import math
import os
import threading
from pathlib import Path

from pydantic import ValidationError

from pipeline.agent.contracts import SpendEntry

log = logging.getLogger(__name__)

_SNIPPET_BYTES = 120  # of an unreadable line, quoted in the error


class CorruptLedgerError(RuntimeError):
    """A ledger line that cannot be read: total spend is unknown, so the run has to stop."""


class SpendLedger:
    """SpendRecorder on a JSON-lines file shared by all runs and models. Thread-safe.

    The total is kept in memory and topped up with only the lines appended since the last
    call, by this instance or any other process, so parallel runs still see each other's spend.
    """

    def __init__(self, path: Path) -> None:
        self.path = path
        self._lock = threading.Lock()
        self._total = 0.0
        self._bytes_counted = 0  # file prefix, whole lines only, already summed into _total
        self._lines_counted = 0

    def record(self, entry: SpendEntry) -> None:
        line = entry.model_dump_json().encode("utf-8") + b"\n"
        with self._lock:
            _append_durably(self.path, line)
        log.debug("Spend recorded: %s %s $%.6f", entry.company_id, entry.model, entry.cost_usd)

    def total_usd(self) -> float:
        """Everything spent so far, across all runs and models."""
        with self._lock:
            new = _whole_lines(_read_from(self.path, self._bytes_counted))
            entries = _parse(self.path, new, first_line=self._lines_counted + 1)
            self._total += sum(entry.cost_usd for entry in entries)
            self._bytes_counted += len(new)
            self._lines_counted += new.count(b"\n")
            return self._total

    def entries(self) -> list[SpendEntry]:
        return _parse(self.path, _whole_lines(_read_from(self.path, 0)), first_line=1)


def _append_durably(path: Path, line: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if _ends_mid_line(path):
        # A write cut off by a crash: this entry goes on a new line so it stays readable, and
        # the cut-off line is reported by the next total instead of swallowing this one.
        log.warning("%s ends in an incomplete line; appending on a new line", path)
        line = b"\n" + line
    with path.open("ab") as f:
        f.write(line)
        f.flush()
        os.fsync(f.fileno())


def _ends_mid_line(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            if f.seek(0, os.SEEK_END) == 0:
                return False
            f.seek(-1, os.SEEK_END)
            return f.read(1) != b"\n"
    except FileNotFoundError:
        return False


def _read_from(path: Path, offset: int) -> bytes:
    try:
        with path.open("rb") as f:
            f.seek(offset)
            return f.read()
    except FileNotFoundError:
        return b""  # no ledger yet: nothing spent


def _whole_lines(data: bytes) -> bytes:
    """Holds back a last line still missing its newline: another process may be writing it."""
    return data[: data.rfind(b"\n") + 1]


def _parse(path: Path, data: bytes, first_line: int) -> list[SpendEntry]:
    lines = data.split(b"\n")[:-1]  # data is whole lines, so the last split part is empty
    return [
        _parse_line(path, number, line)
        for number, line in enumerate(lines, start=first_line)
        if line.strip()
    ]


def _parse_line(path: Path, number: int, line: bytes) -> SpendEntry:
    try:
        entry = SpendEntry.model_validate_json(line)
    except ValidationError as exc:
        raise _unreadable(path, number, line, _first_error(exc)) from exc
    # The JSON parser accepts NaN and Infinity; a NaN total would pass every budget check.
    if not math.isfinite(entry.cost_usd) or entry.cost_usd < 0:
        raise _unreadable(path, number, line, f"cost_usd {entry.cost_usd} is not a valid cost")
    return entry


def _first_error(exc: ValidationError) -> str:
    error = exc.errors()[0]
    where = ".".join(str(part) for part in error["loc"])
    return f"{where}: {error['msg']}" if where else error["msg"]


def _unreadable(path: Path, number: int, line: bytes, reason: str) -> CorruptLedgerError:
    snippet = line[:_SNIPPET_BYTES].decode("utf-8", errors="replace")
    return CorruptLedgerError(
        f"Spend ledger {path}, line {number}: {reason} in {snippet!r}. Total spend is unknown, "
        "so the run stops. Repair that line by hand; deleting it would under-report spend."
    )
