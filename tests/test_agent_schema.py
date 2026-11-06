from pipeline.agent.schema import CLAIM_FIELDS, ResearchSubmission, submission_json_schema
from pipeline.models import Company, Fact

UNSUPPORTED_IN_STRICT_MODE = {
    "minLength",
    "maxLength",
    "minimum",
    "maximum",
    "multipleOf",
    "default",
}


def _objects(node: object) -> list[dict]:
    found: list[dict] = []
    if isinstance(node, dict):
        if node.get("type") == "object":
            found.append(node)
        for value in node.values():
            found.extend(_objects(value))
    elif isinstance(node, list):
        for item in node:
            found.extend(_objects(item))
    return found


def _keys(node: object) -> set[str]:
    if isinstance(node, dict):
        return set(node) | {k for v in node.values() for k in _keys(v)}
    if isinstance(node, list):
        return {k for item in node for k in _keys(item)}
    return set()


def test_every_object_is_closed_and_fully_required() -> None:
    objects = _objects(submission_json_schema())
    assert objects, "schema has no objects"
    for obj in objects:
        assert obj.get("additionalProperties") is False
        assert set(obj["required"]) == set(obj["properties"])


def test_schema_uses_no_keywords_strict_mode_rejects() -> None:
    assert not _keys(submission_json_schema()) & UNSUPPORTED_IN_STRICT_MODE


def test_schema_has_no_title_annotations() -> None:
    schema = submission_json_schema()
    assert "title" not in _keys({k: v for k, v in schema.items() if k != "properties"})


def test_every_claim_field_maps_to_a_company_fact() -> None:
    fact_fields = {n for n, f in Company.model_fields.items() if f.annotation is Fact}
    assert set(CLAIM_FIELDS) == fact_fields


def test_submission_round_trips_through_schema_validation() -> None:
    empty_claim = {"value": None, "source_url": None, "quote": None}
    payload = {name: dict(empty_claim) for name in CLAIM_FIELDS}
    payload |= {"contacts": [], "notes": None}
    assert ResearchSubmission.model_validate(payload).units_managed.value is None
