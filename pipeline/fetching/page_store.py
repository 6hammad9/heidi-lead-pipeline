"""Fetched pages on disk, per company: reused within and across runs, and the exact text that
quote verification checks against."""

import hashlib
from pathlib import Path

from pipeline.models import Page
from pipeline.utils.io import safe_name, write_text_atomic


class PageStore:
    def __init__(self, root: Path) -> None:
        self.root = root

    def get(self, company_id: str, url: str) -> Page | None:
        path = self._path(company_id, url)
        if not path.exists():
            return None
        return Page.model_validate_json(path.read_text(encoding="utf-8"))

    def put(self, company_id: str, page: Page) -> None:
        write_text_atomic(self._path(company_id, page.requested_url), page.model_dump_json())

    def all(self, company_id: str) -> list[Page]:
        folder = self.root / safe_name(company_id)
        pages = [
            Page.model_validate_json(p.read_text(encoding="utf-8")) for p in folder.glob("*.json")
        ]
        unique = {page.url: page for page in sorted(pages, key=lambda p: p.fetched_at)}
        return list(unique.values())

    def _path(self, company_id: str, url: str) -> Path:
        name = hashlib.sha1(url.encode()).hexdigest()[:16]
        return self.root / safe_name(company_id) / f"{name}.json"
