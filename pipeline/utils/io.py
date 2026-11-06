"""JSON file I/O. Raw files are write-once; company lists round-trip through the schema."""

import hashlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

from pydantic import TypeAdapter

from pipeline.models import Company

_companies = TypeAdapter(list[Company])


def write_raw(raw_dir: Path, source: str, payload: object) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    # Microseconds: two runs finishing in the same second must not collide (paid data is lost).
    path = raw_dir / f"{source}_{datetime.now():%Y%m%d-%H%M%S-%f}.json"
    with path.open("x", encoding="utf-8") as f:  # "x": never overwrite raw data
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def safe_name(text: str) -> str:
    """A filename for ids like 'osm:node/123': readable slug + hash, so it is unique and can
    never escape its directory."""
    slug = re.sub(r"[^a-z0-9._-]+", "_", text.lower()).strip("._")[:60]
    return f"{slug}-{hashlib.sha1(text.encode()).hexdigest()[:8]}"


def write_text_atomic(path: Path, text: str) -> None:
    """Write to a temp file, then rename: a crash never leaves a half-written file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def save_companies(path: Path, companies: list[Company]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_companies.dump_json(companies, indent=2))


def load_companies(path: Path) -> list[Company]:
    return _companies.validate_json(path.read_bytes())
