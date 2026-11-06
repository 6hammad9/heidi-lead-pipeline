"""Discover firms via Google Places; stored fields come later from websites (ToS: IDs only).

Two phases keep the bill small. Explore: an adaptive quadtree over Berlin with an IDs-only
field mask ("Text Search Essentials (IDs Only)", free) finds cells that fit in one query.
Details: only those leaf cells are searched once more with the Enterprise field mask (billed).
"""

import json
import logging
import os
from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum, StrEnum
from pathlib import Path
from types import MappingProxyType
from typing import NamedTuple

import requests

from pipeline import config
from pipeline.models import Company, SourceRef
from pipeline.utils.http import DEFAULT_RETRY_ON, HttpClient, RetryableStatusError
from pipeline.utils.io import write_raw
from pipeline.utils.urls import company_id, normalize_url

log = logging.getLogger(__name__)

SOURCE = "google_places"
API_KEY_ENV = "GOOGLE_PLACES_API_KEY"


class Phase(StrEnum):
    EXPLORE = "explore"  # free
    DETAILS = "details"  # billed


# Google bills a request at the highest SKU of any field in its mask. IDs only = free.
FREE_FIELD_MASK = "places.id,nextPageToken"
# Website and phone make every request "Text Search Enterprise"; no Atmosphere fields here.
FIELD_MASK = ",".join(
    [
        "places.id",
        "places.displayName",
        "places.formattedAddress",
        "places.addressComponents",
        "places.websiteUri",
        "places.nationalPhoneNumber",
        "places.businessStatus",
        "places.types",
        "nextPageToken",
    ]
)
# The only place a request's mask is chosen: by phase, never by the caller. Read-only, so an
# explore request cannot carry a billed field.
FIELD_MASKS: Mapping[Phase, str] = MappingProxyType(
    {Phase.EXPLORE: FREE_FIELD_MASK, Phase.DETAILS: FIELD_MASK}
)
# Billed requests are retried only when Google certainly did not bill them: an error status
# (not a "successful request") or a connect timeout (never sent). A read timeout may already be
# billed, so it is not retried.
RETRY_ON: Mapping[Phase, tuple[type[Exception], ...]] = MappingProxyType(
    {
        Phase.EXPLORE: DEFAULT_RETRY_ON,
        Phase.DETAILS: (RetryableStatusError, requests.exceptions.ConnectTimeout),
    }
)
# On a phase's first request these mean a bad key/setup, so going on would only burn budget.
FATAL_FIRST_REQUEST_STATUS = {400, 401, 403}
BERLIN = "Berlin"


class Cell(NamedTuple):
    south: float
    west: float
    north: float
    east: float


class Leaf(NamedTuple):
    """A cell exploration finished: not saturated, or saturated at minimum size."""

    query: str
    cell: Cell
    results: int
    pages: int


class CellOutcome(Enum):
    DONE = "done"
    SATURATED = "saturated"
    PARTIAL = "partial"  # a page after the first failed: more results may exist
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


class CellScan(NamedTuple):
    outcome: CellOutcome
    results: int
    pages: int


@dataclass
class Budget:
    limit: int
    used: int = 0

    def left(self) -> bool:
        return self.used < self.limit


@dataclass
class SearchState:
    """Everything a run requested. Written to data/raw/ even if the run crashes."""

    free: Budget
    billed: Budget
    dry_run: bool = False
    pages: list[dict] = field(default_factory=list)
    leaves: list[Leaf] = field(default_factory=list)
    plan: dict | None = None
    places: dict[str, dict] = field(default_factory=dict)
    duplicates: int = 0

    def budget(self, phase: Phase) -> Budget:
        return self.free if phase is Phase.EXPLORE else self.billed

    @property
    def requests_total(self) -> int:
        return self.free.used + self.billed.used

    def add_places(self, places: list[dict]) -> None:
        for place in places:
            place_id = place.get("id")
            if not place_id:
                continue
            if place_id in self.places:
                self.duplicates += 1
            else:
                self.places[place_id] = place


def collect_google_places(client: HttpClient) -> list[Company]:
    api_key = _api_key()
    state = SearchState(
        free=Budget(config.GOOGLE_PLACES_MAX_FREE_REQUESTS),
        billed=Budget(_monthly_budget_left()),
        dry_run=_dry_run(),
    )
    try:
        _run_phases(client, api_key, state)
    finally:
        raw_path = write_raw(config.RAW_DIR, SOURCE, _raw_payload(state))
        log.info(
            "Google Places: %d billed and %d free requests, raw: %s",
            state.billed.used,
            state.free.used,
            raw_path,
        )
    if state.dry_run:
        return []
    return _to_companies(state)


def _run_phases(client: HttpClient, api_key: str, state: SearchState) -> None:
    _explore(client, api_key, state)
    state.plan = details_plan(state.leaves, state.billed.limit)
    _log_plan(state.plan, state.dry_run)
    if not state.dry_run:
        _fetch_details(client, api_key, state)


def _to_companies(state: SearchState) -> list[Company]:
    kept, dropped = filter_places(list(state.places.values()))
    collected_at = datetime.now(UTC)
    companies = [place_to_company(p, collected_at) for p in kept]
    with_site = sum(1 for c in companies if c.website)
    log.info(
        "Google Places: %d companies (%d with website); dropped %d cross-cell duplicates, %s",
        len(companies),
        with_site,
        state.duplicates,
        dict(dropped) or "nothing else",
    )
    return companies


def _api_key() -> str:
    api_key = os.environ.get(API_KEY_ENV, "").strip()
    if not api_key:
        raise RuntimeError(f"{API_KEY_ENV} is not set. Add it to .env (see .env.example).")
    return api_key


def _dry_run() -> bool:
    return os.environ.get(config.GOOGLE_PLACES_DRY_RUN_ENV) == "1"


def _monthly_budget_left() -> int:
    """The free quota is monthly, so billed requests made by earlier runs this month count too."""
    # write_raw names files <source>_<local YYYYMMDD-HHMMSS>.json
    this_month = config.RAW_DIR.glob(f"{SOURCE}_{datetime.now():%Y%m}*.json")
    used = sum(_requests_in(path) for path in this_month)
    left = max(config.GOOGLE_PLACES_MAX_REQUESTS - used, 0)
    if used:
        log.info("Google Places: %d billed requests made earlier this month, %d left", used, left)
    return left


def _requests_in(raw_path: Path) -> int:
    """Billed requests only. Files from before the two phases counted Enterprise requests too."""
    try:
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        return int(payload.get("requests_made", 0))
    except (OSError, ValueError, AttributeError, TypeError) as e:
        # Fail safe: an unknown count could hide spending, so treat the whole budget as used.
        log.error(
            "Google Places: cannot read request count from %s (%s); treating this month's paid "
            "budget as used up. Inspect or move the file to continue.",
            raw_path,
            e,
        )
        return config.GOOGLE_PLACES_MAX_REQUESTS


# --- Phase A: explore (free) -----------------------------------------------------------


def _explore(client: HttpClient, api_key: str, state: SearchState) -> None:
    """Adaptive quadtree, breadth-first: saturated cells are split, the rest become leaves."""
    root = bbox_cell(config.BERLIN_BBOX)
    queue = deque((query, root) for query in config.GOOGLE_PLACES_QUERIES)
    while queue:
        query, cell = queue.popleft()
        scan = _scan_cell(client, api_key, Phase.EXPLORE, query, cell, state)
        if scan.outcome is CellOutcome.BUDGET_EXHAUSTED:
            queue.appendleft((query, cell))
            _warn_unexplored(state.free.limit, list(queue))
            return
        if scan.outcome is CellOutcome.FAILED:
            continue  # logged in _fetch_page
        children = [] if scan.outcome is CellOutcome.DONE else _children_or_warn(query, cell)
        if children:
            queue.extend((query, child) for child in children)
        else:
            state.leaves.append(Leaf(query, cell, scan.results, scan.pages))


def _children_or_warn(query: str, cell: Cell) -> list[Cell]:
    if can_split(cell, config.GOOGLE_PLACES_MIN_CELL_DEGREES):
        return split_cell(cell)
    log.warning(
        "Google Places: cell %s for %r is saturated at minimum size; results may be missing there",
        _rounded(cell),
        query,
    )
    return []


def _warn_unexplored(limit: int, cells: list[tuple[str, Cell]]) -> None:
    log.warning(
        "Google Places: free exploration budget of %d requests (GOOGLE_PLACES_MAX_FREE_REQUESTS) "
        "used up: %d cell(s) left unexplored, results are missing there: %s",
        limit,
        len(cells),
        [(query, _rounded(cell)) for query, cell in cells],
    )


def _log_plan(plan: dict, dry_run: bool) -> None:
    over_budget = plan["estimated_billed_requests"] > plan["paid_budget_left"]
    log.log(
        logging.WARNING if over_budget else logging.INFO,
        "Google Places plan: %d of %d leaf cell(s) have results, ~%d billed request(s) "
        "estimated, %d left in this month's paid budget%s%s",
        plan["leaf_cells_with_results"],
        plan["leaf_cells"],
        plan["estimated_billed_requests"],
        plan["paid_budget_left"],
        "; estimate exceeds budget, some cells will not be fetched" if over_budget else "",
        "; DRY RUN, no billed requests will be made" if dry_run else "",
    )


# --- Phase B: details (billed) ---------------------------------------------------------


def _fetch_details(client: HttpClient, api_key: str, state: SearchState) -> None:
    """Each leaf with results is searched once with the full mask, all pages, never split."""
    todo = [leaf for leaf in state.leaves if leaf.results > 0]
    for fetched, leaf in enumerate(todo):
        scan = _scan_cell(client, api_key, Phase.DETAILS, leaf.query, leaf.cell, state)
        if scan.outcome is CellOutcome.BUDGET_EXHAUSTED:
            _warn_unfetched(state.billed.limit, len(todo) - fetched, len(todo))
            return
        if scan.outcome is CellOutcome.SATURATED:
            _warn_details_saturated(leaf, scan)


def _warn_unfetched(limit: int, unfetched: int, total: int) -> None:
    log.warning(
        "Google Places: paid budget of %d billed requests left this month is used up: "
        "%d of %d leaf cell(s) with results not fetched or only partly fetched. "
        "Companies there are missing (raise GOOGLE_PLACES_MAX_REQUESTS or rerun next month).",
        limit,
        unfetched,
        total,
    )


def _warn_details_saturated(leaf: Leaf, scan: CellScan) -> None:
    # Google documents that identical requests can return different results.
    log.warning(
        "Google Places: cell %s for %r was not saturated when explored (%d results) but is now "
        "(%d results); keeping what was returned, results may be missing there",
        _rounded(leaf.cell),
        leaf.query,
        leaf.results,
        scan.results,
    )


# --- Shared cell search ----------------------------------------------------------------


def _scan_cell(
    client: HttpClient, api_key: str, phase: Phase, query: str, cell: Cell, state: SearchState
) -> CellScan:
    results, pages, token = 0, 0, None
    for page_index in range(config.GOOGLE_PLACES_MAX_PAGES):
        if not state.budget(phase).left():
            return CellScan(CellOutcome.BUDGET_EXHAUSTED, results, pages)
        record = {
            "phase": phase.value,
            "query": query,
            "cell": cell._asdict(),
            "page_index": page_index,
        }
        body = build_request_body(query, cell, token)
        response = _fetch_page(client, api_key, phase, body, record, state)
        if response is None:
            # Earlier pages said "more exist": split rather than lose the whole area.
            outcome = CellOutcome.PARTIAL if page_index > 0 else CellOutcome.FAILED
            return CellScan(outcome, results, pages)
        places = response.get("places", [])
        results, pages = results + len(places), pages + 1
        if phase is Phase.DETAILS:
            state.add_places(places)  # explore responses hold IDs only
        token = response.get("nextPageToken") or None
        if not token:
            break
    saturated = is_saturated(results, token is not None)
    return CellScan(CellOutcome.SATURATED if saturated else CellOutcome.DONE, results, pages)


# --- HTTP ------------------------------------------------------------------------------


def _fetch_page(
    client: HttpClient, api_key: str, phase: Phase, body: dict, record: dict, state: SearchState
) -> dict | None:
    """One request. Counts against its phase's budget before sending, so no cap is passed."""
    if phase is Phase.DETAILS and state.dry_run:
        raise RuntimeError("Bug: a billed Google Places request was about to be sent in a dry run")
    budget = state.budget(phase)
    budget.used += 1
    record["request_number"] = state.requests_total
    state.pages.append(record)
    try:
        resp = client.post(
            config.GOOGLE_PLACES_TEXT_SEARCH_URL,
            json=body,
            headers=_headers(api_key, phase),
            retry_on=RETRY_ON[phase],
        )
        record["response"] = resp.json()
        return record["response"]
    except requests.HTTPError as e:
        _handle_http_error(e, record, api_key, is_first=budget.used == 1)
    except RetryableStatusError as e:
        record["error"] = {"status": e.status, "body": _redact(e.body, api_key)}
        _log_failed(record)
    except (requests.RequestException, ValueError) as e:
        record["error"] = {"status": None, "body": _redact(str(e), api_key)}
        _log_failed(record)
    return None


def _handle_http_error(e: requests.HTTPError, record: dict, api_key: str, is_first: bool) -> None:
    status = e.response.status_code if e.response is not None else None
    body = _redact(e.response.text if e.response is not None else str(e), api_key)
    record["error"] = {"status": status, "body": body}
    if is_first and status in FATAL_FIRST_REQUEST_STATUS:
        raise RuntimeError(
            f"Google Places rejected the first {record['phase']} request ({status}): {body}\n"
            "Check the API key, that 'Places API (New)' is enabled, and that billing is set up."
        ) from None
    _log_failed(record)


def _log_failed(record: dict) -> None:
    log.error(
        "Google Places %s request %d failed (query %r, cell %s, page %d): %s %s",
        record["phase"],
        record["request_number"],
        record["query"],
        tuple(round(v, 5) for v in record["cell"].values()),
        record["page_index"],
        record["error"]["status"],
        record["error"]["body"],
    )


def _headers(api_key: str, phase: Phase) -> dict[str, str]:
    return {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASKS[phase],
        "Content-Type": "application/json",
    }


def _redact(text: str, api_key: str) -> str:
    return text.replace(api_key, "***") if api_key else text


def _raw_payload(state: SearchState) -> dict:
    return {
        "requests_made": state.billed.used,  # billed only: the monthly ledger sums this
        "free_requests_made": state.free.used,
        "max_requests": state.billed.limit,
        "max_free_requests": state.free.limit,
        "dry_run": state.dry_run,
        "field_masks": {phase.value: mask for phase, mask in FIELD_MASKS.items()},
        "plan": state.plan,
        "leaves": [leaf_record(leaf) for leaf in state.leaves],
        "pages": state.pages,
    }


# --- Pure helpers ----------------------------------------------------------------------


def details_plan(leaves: list[Leaf], paid_budget_left: int) -> dict:
    """Exploration saw every page a details search will request, so its pages are the estimate."""
    with_results = [leaf for leaf in leaves if leaf.results > 0]
    return {
        "leaf_cells": len(leaves),
        "leaf_cells_with_results": len(with_results),
        "estimated_billed_requests": sum(leaf.pages for leaf in with_results),
        "paid_budget_left": paid_budget_left,
    }


def leaf_record(leaf: Leaf) -> dict:
    return {
        "query": leaf.query,
        "cell": leaf.cell._asdict(),
        "results": leaf.results,
        "pages": leaf.pages,
    }


def build_request_body(query: str, cell: Cell, page_token: str | None = None) -> dict:
    """Identical for every page of a cell except pageToken, as the API requires."""
    body: dict = {
        "textQuery": query,
        "languageCode": config.GOOGLE_PLACES_LANGUAGE_CODE,
        "regionCode": config.GOOGLE_PLACES_REGION_CODE,
        "pageSize": config.GOOGLE_PLACES_PAGE_SIZE,
        "locationRestriction": {
            "rectangle": {
                "low": {"latitude": cell.south, "longitude": cell.west},
                "high": {"latitude": cell.north, "longitude": cell.east},
            }
        },
    }
    if page_token:
        body["pageToken"] = page_token
    return body


def bbox_cell(bbox: dict[str, tuple[float, float]]) -> Cell:
    (south, west), (north, east) = bbox["low"], bbox["high"]
    return Cell(south=south, west=west, north=north, east=east)


def split_cell(cell: Cell) -> list[Cell]:
    mid_lat = (cell.south + cell.north) / 2
    mid_lng = (cell.west + cell.east) / 2
    return [
        Cell(cell.south, cell.west, mid_lat, mid_lng),
        Cell(cell.south, mid_lng, mid_lat, cell.east),
        Cell(mid_lat, cell.west, cell.north, mid_lng),
        Cell(mid_lat, mid_lng, cell.north, cell.east),
    ]


def can_split(cell: Cell, min_degrees: float) -> bool:
    """Children would be half as tall and wide; never go below the minimum size."""
    return min(cell.north - cell.south, cell.east - cell.west) / 2 >= min_degrees


def is_saturated(results: int, token_left_after_last_page: bool) -> bool:
    """The API stops at MAX_PAGES x PAGE_SIZE results, so hitting that means more may exist."""
    max_results = config.GOOGLE_PLACES_PAGE_SIZE * config.GOOGLE_PLACES_MAX_PAGES
    return token_left_after_last_page or results >= max_results


def _rounded(cell: Cell) -> tuple[float, ...]:
    return tuple(round(v, 5) for v in cell)


def address_part(place: dict, component_type: str) -> str | None:
    """Match by type, not position: Google does not guarantee component order."""
    for component in place.get("addressComponents", []):
        if component_type in component.get("types", []):
            return component.get("longText") or component.get("shortText") or None
    return None


def place_city(place: dict) -> str | None:
    """Some regions name the mail town postal_town instead of locality."""
    return address_part(place, "locality") or address_part(place, "postal_town")


def drop_reason(place: dict) -> str | None:
    if not (place.get("displayName") or {}).get("text"):
        return "no_name"
    if place.get("businessStatus") == "CLOSED_PERMANENTLY":
        return "closed_permanently"
    if place_city(place) != BERLIN:
        return "outside_berlin"  # the bbox also covers Brandenburg towns
    return None


def filter_places(places: list[dict]) -> tuple[list[dict], Counter[str]]:
    kept: list[dict] = []
    dropped: Counter[str] = Counter()
    for place in places:
        if reason := drop_reason(place):
            dropped[reason] += 1
        else:
            kept.append(place)
    return kept, dropped


def place_to_company(place: dict, collected_at: datetime) -> Company:
    place_id = place["id"]
    website = normalize_url(place.get("websiteUri"))
    street = " ".join(
        filter(None, [address_part(place, "route"), address_part(place, "street_number")])
    )
    return Company(
        id=company_id(website, SOURCE, place_id),
        name=place["displayName"]["text"],
        website=website,
        phone=place.get("nationalPhoneNumber"),
        street=street or None,
        postcode=address_part(place, "postal_code"),
        city=place_city(place),
        sources=[
            SourceRef(
                source=SOURCE,
                source_id=place_id,
                url=f"https://www.google.com/maps/place/?q=place_id:{place_id}",
                collected_at=collected_at,
            )
        ],
    )
