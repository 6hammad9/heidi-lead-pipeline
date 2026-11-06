import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import requests

from pipeline import config
from pipeline.collectors import google_places as gp
from pipeline.collectors.google_places import Cell
from pipeline.utils.http import RetryableStatusError

FAKE_KEY = "TEST-KEY-not-real-123"
NOW = datetime(2026, 1, 1, tzinfo=UTC)
ROOT = gp.bbox_cell(config.BERLIN_BBOX)


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


class FakeResponse:
    def __init__(self, payload: dict) -> None:
        self.payload = payload

    def json(self) -> dict:
        return self.payload


class FakeClient:
    """Stands in for HttpClient. respond(body, call_number) returns a payload or an exception."""

    def __init__(self, respond: Callable[[dict, int], dict | Exception]) -> None:
        self.respond = respond
        self.calls: list[dict] = []

    def post(self, url: str, json: dict, headers: dict) -> FakeResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        result = self.respond(json, len(self.calls))
        if isinstance(result, Exception):
            raise result
        return FakeResponse(result)


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


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv(gp.API_KEY_ENV, FAKE_KEY)
    monkeypatch.setattr(config, "RAW_DIR", tmp_path / "raw")
    monkeypatch.setattr(config, "GOOGLE_PLACES_QUERIES", ["Hausverwaltung"])


def raw_files() -> list[Path]:
    return sorted(config.RAW_DIR.glob("google_places_*.json"))


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


# --- Search loop -----------------------------------------------------------------------


def test_pagination_follows_token_and_stops() -> None:
    pages = {1: full_page("a", "t1"), 2: {"places": [make_place("b")]}}
    client = FakeClient(lambda body, n: pages[n])
    companies = gp.collect_google_places(client)
    assert len(client.calls) == 2
    assert "pageToken" not in client.calls[0]["json"]
    assert client.calls[1]["json"]["pageToken"] == "t1"
    assert len(companies) == 21
    assert client.calls[0]["headers"]["X-Goog-FieldMask"] == gp.FIELD_MASK


def test_saturated_cell_is_split_and_duplicates_kept_once() -> None:
    def respond(body: dict, n: int) -> dict:
        if n <= 3:  # root: 3 full pages with a token left -> saturated
            return full_page(f"root{n}", "more")
        return {"places": [make_place("dup"), make_place(f"child{n}")]}

    client = FakeClient(respond)
    companies = gp.collect_google_places(client)
    assert len(client.calls) == 3 + 4
    ids = [c.sources[0].source_id for c in companies]
    assert ids.count("dup") == 1
    assert len(ids) == 60 + 1 + 4


def test_min_size_cell_not_split_and_warned(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(config, "BERLIN_BBOX", {"low": (52.5, 13.4), "high": (52.509, 13.409)})
    client = FakeClient(lambda body, n: full_page(f"p{n}", "more"))
    with caplog.at_level(logging.WARNING):
        gp.collect_google_places(client)
    assert len(client.calls) == 3
    assert "minimum size" in caplog.text


def test_budget_never_exceeded_and_remaining_cells_logged(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(config, "GOOGLE_PLACES_MAX_REQUESTS", 7)
    client = FakeClient(lambda body, n: full_page(f"p{n}", "more"))  # always saturated
    with caplog.at_level(logging.WARNING):
        gp.collect_google_places(client)
    assert len(client.calls) == 7
    # root (3) + child 1 (3, split again) + child 2 page 1 = 7 requests.
    # Left: child 2 (incomplete), children 3-4, child 1's four sub-cells = 7 cells.
    assert "7 cell(s) left unsearched" in caplog.text
    assert json.loads(raw_files()[0].read_text(encoding="utf-8"))["requests_made"] == 7


def test_failed_request_is_logged_and_run_continues(caplog: pytest.LogCaptureFixture) -> None:
    def respond(body: dict, n: int) -> dict | Exception:
        if n <= 3:
            return full_page(f"root{n}", "more")
        if n == 4:
            return http_error(500, '{"error": {"message": "backend boom"}}')
        return {"places": [make_place(f"child{n}")]}

    client = FakeClient(respond)
    with caplog.at_level(logging.ERROR):
        companies = gp.collect_google_places(client)
    assert len(client.calls) == 7
    assert len(companies) == 60 + 3
    assert "backend boom" in caplog.text


def test_retryable_status_error_is_logged_and_run_continues(
    caplog: pytest.LogCaptureFixture,
) -> None:
    # The real HttpClient turns 429/5xx into RetryableStatusError, not HTTPError.
    def respond(body: dict, n: int) -> dict | Exception:
        if n <= 3:
            return full_page(f"root{n}", "more")
        if n == 4:
            return RetryableStatusError(503, "backend unavailable", "https://places.googleapis.com")
        return {"places": [make_place(f"child{n}")]}

    with caplog.at_level(logging.ERROR):
        companies = gp.collect_google_places(FakeClient(respond))
    assert len(companies) == 60 + 3
    assert "503 backend unavailable" in caplog.text


def test_failure_after_first_page_splits_cell_instead_of_losing_it() -> None:
    # Page 1 said "more results exist"; page 2 failing must not drop the whole area.
    def respond(body: dict, n: int) -> dict | Exception:
        if n == 1:
            return full_page("root", "t1")
        if n == 2:
            return http_error(400, '{"error": {"status": "INVALID_ARGUMENT"}}')
        return {"places": [make_place(f"child{n}")]}

    client = FakeClient(respond)
    companies = gp.collect_google_places(client)
    assert len(client.calls) == 2 + 4
    assert len(companies) == 20 + 4


def test_budget_counts_earlier_runs_this_month(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(config, "GOOGLE_PLACES_MAX_REQUESTS", 10)
    config.RAW_DIR.mkdir(parents=True)
    now = datetime.now()
    last_month = (now.replace(day=1) - timedelta(days=1)).strftime("%Y%m")
    # Day "00" never collides with the file this run writes.
    (config.RAW_DIR / f"google_places_{now:%Y%m}00-000000.json").write_text(
        json.dumps({"requests_made": 6}), encoding="utf-8"
    )
    (config.RAW_DIR / f"google_places_{last_month}00-000000.json").write_text(
        json.dumps({"requests_made": 9}), encoding="utf-8"
    )
    client = FakeClient(lambda body, n: full_page(f"p{n}", "more"))
    with caplog.at_level(logging.WARNING):
        gp.collect_google_places(client)
    assert len(client.calls) == 4


def test_monthly_budget_used_up_makes_no_requests(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config, "GOOGLE_PLACES_MAX_REQUESTS", 5)
    config.RAW_DIR.mkdir(parents=True)
    (config.RAW_DIR / f"google_places_{datetime.now():%Y%m}00-000000.json").write_text(
        json.dumps({"requests_made": 5}), encoding="utf-8"
    )
    client = FakeClient(lambda body, n: full_page(f"p{n}", None))
    assert gp.collect_google_places(client) == []
    assert client.calls == []


@pytest.mark.parametrize("status", [400, 401, 403])
def test_first_request_auth_error_aborts(status: int) -> None:
    client = FakeClient(lambda body, n: http_error(status, '{"error": {"status": "DENIED"}}'))
    with pytest.raises(RuntimeError, match=str(status)):
        gp.collect_google_places(client)
    assert len(client.calls) == 1
    assert len(raw_files()) == 1


def test_missing_api_key_is_clear_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(gp.API_KEY_ENV)
    client = FakeClient(lambda body, n: {})
    with pytest.raises(RuntimeError, match=gp.API_KEY_ENV):
        gp.collect_google_places(client)
    assert client.calls == []


# --- Raw data --------------------------------------------------------------------------


def test_raw_written_when_later_request_crashes() -> None:
    def respond(body: dict, n: int) -> dict | Exception:
        return full_page("a", "t1") if n == 1 else KeyError("unexpected crash")

    with pytest.raises(KeyError):
        gp.collect_google_places(FakeClient(respond))
    payload = json.loads(raw_files()[0].read_text(encoding="utf-8"))
    assert payload["requests_made"] == 2
    first = payload["pages"][0]
    assert first["query"] == "Hausverwaltung"
    assert first["page_index"] == 0
    assert first["cell"] == ROOT._asdict()
    assert len(first["response"]["places"]) == 20


def test_api_key_absent_from_raw_payload() -> None:
    def respond(body: dict, n: int) -> dict | Exception:
        if n == 1:
            return full_page("a", "t1")
        return http_error(500, f'{{"error": "echoed key {FAKE_KEY}"}}')

    gp.collect_google_places(FakeClient(respond))
    text = raw_files()[0].read_text(encoding="utf-8")
    assert FAKE_KEY not in text
    assert "echoed key ***" in text


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
