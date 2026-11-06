"""JSON file I/O. Raw files are write-once; company lists round-trip through the schema."""

import json
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from pipeline.models import Company

_companies = TypeAdapter(list[Company])


def write_raw(raw_dir: Path, source: str, payload: object) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    path = raw_dir / f"{source}_{datetime.now():%Y%m%d-%H%M%S}.json"
    with path.open("x", encoding="utf-8") as f:  # "x": never overwrite raw data
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def save_companies(path: Path, companies: list[Company]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_companies.dump_json(companies, indent=2))


def load_companies(path: Path) -> list[Company]:
    return _companies.validate_json(path.read_bytes())
