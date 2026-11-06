from datetime import UTC, datetime
from pathlib import Path

import pytest

from pipeline import config, main
from pipeline.models import Company, SourceRef
from pipeline.utils.io import load_companies


def company(cid: str) -> Company:
    ref = SourceRef(source="osm", source_id=cid, url="u", collected_at=datetime.now(UTC))
    return Company(id=cid, name=cid, sources=[ref])


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(config, "INTERIM_DIR", tmp_path)


def test_empty_result_does_not_overwrite_existing_collection() -> None:
    main.save_collected("google_places", [company("a.de")])
    main.save_collected("google_places", [])
    path = config.INTERIM_DIR / "collected_google_places.json"
    assert [c.id for c in load_companies(path)] == ["a.de"]


def test_first_empty_result_is_saved() -> None:
    main.save_collected("osm", [])
    assert load_companies(config.INTERIM_DIR / "collected_osm.json") == []


def test_new_result_replaces_old_one() -> None:
    main.save_collected("osm", [company("a.de")])
    main.save_collected("osm", [company("b.de")])
    assert [c.id for c in load_companies(config.INTERIM_DIR / "collected_osm.json")] == ["b.de"]
