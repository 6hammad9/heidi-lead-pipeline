"""Discover firms via Google Places; stored fields come later from websites (ToS: IDs only)."""

import json
import logging
import os
from collections import Counter, deque
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from pathlib import Path
from typing import NamedTuple

import requests

from pipeline import config
from pipeline.models import Company, SourceRef
from pipeline.utils.http import HttpClient, RetryableStatusError
from pipeline.utils.io import write_raw
from pipeline.utils.urls import company_id, normalize_url

log = logging.getLogger(__name__)

SOURCE = "google_places"
API_KEY_ENV = "GOOGLE_PLACES_API_KEY"
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
# On the very first request these mean a bad key/setup, so retrying cells would only burn budget.
FATAL_FIRST_REQUEST_STATUS = {400, 401, 403}
BERLIN = "Berlin"


class Cell(NamedTuple):
    south: float
    west: float
    north: float
    east: float


class CellOutcome(Enum):
    DONE = "done"
    SATURATED = "saturated"
    FAILED = "failed"
    BUDGET_EXHAUSTED = "budget_exhausted"


@dataclass
class SearchState:
    """Everything a run has paid for. Written to data/raw/ even if the run crashes."""

    max_requests: int
    requests_made: int = 0
    pages: list[dict] = field(default_factory=list)
    places: dict[str, dict] = field(default_factory=dict)
    duplicates: int = 0

    def budget_left(self) -> bool:
        return self.requests_made < self.max_requests

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
    state = SearchState(max_requests=_monthly_budget_left())
    try:
        _search_all(client, api_key, state)
    finally:
        raw_path = write_raw(config.RAW_DIR, SOURCE, _raw_payload(state))
        log.info("Google Places: %d billed requests, raw: %s", state.requests_made, raw_path)
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


def _monthly_budget_left() -> int:
    """The free quota is monthly, so requests made by earlier runs this month count too."""
    # write_raw names files <source>_<local YYYYMMDD-HHMMSS>.json
    this_month = config.RAW_DIR.glob(f"{SOURCE}_{datetime.now():%Y%m}*.json")
    used = sum(_requests_in(path) for path in this_month)
    left = max(config.GOOGLE_PLACES_MAX_REQUESTS - used, 0)
    if used:
        log.info("Google Places: %d requests made earlier this month, %d left", used, left)
    return left


def _requests_in(raw_path: Path) -> int:
    try:
        payload = json.loads(raw_path.read_text(encoding="utf-8"))
        return int(payload.get("requests_made", 0))
    except (OSError, ValueError, AttributeError, TypeError) as e:
        log.warning("Google Places: cannot read request count from %s (%s)", raw_path, e)
        return 0


# --- Search loop -----------------------------------------------------------------------


def _search_all(client: HttpClient, api_key: str, state: SearchState) -> None:
    """Adaptive quadtree, breadth-first: saturated cells are split and searched again."""
    root = bbox_cell(config.BERLIN_BBOX)
    queue = deque((query, root) for query in config.GOOGLE_PLACES_QUERIES)
    while queue:
        query, cell = queue.popleft()
        outcome = _search_cell(client, api_key, query, cell, state)
        if outcome is CellOutcome.BUDGET_EXHAUSTED:
            log.warning(
                "Google Places budget of %d requests used up: %d cell(s) left unsearched "
                "or incomplete. Results are missing for those areas.",
                state.max_requests,
                len(queue) + 1,
            )
            return
        if outcome is CellOutcome.SATURATED:
            queue.extend((query, child) for child in _children_or_warn(query, cell))


def _search_cell(
    client: HttpClient, api_key: str, query: str, cell: Cell, state: SearchState
) -> CellOutcome:
    results, token = 0, None
    for page_index in range(config.GOOGLE_PLACES_MAX_PAGES):
        if not state.budget_left():
            return CellOutcome.BUDGET_EXHAUSTED
        record = {"query": query, "cell": cell._asdict(), "page_index": page_index}
        body = build_request_body(query, cell, token)
        response = _fetch_page(client, api_key, body, record, state)
        if response is None:
            # Earlier pages said "more exist": split rather than lose the whole area.
            return CellOutcome.SATURATED if page_index > 0 else CellOutcome.FAILED
        places = response.get("places", [])
        results += len(places)
        state.add_places(places)
        token = response.get("nextPageToken") or None
        if not token:
            break
    return CellOutcome.SATURATED if is_saturated(results, token is not None) else CellOutcome.DONE


def _children_or_warn(query: str, cell: Cell) -> list[Cell]:
    if can_split(cell, config.GOOGLE_PLACES_MIN_CELL_DEGREES):
        return split_cell(cell)
    log.warning(
        "Google Places: cell %s for %r is saturated at minimum size; results may be missing there",
        tuple(round(v, 5) for v in cell),
        query,
    )
    return []


# --- HTTP ------------------------------------------------------------------------------


def _fetch_page(
    client: HttpClient, api_key: str, body: dict, record: dict, state: SearchState
) -> dict | None:
    """One billed request. Counts against the budget before sending, so the cap is never passed."""
    state.requests_made += 1
    record["request_number"] = state.requests_made
    state.pages.append(record)
    try:
        resp = client.post(
            config.GOOGLE_PLACES_TEXT_SEARCH_URL, json=body, headers=_headers(api_key)
        )
        record["response"] = resp.json()
        return record["response"]
    except requests.HTTPError as e:
        _handle_http_error(e, record, api_key, is_first=state.requests_made == 1)
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
            f"Google Places rejected the first request ({status}): {body}\n"
            "Check the API key, that 'Places API (New)' is enabled, and that billing is set up."
        ) from None
    _log_failed(record)


def _log_failed(record: dict) -> None:
    log.error(
        "Google Places request %d failed (query %r, cell %s, page %d), skipping cell: %s %s",
        record["request_number"],
        record["query"],
        tuple(round(v, 5) for v in record["cell"].values()),
        record["page_index"],
        record["error"]["status"],
        record["error"]["body"],
    )


def _headers(api_key: str) -> dict[str, str]:
    return {
        "X-Goog-Api-Key": api_key,
        "X-Goog-FieldMask": FIELD_MASK,
        "Content-Type": "application/json",
    }


def _redact(text: str, api_key: str) -> str:
    return text.replace(api_key, "***") if api_key else text


def _raw_payload(state: SearchState) -> dict:
    return {
        "requests_made": state.requests_made,
        "max_requests": state.max_requests,
        "field_mask": FIELD_MASK,
        "pages": state.pages,
    }


# --- Pure helpers ----------------------------------------------------------------------


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
