import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

from pipeline import config
from pipeline.collectors import google_places as gp
from pipeline.collectors.google_places import Cell, Leaf
from pipeline.utils.http import RetryableStatusError

FAKE_KEY = "TEST-KEY-not-real-123"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
ROOT = gp.bbox_cell(config.BERLIN_BBOX)
FREE_MASK = "places.id,nextPageToken"  # spelled out: the free SKU depends on this exact mask
EXPLORE, DETAILS = "explore", "details"
PHASE_BY_MASK = {FREE_MASK: EXPLORE, gp.FIELD_MASK: DETAILS}

Responder = Callable[[dict, int], dict | Exception]


def make_place(place_id: str, locality: str = "Berlin", **extra: object) -> dict:
    return {
        "id": place_id,
        "displayName": {"text": f"HV {place_id}", "languageCode": "de"},
        "addressComponents": [
            {"longText": "12", "shortText": "12", "types": ["street_number"]},
            {"longText": "Musterstraße", "shortText": "Musterstr.", "types": ["route"]},
            {"longText": locality, "shortText": locality, "types": ["locality", "political"]},
            {"longText": "10115", "shortText": "10115", "types": ["postal_code"]},
        ],
        "businessStatus": "OPERATIONAL",
        **extra,
    }


def apply_mask(payload: dict, mask: str) -> dict:
    """Google returns only the fields named in the mask."""
    fields = mask.split(",")
    place_fields = {f.removeprefix("places.") for f in fields if f.startswith("places.")}
    masked = {k: v for k, v in payload.items() if k != "places" and k in fields}
    if "places" in payload:
        masked["places"] = [
            {k: v for k, v in place.items() if k in place_fields} for place in payload["places"]
        ]
    return masked


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload


class FakeClient:
    """Stands in for HttpClient; never touches the network.

    Each phase has its own responder(body, call_number_within_phase) returning a payload or an
    exception. Any field mask other than the two known ones fails the test.
    """

    def __init__(self, explore: Responder, details: Responder | None = None) -> None:
        self.responders = {EXPLORE: explore, DETAILS: details or explore}
        self.calls: list[dict] = []

    def post(
        self,
        url: str,
        json: dict,
        headers: dict,
        retry_on: tuple[type[Exception], ...] = (),
    ) -> FakeResponse:
        mask = headers["X-Goog-FieldMask"]
        assert mask in PHASE_BY_MASK, f"unexpected field mask {mask!r}"
        phase = PHASE_BY_MASK[mask]
        self.calls.append(
            {"url": url, "json": json, "headers": headers, "phase": phase, "retry_on": retry_on}
        )
        result = self.responders[phase](json, len(self.phase_calls(phase)))
        if isinstance(result, Exception):
            raise result
        return FakeResponse(apply_mask(result, mask))

    def phase_calls(self, phase: str) -> list[dict]:
        return [c for c in self.calls if c["phase"] == phase]


def http_error(status: int, body: str) -> requests.HTTPError:
    resp = requests.Response()
    resp.status_code = status
    resp._content = body.encode()
    return requests.HTTPError(f"{status} error", response=resp)


def full_page(prefix: str, token: str | None) -> dict:
    page: dict = {"places": [make_place(f"{prefix}-{i}") for i in range(20)]}
    if token:
        page["nextPageToken"] = token
    return page


def cell_of(body: dict) -> Cell:
    rect = body["locationRestriction"]["rectangle"]
    low, high = rect["low"], rect["high"]
    return Cell(low["latitude"], low["longitude"], high["latitude"], high["longitude"])


def points_in(cell: Cell, count: int, prefix: str) -> dict[str, tuple[float, float]]:
    """Points on the cell's diagonal, strictly inside it."""
    step_lat = (cell.north - cell.south) / (count + 1)
    step_lng = (cell.east - cell.west) / (count + 1)
    return {
        f"{prefix}{i}": (cell.south + (i + 1) * step_lat, cell.west + (i + 1) * step_lng)
        for i in range(count)
    }


def world(points: dict[str, tuple[float, float]]) -> Responder:
    """Answers like Google: places inside the rectangle, 20 per page, at most 60."""

    def respond(body: dict, n: int) -> dict:
        cell = cell_of(body)
        inside = sorted(
            place_id
            for place_id, (lat, lng) in points.items()
            if cell.south <= lat < cell.north and cell.west <= lng < cell.east
        )
        start = int(body.get("pageToken", 0))
        end = start + config.GOOGLE_PLACES_PAGE_SIZE
        page: dict = {"places": [make_place(place_id) for place_id in inside[start:end]]}
        if end < min(len(inside), 60):
            page["nextPageToken"] = str(end)
        return page

    return respond


# Root holds 75 places (saturated). Children: SW 70 (saturated), SE 0, NW 0, NE 5.
# SW's children: 30 (2 pages), 20 (1 page), 20 (1 page), 0.
SW, SE, NW, NE = gp.split_cell(ROOT)
G0, G1, G2, G3 = gp.split_cell(SW)
WORLD_POINTS = {
    **points_in(G0, 30, "g0-"),
    **points_in(G1, 20, "g1-"),
    **points_in(G2, 20, "g2-"),
    **points_in(NE, 5, "ne-"),
}
WORLD_EXPLORE_CALLS = 3 + 3 + 1 + 1 + 1 + 2 + 1 + 1 + 1  # root, SW, SE, NW, NE, G0-G3
WORLD_DETAILS_CALLS = 1 + 2 + 1 + 1  # NE, G0, G1, G2 (BFS order)
WORLD_PLAN = {
    "leaf_cells": 7,
    "leaf_cells_with_results": 4,
    "estimated_billed_requests": WORLD_DETAILS_CALLS,
    "paid_budget_left": config.GOOGLE_PLACES_MAX_REQUESTS,
}


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(gp.API_KEY_ENV, FAKE_KEY)
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(config, "GOOGLE_PLACES_QUERIES", ["Hausverwaltung"])
    monkeypatch.delenv(config.GOOGLE_PLACES_DRY_RUN_ENV, raising=False)  # a shell value leaks in
    monkeypatch.setattr(config, "GOOGLE_PLACES_MAX_FREE_REQUESTS", 3000)


def raw_files() -> list[Path]:
    return sorted(config.RAW_DIR.glob("google_places_*.json"))


def raw_payload() -> dict:
    (path,) = raw_files()
    return json.loads(path.read_text(encoding="utf-8"))


def write_earlier_run(month: str, **payload: int) -> None:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    # Day "00" never collides with the file this run writes.
    path = config.RAW_DIR / f"google_places_{month}00-0000{len(raw_files()):02d}.json"
    path.write_text(json.dumps(payload), encoding="utf-8")


def this_month() -> str:
    return f"{datetime.now():%Y%m}"


def assert_masks_match_phases(client: FakeClient) -> None:
    """Every explore request carries exactly the free mask, every details request the full one,
    and the collector's own phase tag in the raw file agrees with the mask it sent."""
    explore = client.phase_calls(EXPLORE)
    details = client.phase_calls(DETAILS)
    assert all(c["headers"]["X-Goog-FieldMask"] == FREE_MASK for c in explore)
    assert all(c["headers"]["X-Goog-FieldMask"] == gp.FIELD_MASK for c in details)
    assert client.calls == explore + details  # details only start after exploration
    assert [p["phase"] for p in raw_payload()["pages"]] == [c["phase"] for c in client.calls]


# --- Cells -----------------------------------------------------------------------------


def test_split_covers_parent_exactly() -> None:
    children = gp.split_cell(ROOT)
    assert len(children) == 4
    assert min(c.south for c in children) == ROOT.south
    assert min(c.west for c in children) == ROOT.west
    assert max(c.north for c in children) == ROOT.north
    assert max(c.east for c in children) == ROOT.east
    area = sum((c.north - c.south) * (c.east - c.west) for c in children)
    assert area == pytest.approx((ROOT.north - ROOT.south) * (ROOT.east - ROOT.west))
    assert len(set(children)) == 4  # four distinct quadrants, no overlap


def test_can_split_stops_at_min_size() -> None:
    assert gp.can_split(Cell(52.0, 13.0, 52.02, 13.02), 0.005)
    assert gp.can_split(Cell(52.0, 13.0, 52.011, 13.011), 0.005)
    assert not gp.can_split(Cell(52.0, 13.0, 52.009, 13.5), 0.005)


@pytest.mark.parametrize(
    ("results", "token_left", "expected"),
    [
        (60, False, True),
        (40, True, True),
        (59, False, False),
        (20, False, False),
        (0, False, False),
    ],
)
def test_is_saturated(results: int, token_left: bool, expected: bool) -> None:
    assert gp.is_saturated(results, token_left) is expected


def test_request_body_pages_differ_only_by_token() -> None:
    first = gp.build_request_body("Hausverwaltung", ROOT)
    second = gp.build_request_body("Hausverwaltung", ROOT, "tok")
    assert second.pop("pageToken") == "tok"
    assert first == second
    assert first["locationRestriction"]["rectangle"]["low"] == {
        "latitude": ROOT.south,
        "longitude": ROOT.west,
    }
    assert first["pageSize"] == 20


# --- Field masks -----------------------------------------------------------------------


def test_field_mask_is_chosen_by_phase_only() -> None:
    assert gp.FREE_FIELD_MASK == FREE_MASK
    assert gp._headers(FAKE_KEY, gp.Phase.EXPLORE)["X-Goog-FieldMask"] == FREE_MASK
    assert gp._headers(FAKE_KEY, gp.Phase.DETAILS)["X-Goog-FieldMask"] == gp.FIELD_MASK
    assert set(gp.FIELD_MASKS) == set(gp.Phase)
    with pytest.raises(TypeError):
        gp.FIELD_MASKS[gp.Phase.EXPLORE] = gp.FIELD_MASK  # type: ignore[index]


def test_details_plan_counts_only_leaves_with_results() -> None:
    leaves = [Leaf("q", ROOT, 0, 1), Leaf("q", SW, 45, 3), Leaf("q", NE, 5, 1)]
    assert gp.details_plan(leaves, 2) == {
        "leaf_cells": 3,
        "leaf_cells_with_results": 2,
        "estimated_billed_requests": 4,
        "paid_budget_left": 2,
    }


# --- Two phases ------------------------------------------------------------------------


def test_explore_free_then_details_only_on_leaves_with_results() -> None:
    client = FakeClient(world(WORLD_POINTS))
    companies = gp.collect_google_places(client)

    assert len(client.phase_calls(EXPLORE)) == WORLD_EXPLORE_CALLS
    assert len(client.phase_calls(DETAILS)) == WORLD_DETAILS_CALLS
    assert_masks_match_phases(client)
    explored = [cell_of(c["json"]) for c in client.phase_calls(EXPLORE)]
    assert explored.count(ROOT) == 3 and explored.count(SW) == 3  # saturated cells split
    detailed = [cell_of(c["json"]) for c in client.phase_calls(DETAILS)]
    assert detailed == [NE, G0, G0, G1, G2]  # leaves only; empty SE, NW, G3 never billed
    assert len(companies) == len(WORLD_POINTS)


def test_raw_counts_billed_and_free_requests_separately() -> None:
    client = FakeClient(world(WORLD_POINTS))
    gp.collect_google_places(client)
    payload = raw_payload()
    assert payload["requests_made"] == len(client.phase_calls(DETAILS)) == WORLD_DETAILS_CALLS
    assert payload["free_requests_made"] == len(client.phase_calls(EXPLORE))
    assert payload["field_masks"] == {EXPLORE: FREE_MASK, DETAILS: gp.FIELD_MASK}
    assert payload["plan"] == WORLD_PLAN
    assert payload["dry_run"] is False
    assert {"query": "Hausverwaltung", "cell": NE._asdict(), "results": 5, "pages": 1} in (
        payload["leaves"]
    )
    explore_page = payload["pages"][0]
    assert explore_page["phase"] == EXPLORE
    assert explore_page["response"]["places"][0] == {"id": "g0-0"}  # IDs only


def test_empty_leaves_cause_no_details_requests() -> None:
    client = FakeClient(lambda body, n: {})
    assert gp.collect_google_places(client) == []
    assert len(client.phase_calls(EXPLORE)) == 1
    assert client.phase_calls(DETAILS) == []
    assert raw_payload()["plan"]["leaf_cells"] == 1


def test_dry_run_explores_and_plans_but_bills_nothing(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv(config.GOOGLE_PLACES_DRY_RUN_ENV, "1")
    client = FakeClient(world(WORLD_POINTS))
    with caplog.at_level(logging.INFO):
        assert gp.collect_google_places(client) == []
    assert len(client.phase_calls(EXPLORE)) == WORLD_EXPLORE_CALLS
    assert client.phase_calls(DETAILS) == []
    payload = raw_payload()
    assert payload["dry_run"] is True
    assert payload["requests_made"] == 0
    assert payload["free_requests_made"] == WORLD_EXPLORE_CALLS
    assert payload["plan"] == WORLD_PLAN
    assert "DRY RUN" in caplog.text
    assert f"~{WORLD_DETAILS_CALLS} billed request(s)" in caplog.text


def test_dry_run_set_after_config_import_still_bills_nothing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # main.py imports config before load_dotenv(): a flag from .env only reaches os.environ.
    monkeypatch.setenv(config.GOOGLE_PLACES_DRY_RUN_ENV, "1")
    client = FakeClient(world(WORLD_POINTS))
    assert gp.collect_google_places(client) == []
    assert client.phase_calls(DETAILS) == []
    assert raw_payload()["dry_run"] is True


def test_pagination_follows_token_and_stops_in_both_phases() -> None:
    pages = {1: full_page("a", "t1"), 2: {"places": [make_place("b")]}}
    client = FakeClient(lambda body, n: pages[n])
    companies = gp.collect_google_places(client)
    for phase in (EXPLORE, DETAILS):
        calls = client.phase_calls(phase)
        assert len(calls) == 2
        assert "pageToken" not in calls[0]["json"]
        assert calls[1]["json"]["pageToken"] == "t1"
    assert len(companies) == 21
    assert_masks_match_phases(client)


def test_saturated_cell_is_split_and_duplicates_kept_once() -> None:
    def explore(body: dict, n: int) -> dict:
        if n <= 3:  # root: 3 full pages with a token left -> saturated
            return full_page(f"root{n}", "more")
        return {"places": [make_place(f"child{n}")]}

    def details(body: dict, n: int) -> dict:
        return {"places": [make_place("dup"), make_place(f"child{n}")]}

    client = FakeClient(explore, details)
    companies = gp.collect_google_places(client)
    assert len(client.phase_calls(EXPLORE)) == 3 + 4
    assert [cell_of(c["json"]) for c in client.phase_calls(DETAILS)] == gp.split_cell(ROOT)
    ids = [c.sources[0].source_id for c in companies]
    assert ids.count("dup") == 1
    assert len(ids) == 1 + 4  # the saturated root is never fetched with the billed mask
    assert raw_payload()["requests_made"] == 4


def test_min_size_cell_not_split_and_warned(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(config, "BERLIN_BBOX", {"low": (52.5, 13.4), "high": (52.509, 13.409)})
    client = FakeClient(lambda body, n: full_page(f"p{n}", "more"))
    with caplog.at_level(logging.WARNING):
        companies = gp.collect_google_places(client)
    assert len(client.phase_calls(EXPLORE)) == 3
    assert len(client.phase_calls(DETAILS)) == 3  # still a leaf: fetch what Google returns
    assert len(companies) == 60
    assert "minimum size" in caplog.text


def test_details_saturation_is_warned_not_split(caplog: pytest.LogCaptureFixture) -> None:
    def explore(body: dict, n: int) -> dict:
        return {"places": [make_place(f"e{i}") for i in range(10)]}

    client = FakeClient(explore, lambda body, n: full_page(f"d{n}", "more"))
    with caplog.at_level(logging.WARNING):
        companies = gp.collect_google_places(client)
    assert len(client.phase_calls(EXPLORE)) == 1
    assert [cell_of(c["json"]) for c in client.phase_calls(DETAILS)] == [ROOT] * 3
    assert len(companies) == 60
    assert "not saturated when explored (10 results) but is now (60 results)" in caplog.text


# --- Budgets ---------------------------------------------------------------------------


def test_free_budget_guard_stops_exploration_and_logs(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(config, "GOOGLE_PLACES_MAX_FREE_REQUESTS", 7)
    client = FakeClient(lambda body, n: full_page(f"p{n}", "more"))  # always saturated
    with caplog.at_level(logging.WARNING):
        gp.collect_google_places(client)
    assert len(client.phase_calls(EXPLORE)) == 7
    # root (3) + child 1 (3, split again) + child 2 page 1 = 7 requests.
    # Left: child 2 (incomplete), children 3-4, child 1's four sub-cells = 7 cells.
    assert "7 cell(s) left unexplored" in caplog.text
    assert client.phase_calls(DETAILS) == []  # nothing finished, so nothing to fetch
    payload = raw_payload()
    assert (payload["free_requests_made"], payload["requests_made"]) == (7, 0)


@pytest.mark.parametrize(
    ("budget_left", "details_calls", "unfetched"),
    [
        (3, 3, 2),  # NE (1) + G0 (2); G1, G2 not fetched
        (2, 2, 3),  # NE + G0 page 1: G0 only partly fetched
        (0, 0, 4),
    ],
)
def test_paid_budget_never_exceeded_counting_earlier_runs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    budget_left: int,
    details_calls: int,
    unfetched: int,
) -> None:
    monkeypatch.setattr(config, "GOOGLE_PLACES_MAX_REQUESTS", 7 + budget_left)
    last_month = (datetime.now().replace(day=1) - timedelta(days=1)).strftime("%Y%m")
    write_earlier_run(this_month(), requests_made=7, free_requests_made=999)
    write_earlier_run(last_month, requests_made=9)
    client = FakeClient(world(WORLD_POINTS))
    with caplog.at_level(logging.WARNING):
        gp.collect_google_places(client)
    assert len(client.phase_calls(EXPLORE)) == WORLD_EXPLORE_CALLS  # free, unaffected
    assert len(client.phase_calls(DETAILS)) == details_calls
    assert "estimate exceeds budget" in caplog.text
    assert f"{unfetched} of 4 leaf cell(s) with results not fetched" in caplog.text
    new_raw = json.loads(raw_files()[-1].read_text(encoding="utf-8"))
    assert new_raw["requests_made"] == details_calls


def test_paid_budget_used_up_makes_no_billed_requests(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(config, "GOOGLE_PLACES_MAX_REQUESTS", 5)
    write_earlier_run(this_month(), requests_made=5)
    client = FakeClient(lambda body, n: full_page(f"p{n}", None))
    with caplog.at_level(logging.WARNING):
        assert gp.collect_google_places(client) == []
    assert client.phase_calls(DETAILS) == []
    assert "1 of 1 leaf cell(s) with results not fetched" in caplog.text


def test_ledger_counts_only_billed_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "GOOGLE_PLACES_MAX_REQUESTS", 100)
    write_earlier_run(this_month(), requests_made=10, free_requests_made=2500)
    write_earlier_run(this_month(), requests_made=30)  # written before the two-phase flow
    assert gp._monthly_budget_left() == 60


# --- Failures --------------------------------------------------------------------------


def test_failed_request_is_logged_and_run_continues(caplog: pytest.LogCaptureFixture) -> None:
    def explore(body: dict, n: int) -> dict | Exception:
        if n <= 3:
            return full_page(f"root{n}", "more")
        if n == 4:
            return http_error(500, '{"error": {"message": "backend boom"}}')
        return {"places": [make_place(f"child{n}")]}

    client = FakeClient(explore, lambda body, n: {"places": [make_place(f"d{n}")]})
    with caplog.at_level(logging.ERROR):
        companies = gp.collect_google_places(client)
    assert len(client.phase_calls(EXPLORE)) == 7
    assert len(client.phase_calls(DETAILS)) == 3  # the failed child is not a leaf
    assert len(companies) == 3
    assert "backend boom" in caplog.text


def test_failed_details_request_is_logged_and_run_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def explore(body: dict, n: int) -> dict:
        return full_page(f"root{n}", "more") if n <= 3 else {"places": [make_place(f"c{n}")]}

    def details(body: dict, n: int) -> dict | Exception:
        if n == 1:
            return http_error(500, '{"error": {"message": "details boom"}}')
        return {"places": [make_place(f"d{n}")]}

    client = FakeClient(explore, details)
    with caplog.at_level(logging.ERROR):
        companies = gp.collect_google_places(client)
    assert len(client.phase_calls(DETAILS)) == 4
    assert len(companies) == 3
    assert "details request" in caplog.text and "details boom" in caplog.text


@pytest.mark.parametrize("phase", [EXPLORE, DETAILS])
def test_retryable_status_error_is_logged_and_run_continues(
    caplog: pytest.LogCaptureFixture, phase: str
) -> None:
    # The real HttpClient turns 429/5xx into RetryableStatusError, not HTTPError.
    def explore(body: dict, n: int) -> dict | Exception:
        if n <= 3:
            return full_page(f"root{n}", "more")
        if n == 4 and phase == EXPLORE:
            return RetryableStatusError(503, "backend unavailable", "https://places.googleapis.com")
        return {"places": [make_place(f"child{n}")]}

    def details(body: dict, n: int) -> dict | Exception:
        if n == 1 and phase == DETAILS:
            return RetryableStatusError(503, "backend unavailable", "https://places.googleapis.com")
        return {"places": [make_place(f"d{n}")]}

    with caplog.at_level(logging.ERROR):
        companies = gp.collect_google_places(FakeClient(explore, details))
    assert len(companies) == 3
    assert "503 backend unavailable" in caplog.text


def test_failure_after_first_page_splits_cell_instead_of_losing_it() -> None:
    # Page 1 said "more results exist"; page 2 failing must not drop the whole area.
    def explore(body: dict, n: int) -> dict | Exception:
        if n == 1:
            return full_page("root", "t1")
        if n == 2:
            return http_error(400, '{"error": {"status": "INVALID_ARGUMENT"}}')
        return {"places": [make_place(f"child{n}")]}

    client = FakeClient(explore, lambda body, n: {"places": [make_place(f"d{n}")]})
    companies = gp.collect_google_places(client)
    assert len(client.phase_calls(EXPLORE)) == 2 + 4
    assert [cell_of(c["json"]) for c in client.phase_calls(DETAILS)] == gp.split_cell(ROOT)
    assert len(companies) == 4


@pytest.mark.parametrize("status", [400, 401, 403])
def test_first_request_auth_error_aborts(status: int) -> None:
    client = FakeClient(lambda body, n: http_error(status, '{"error": {"status": "DENIED"}}'))
    with pytest.raises(RuntimeError, match=str(status)):
        gp.collect_google_places(client)
    assert len(client.calls) == 1
    assert len(raw_files()) == 1


def test_first_details_request_auth_error_aborts() -> None:
    client = FakeClient(
        lambda body, n: {"places": [make_place("a")]},
        lambda body, n: http_error(403, '{"error": {"status": "PERMISSION_DENIED"}}'),
    )
    with pytest.raises(RuntimeError, match="first details request \\(403\\)"):
        gp.collect_google_places(client)
    assert len(client.phase_calls(DETAILS)) == 1
    payload = raw_payload()
    assert (payload["free_requests_made"], payload["requests_made"]) == (1, 1)


def test_missing_api_key_is_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(gp.API_KEY_ENV)
    client = FakeClient(lambda body, n: {})
    with pytest.raises(RuntimeError, match=gp.API_KEY_ENV):
        gp.collect_google_places(client)
    assert client.calls == []


# --- Raw data --------------------------------------------------------------------------


def test_raw_written_when_explore_request_crashes() -> None:
    def respond(body: dict, n: int) -> dict | Exception:
        return full_page("a", "t1") if n == 1 else KeyError("unexpected crash")

    with pytest.raises(KeyError):
        gp.collect_google_places(FakeClient(respond))
    payload = raw_payload()
    assert (payload["free_requests_made"], payload["requests_made"]) == (2, 0)
    first = payload["pages"][0]
    assert first["phase"] == EXPLORE
    assert first["query"] == "Hausverwaltung"
    assert first["page_index"] == 0
    assert first["cell"] == ROOT._asdict()
    assert len(first["response"]["places"]) == 20


def test_raw_written_when_details_request_crashes() -> None:
    client = FakeClient(
        lambda body, n: {"places": [make_place("a")]},
        lambda body, n: KeyError("unexpected crash"),
    )
    with pytest.raises(KeyError):
        gp.collect_google_places(client)
    payload = raw_payload()
    assert (payload["free_requests_made"], payload["requests_made"]) == (1, 1)
    assert payload["plan"]["estimated_billed_requests"] == 1
    assert [p["phase"] for p in payload["pages"]] == [EXPLORE, DETAILS]


def test_api_key_absent_from_raw_payload() -> None:
    echo = http_error(500, f'{{"error": "echoed key {FAKE_KEY}"}}')

    def explore(body: dict, n: int) -> dict | Exception:
        if n == 1:
            return full_page("a", "t1")
        return echo if n == 2 else {"places": [make_place(f"c{n}")]}

    gp.collect_google_places(FakeClient(explore, lambda body, n: echo))
    text = raw_files()[0].read_text(encoding="utf-8")
    assert FAKE_KEY not in text
    assert text.count("echoed key ***") == 1 + 4  # explore page 2 + four details requests


# --- Filtering and mapping -------------------------------------------------------------


def test_non_berlin_closed_and_nameless_places_dropped() -> None:
    places = [
        make_place("ok"),
        make_place("potsdam", locality="Potsdam"),
        make_place("closed", businessStatus="CLOSED_PERMANENTLY"),
        make_place("temp", businessStatus="CLOSED_TEMPORARILY"),
        {"id": "noname", "addressComponents": []},
        {"id": "noaddr", "displayName": {"text": "HV ohne Adresse"}},
    ]
    kept, dropped = gp.filter_places(places)
    assert [p["id"] for p in kept] == ["ok", "temp"]
    assert dropped == {"outside_berlin": 2, "closed_permanently": 1, "no_name": 1}


def test_closed_and_non_berlin_dropped_end_to_end() -> None:
    def respond(body: dict, n: int) -> dict:
        return {
            "places": [
                make_place("ok"),
                make_place("closed", businessStatus="CLOSED_PERMANENTLY"),
                make_place("potsdam", locality="Potsdam"),
            ]
        }

    companies = gp.collect_google_places(FakeClient(respond))
    assert [c.sources[0].source_id for c in companies] == ["ok"]


def test_berlin_filter_matches_city_mapping_fallbacks() -> None:
    # place_to_company falls back to postal_town; the filter must not drop those first.
    postal_town = {
        "id": "pt",
        "displayName": {"text": "HV PT"},
        "addressComponents": [{"longText": "Berlin", "types": ["postal_town"]}],
    }
    short_only = {
        "id": "short",
        "displayName": {"text": "HV Short"},
        "addressComponents": [{"shortText": "Berlin", "types": ["locality", "political"]}],
    }
    kept, dropped = gp.filter_places([postal_town, short_only])
    assert [p["id"] for p in kept] == ["pt", "short"]
    assert not dropped
    assert gp.place_to_company(short_only, NOW).city == "Berlin"


def test_place_to_company_maps_fields() -> None:
    place = make_place(
        "ChIJabc",
        websiteUri="https://www.hv-mueller.de/kontakt/",
        nationalPhoneNumber="030 1234567",
    )
    company = gp.place_to_company(place, NOW)
    assert company.id == "hv-mueller.de"
    assert company.name == "HV ChIJabc"
    assert company.website == "https://hv-mueller.de/kontakt"
    assert company.phone == "030 1234567"
    assert company.street == "Musterstraße 12"
    assert company.postcode == "10115"
    assert company.city == "Berlin"
    source = company.sources[0]
    assert source.source == "google_places"
    assert source.source_id == "ChIJabc"
    assert source.url == "https://www.google.com/maps/place/?q=place_id:ChIJabc"
    assert source.collected_at == NOW


def test_platform_website_gets_source_scoped_id() -> None:
    place = make_place("ChIJxyz", websiteUri="https://www.facebook.com/hvmueller")
    company = gp.place_to_company(place, NOW)
    assert company.id == "google_places:ChIJxyz"
    assert company.website == "https://facebook.com/hvmueller"


def test_place_without_website_or_address_details() -> None:
    place = {"id": "p1", "displayName": {"text": "HV"}, "addressComponents": []}
    company = gp.place_to_company(place, NOW)
    assert company.id == "google_places:p1"
    assert (company.website, company.street, company.postcode, company.city) == (None,) * 4


def test_corrupt_raw_file_this_month_blocks_all_billed_requests(
    caplog: pytest.LogCaptureFixture,
) -> None:
    config.RAW_DIR.mkdir(parents=True, exist_ok=True)
    (config.RAW_DIR / f"google_places_{this_month()}00-000000.json").write_text(
        "{not json", encoding="utf-8"
    )
    client = FakeClient(world(WORLD_POINTS))
    with caplog.at_level(logging.ERROR):
        assert gp.collect_google_places(client) == []
    assert client.phase_calls(DETAILS) == []
    assert "treating this month's paid budget as used up" in caplog.text


def test_billed_requests_never_retry_errors_google_may_have_billed() -> None:
    client = FakeClient(world(WORLD_POINTS))
    gp.collect_google_places(client)
    details_retry_on = {c["retry_on"] for c in client.phase_calls(DETAILS)}
    (retry_on,) = details_retry_on
    assert any(issubclass(RetryableStatusError, t) for t in retry_on)
    # A read timeout or dropped connection may come after Google processed (and billed) it.
    assert not any(issubclass(requests.exceptions.ReadTimeout, t) for t in retry_on)
    assert not any(issubclass(requests.exceptions.ConnectionError, t) for t in retry_on)
    # A connect timeout means the request was never sent: safe to retry.
    assert any(issubclass(requests.exceptions.ConnectTimeout, t) for t in retry_on)


def test_free_requests_keep_default_retries() -> None:
    client = FakeClient(world(WORLD_POINTS))
    gp.collect_google_places(client)
    assert {c["retry_on"] for c in client.phase_calls(EXPLORE)} == {gp.DEFAULT_RETRY_ON}


def test_dry_run_guard_refuses_a_billed_request_even_if_called_directly() -> None:
    state = gp.SearchState(free=gp.Budget(10), billed=gp.Budget(10), dry_run=True)
    client = FakeClient(world(WORLD_POINTS))
    record = {"phase": DETAILS, "query": "q", "cell": ROOT._asdict(), "page_index": 0}
    with pytest.raises(RuntimeError, match="dry run"):
        gp._fetch_page(
            client,
            FAKE_KEY,
            gp.Phase.DETAILS,
            gp.build_request_body("q", ROOT),
            record,
            state,
        )
    assert client.calls == []
    assert state.billed.used == 0
