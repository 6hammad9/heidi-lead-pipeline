# Heidi Lead Pipeline — coding standards

Methodology and decisions: RULEBOOK.md. KPI column spec: KPI_LIST.md.

## Structure
- One file = one job. If a file can't be described in one sentence, split it.
- Each pipeline step is its own module with one entry function
  (e.g. `collect_osm() -> list[Company]`). `pipeline/main.py` only calls steps in order.
- Shared helpers (URL normalising, HTTP, JSON I/O, logging) live in `pipeline/utils/`.
- Functions do one thing, roughly under 40 lines. A "# now do X" comment means extract a function.
- Pure functions where possible. Scoring must be pure.
- Classes only for data + behaviour or state: `Company`/`Fact`/`Contact` models,
  `ResearchAgent`, `CheckpointStore`, `HttpClient`. Single functions stay plain functions.
- Every source collector has the same signature and returns `list[Company]`.

## Data
- One schema: `pipeline/models.py`. No loose dicts between steps.
- Every KPI value is a `Fact`: value, status (published/estimated/unknown), source URL, quote.
- Raw collection results go to `data/raw/` (timestamped) and are never edited.
  Later steps write new files.

## Configuration and secrets
- No hard-coded values in logic: models, batch sizes, weights, bands live in `pipeline/config.py`.
- Rulebook numbers (tier weights, bonus points, 18.8 factor) exist only in config.
- API keys only in `.env` (python-dotenv); `.env` is git-ignored.

## Reliability
- Every network call goes through `utils/http.py` (timeout + retries via tenacity).
- Checkpoint after every company; skip finished ones on restart.
- One failure never stops a run: catch, log with the company name, mark the record, continue.
- Polite crawling: delays between requests, clear user agent, respect robots.txt and
  blocked pages (never work around them).

## Code quality
- Type hints everywhere. `logging`, not print (console + `data/logs/`).
- Clear names over comments; comments explain why, not what.
- `ruff check` and `ruff format` before every commit.

## Testing
- pytest for exact parts: scoring, deduplication, URL normalising.
- The LLM is not unit-tested; it's validated by the 10-company accuracy check.

## Git
- Commit after each working step with a clear message.

## Commands (from repo root)
- Run: `.venv\Scripts\python -m pipeline.main <step>`
- Test: `.venv\Scripts\python -m pytest`
- Lint/format: `.venv\Scripts\ruff check . --fix; .venv\Scripts\ruff format .`
