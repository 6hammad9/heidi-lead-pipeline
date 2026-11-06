import importlib
from datetime import UTC, datetime
from itertools import permutations

import pytest

from pipeline import config, dedupe
from pipeline.dedupe import merge_companies, normalize_company_name
from pipeline.models import Company, Contact, Fact, SourceRef, Status

COLLECTED_AT = datetime(2026, 11, 1, tzinfo=UTC)


def make(
    name: str,
    source_id: str,
    *,
    source: str = "osm",
    website: str | None = None,
    postcode: str | None = None,
    **fields: object,
) -> Company:
    ref = SourceRef(
        source=source,
        source_id=source_id,
        url=f"https://example.org/{source}/{source_id}",
        collected_at=COLLECTED_AT,
    )
    return Company(
        id=f"{source}:{source_id}",
        name=name,
        website=website,
        postcode=postcode,
        sources=[ref],
        **fields,
    )


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Müller Hausverwaltung GmbH", "mueller hausverwaltung"),
        ("Mueller Hausverwaltung", "mueller hausverwaltung"),
        ("Schmidt Immobilien GmbH & Co. KG", "schmidt immobilien"),
        ("Schröder Verwaltung, UG (haftungsbeschränkt)", "schroeder verwaltung"),
        ("Weiß Immobilienverwaltung e.K.", "weiss immobilienverwaltung"),
        ("Becker Verwaltung KG GmbH", "becker verwaltung"),
        ("Hausverwaltung Zug", "hausverwaltung zug"),
        ("  Haus-Verwaltung   Krause!  ", "haus verwaltung krause"),
        ("Krause Verwaltung GmbH.", "krause verwaltung"),
        ("Weiß Immobilienverwaltung e.K", "weiss immobilienverwaltung"),
        ("Schmidt Immobilien GmbH & Co.KG", "schmidt immobilien"),
        ("Schmidt Immobilien GmbH&Co. KG", "schmidt immobilien"),
        ("Hausverwaltung Haag", "hausverwaltung haag"),
        ("Kag Immobilien", "kag immobilien"),
        ("Wohnungsbaugenossenschaft Friedrichshain eG", "wohnungsbaugenossenschaft friedrichshain"),
    ],
)
def test_normalize_company_name(raw: str, expected: str) -> None:
    assert normalize_company_name(raw) == expected


def test_www_and_http_variants_of_same_domain_merge() -> None:
    a = make("HV Müller", "1", website="http://www.hv-mueller.de")
    b = make("Müller Hausverwaltung", "2", source="google_places", website="https://hv-mueller.de/")
    [merged] = merge_companies([a, b])
    assert merged.id == "hv-mueller.de"


def test_platform_domain_websites_do_not_merge() -> None:
    a = make("Alpha Verwaltung", "1", website="https://facebook.com/alpha")
    b = make("Beta Verwaltung", "2", website="https://www.facebook.com/beta")
    assert len(merge_companies([a, b])) == 2


def test_same_name_and_postcode_merge_without_website() -> None:
    a = make("Krause Hausverwaltung", "1", postcode="10115")
    b = make("Krause Hausverwaltung", "2", source="google_places", postcode="10115")
    assert len(merge_companies([a, b])) == 1


def test_same_name_different_postcodes_stay_separate() -> None:
    a = make("Krause Hausverwaltung", "1", postcode="10115")
    b = make("Krause Hausverwaltung", "2", postcode="12043")
    assert len(merge_companies([a, b])) == 2


def test_postcode_less_record_matching_two_postcodes_stays_separate_in_any_order() -> None:
    a = make("Krause Hausverwaltung", "1", postcode="10115")
    bridge = make("Krause Hausverwaltung", "2", source="google_places", phone="030 9")
    c = make("Krause Hausverwaltung", "3", postcode="12043")
    for order in permutations([a, bridge, c]):
        result = merge_companies(list(order))
        assert [[s.source_id for s in r.sources] for r in result] == [["2"], ["1"], ["3"]]


def test_postcode_less_record_merges_with_single_branch_group() -> None:
    a = make("Krause Hausverwaltung", "1", website="https://krause.de", postcode="10115")
    b = make("Krause Hausverwaltung", "2", website="https://krause.de", postcode="12043")
    c = make("Krause Hausverwaltung", "3")
    for order in permutations([a, b, c]):
        assert len(merge_companies(list(order))) == 1


def test_legal_form_and_umlauts_normalised_for_matching() -> None:
    a = make("Müller Hausverwaltung GmbH", "1", postcode="10115")
    b = make("Mueller Hausverwaltung", "2", postcode="10115")
    assert len(merge_companies([a, b])) == 1


def test_generic_name_not_merged() -> None:
    a = make("Hausverwaltung GmbH", "1", postcode="10115")
    b = make("Hausverwaltung", "2", postcode="10115")
    assert len(merge_companies([a, b])) == 2


def test_generic_names_with_umlauts_in_config_are_transliterated(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(config, "GENERIC_COMPANY_NAMES", ["Grundstücksverwaltung"])
    try:
        module = importlib.reload(dedupe)
        a = make("Grundstücksverwaltung GmbH", "1", postcode="10115")
        b = make("Grundstücksverwaltung", "2", postcode="10115")
        assert len(module.merge_companies([a, b])) == 2
    finally:
        monkeypatch.undo()
        importlib.reload(dedupe)


def test_transitive_merge_via_domain_and_name() -> None:
    a = make("Alpha Verwaltung GmbH", "1", postcode="10115")
    b = make("Alpha Verwaltung", "2", website="https://alpha-hv.de", postcode="10115")
    c = make("AHV Berlin", "3", source="google_places", website="www.alpha-hv.de")
    [merged] = merge_companies([a, b, c])
    assert {s.source_id for s in merged.sources} == {"1", "2", "3"}


def test_different_own_domains_stay_separate_despite_bridge_record() -> None:
    a = make("Schulz Verwaltung", "1", website="https://schulz-a.de", postcode="10115")
    bridge = make("Schulz Verwaltung", "2", source="google_places", postcode="10115", phone="030 9")
    c = make("Schulz Verwaltung", "3", website="https://schulz-b.de", postcode="10115")
    for order in permutations([a, bridge, c]):
        result = merge_companies(list(order))
        # The bridge could belong to either firm, so it must not be merged into one by input order.
        assert [r.id for r in result] == ["google_places:2", "schulz-a.de", "schulz-b.de"]
        assert [r.phone for r in result] == ["030 9", None, None]
        assert merge_companies(result) == result


def test_firm_known_by_two_names_absorbs_both_branches_in_any_order() -> None:
    a = make("Schulz Verwaltung GmbH", "1", website="https://schulz.de")
    b = make("AHV", "2", website="https://schulz.de")
    branch_1 = make("Schulz Verwaltung", "3", website="https://facebook.com/s", postcode="10115")
    branch_2 = make("AHV", "4", website="https://facebook.com/a", postcode="12043")
    for order in permutations([a, b, branch_1, branch_2]):
        [merged] = merge_companies(list(order))
        assert merged.id == "schulz.de"


def test_bridge_with_single_candidate_firm_merges_in_any_order() -> None:
    a = make("Schulz Verwaltung", "1", website="https://schulz-a.de", postcode="10115")
    bridge = make("Schulz Verwaltung", "2", postcode="10115")
    other = make("Schulz Verwaltung", "3", website="https://schulz-b.de", postcode="12043")
    for order in permutations([a, bridge, other]):
        assert [r.id for r in merge_companies(list(order))] == ["schulz-a.de", "schulz-b.de"]


def test_source_priority_picks_google_phone() -> None:
    osm = make("Krause HV", "1", phone="030 111", email_general="info@krause.de")
    google = make("Krause HV", "2", source="google_places", phone="030 222")
    [merged] = merge_companies([osm, google])
    assert merged.phone == "030 222"
    assert merged.email_general == "info@krause.de"
    assert merged.sources[0].source == "google_places"
    assert merged.id == "google_places:2"


def test_own_domain_website_preferred_over_facebook() -> None:
    google = make("Krause HV", "1", source="google_places", website="https://facebook.com/krause")
    osm = make("Krause HV", "2", website="https://krause-hv.de")
    [merged] = merge_companies([google, osm])
    assert merged.website == "https://krause-hv.de"
    assert merged.id == "krause-hv.de"


def test_sources_unique_by_source_and_id() -> None:
    a = make("Krause HV", "1", website="https://krause-hv.de")
    b = make("Krause HV", "1", website="https://krause-hv.de")
    [merged] = merge_companies([a, b])
    assert [(s.source, s.source_id) for s in merged.sources] == [("osm", "1")]


def test_known_fact_preserved_over_unknown() -> None:
    known = Fact(value=1200, status=Status.PUBLISHED, source_url="https://krause-hv.de")
    google = make("Krause HV", "1", source="google_places", website="https://krause-hv.de")
    osm = make("Krause HV", "2", website="https://krause-hv.de", units_managed=known)
    [merged] = merge_companies([google, osm])
    assert merged.units_managed == known
    assert merged.software.status == Status.UNKNOWN


def test_contacts_and_errors_unique() -> None:
    anna = Contact(name="Anna Krause", email="anna@krause-hv.de")
    a = make("Krause HV", "1", website="krause-hv.de", contacts=[anna], errors=["timeout"])
    b = make("Krause HV", "2", website="krause-hv.de", contacts=[anna], errors=["timeout", "403"])
    [merged] = merge_companies([a, b])
    assert merged.contacts == [anna]
    assert merged.errors == ["timeout", "403"]


def _sample() -> list[Company]:
    return [
        make("Zeta Verwaltung", "1", website="https://zeta.de", postcode="10115"),
        make("Zeta Verwaltung GmbH", "2", source="google_places", postcode="10115", phone="030 1"),
        make("Alpha HV", "3", website="https://facebook.com/alpha"),
        make("Müller Hausverwaltung", "4", postcode="12043"),
        make("Mueller Hausverwaltung GmbH", "5", source="google_places", postcode="12043"),
        make("Hausverwaltung", "6"),
    ]


def test_inputs_not_mutated() -> None:
    companies = _sample()
    before = [c.model_dump() for c in companies]
    result = merge_companies(companies)
    assert [c.model_dump() for c in companies] == before
    input_objects = {id(c) for c in companies} | {id(s) for c in companies for s in c.sources}
    output_objects = {id(c) for c in result} | {id(s) for c in result for s in c.sources}
    assert input_objects.isdisjoint(output_objects)


def test_idempotent() -> None:
    once = merge_companies(_sample())
    assert merge_companies(once) == once


def test_deterministic_order() -> None:
    result = merge_companies(_sample())
    assert merge_companies(list(reversed(_sample()))) == result
    names = [normalize_company_name(c.name) for c in result]
    assert names == sorted(names)
    assert len(result) == 4
