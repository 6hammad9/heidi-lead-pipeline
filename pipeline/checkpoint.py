"""One saved research record per company and model, so a stopped run resumes where it left off."""

from pathlib import Path

from pipeline.agent.schema import ResearchRecord
from pipeline.utils.io import safe_name, write_text_atomic


class CheckpointStore:
    def __init__(self, root: Path, model: str) -> None:
        self.dir = root / safe_name(model)

    def path_for(self, company_id: str) -> Path:
        return self.dir / f"{safe_name(company_id)}.json"

    def save(self, record: ResearchRecord) -> None:
        write_text_atomic(self.path_for(record.company_id), record.model_dump_json(indent=2))

    def load(self, company_id: str) -> ResearchRecord | None:
        path = self.path_for(company_id)
        if not path.exists():
            return None
        return ResearchRecord.model_validate_json(path.read_text(encoding="utf-8"))

    def load_all(self) -> list[ResearchRecord]:
        records = [
            ResearchRecord.model_validate_json(p.read_text(encoding="utf-8"))
            for p in self.dir.glob("*.json")
        ]
        return sorted(records, key=lambda r: r.company_id)

    def is_done(self, company_id: str) -> bool:
        """API and network errors are transient: those companies are retried next run."""
        record = self.load(company_id)
        return record is not None and record.stop != "error"
