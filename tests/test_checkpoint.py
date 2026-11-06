from datetime import UTC, datetime
from pathlib import Path

from pipeline.agent.schema import ResearchRecord
from pipeline.checkpoint import CheckpointStore
from pipeline.utils.io import safe_name


def record(company_id: str, stop: str = "submitted") -> ResearchRecord:
    return ResearchRecord(
        company_id=company_id,
        model="claude-haiku-5-5",
        effort="medium",
        submission=None,
        stop=stop,
        finished_at=datetime(2026, 11, 7, tzinfo=UTC),
    )


def test_round_trip_and_done(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path, "claude-haiku-5-5")
    assert store.load("a.de") is None
    assert not store.is_done("a.de")
    store.save(record("a.de"))
    assert store.load("a.de") == record("a.de")
    assert store.is_done("a.de")


def test_error_records_are_retried(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path, "m")
    store.save(record("a.de", stop="error"))
    assert not store.is_done("a.de")


def test_models_are_kept_apart(tmp_path: Path) -> None:
    CheckpointStore(tmp_path, "haiku").save(record("a.de"))
    assert not CheckpointStore(tmp_path, "sonnet").is_done("a.de")


def test_ids_with_special_characters_get_distinct_safe_files(tmp_path: Path) -> None:
    store = CheckpointStore(tmp_path, "m")
    for cid in ["osm:node/1", "osm_node_1", "../../etc/passwd"]:
        store.save(record(cid))
    assert {r.company_id for r in store.load_all()} == {
        "osm:node/1",
        "osm_node_1",
        "../../etc/passwd",
    }
    assert all(p.parent == store.dir for p in store.dir.iterdir())
    assert not list(store.dir.glob("*.tmp"))


def test_safe_name_never_contains_path_separators() -> None:
    assert "/" not in safe_name("a/b") and "\\" not in safe_name("a\\b")
    assert ".." not in safe_name("../x")
