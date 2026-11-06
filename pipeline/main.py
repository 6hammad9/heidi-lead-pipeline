"""Entry point: runs pipeline steps in order. Usage: python -m pipeline.main <step> [options]"""

import argparse
import logging
from collections.abc import Callable
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from pipeline import config
from pipeline.agent.ledger import SpendLedger
from pipeline.agent.research_agent import ResearchAgent
from pipeline.checkpoint import CheckpointStore
from pipeline.collectors.google_places import collect_google_places
from pipeline.collectors.osm import collect_osm
from pipeline.dedupe import merge_companies
from pipeline.fetching.fetcher import PageFetcher
from pipeline.fetching.page_store import PageStore
from pipeline.fetching.robots import RobotsPolicy
from pipeline.models import Company
from pipeline.research_step import run_research
from pipeline.utils.http import HttpClient
from pipeline.utils.io import load_companies, save_companies
from pipeline.utils.logging_setup import setup_logging

log = logging.getLogger(__name__)

COLLECTORS: dict[str, Callable[[HttpClient], list[Company]]] = {
    "osm": collect_osm,
    "google_places": collect_google_places,
}
MERGED_FILE = config.INTERIM_DIR / "companies_merged.json"


def run_collect(args: argparse.Namespace) -> None:
    client = HttpClient()
    for name in args.sources:
        try:
            companies = COLLECTORS[name](client)
        except Exception:
            log.exception("Collector %s failed, continuing with the others", name)
            continue
        save_collected(name, companies)


def save_collected(name: str, companies: list[Company]) -> None:
    """An empty result (dry run, outage) must not wipe an earlier real collection."""
    path = config.INTERIM_DIR / f"collected_{name}.json"
    if not companies and path.exists():
        log.warning("Collector %s returned nothing; keeping the existing %s", name, path)
        return
    save_companies(path, companies)


def run_merge(args: argparse.Namespace) -> None:
    paths = sorted(config.INTERIM_DIR.glob("collected_*.json"))
    companies = [c for path in paths for c in load_companies(path)]
    merged = merge_companies(companies)
    save_companies(MERGED_FILE, merged)
    log.info(
        "Merged %d records from %s into %d companies: %s",
        len(companies),
        [p.stem for p in paths],
        len(merged),
        MERGED_FILE,
    )


def run_research_step(args: argparse.Namespace) -> None:
    http = HttpClient()
    fetcher = PageFetcher(http, PageStore(config.PAGES_DIR), RobotsPolicy(http))
    ledger = SpendLedger(config.SPEND_LEDGER)
    agent = ResearchAgent(anthropic.Anthropic(), args.model, fetcher, ledger, effort=args.effort)
    summary = run_research(
        load_companies(MERGED_FILE),
        agent,
        CheckpointStore(config.RESEARCH_DIR, args.model),
        ledger,
        budget_usd=config.AGENT_RUN_BUDGET_USD,
        reserve_per_company_usd=config.AGENT_MAX_COST_PER_COMPANY_USD,
        limit=args.limit,
        only_ids=read_ids(args.ids) if args.ids else None,
    )
    log.info("Research summary: %s", summary.model_dump_json())


def read_ids(path: Path) -> set[str]:
    """One company id per line; blank lines and # comments ignored."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


STEPS: dict[str, Callable[[argparse.Namespace], None]] = {
    "collect": run_collect,
    "merge": run_merge,
    "research": run_research_step,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Heidi lead pipeline")
    parser.add_argument("step", choices=STEPS)
    parser.add_argument(
        "--sources",
        nargs="+",
        choices=COLLECTORS,
        default=list(COLLECTORS),
        help="collectors to run (collect step only)",
    )
    parser.add_argument("--model", choices=config.MODEL_PRICES, default=config.AGENT_MODEL)
    parser.add_argument("--effort", default=config.AGENT_EFFORT)
    parser.add_argument(
        "--limit", type=int, default=config.BATCH_SIZE, help="companies per research run"
    )
    parser.add_argument("--ids", type=Path, help="file of company ids to research (one per line)")
    args = parser.parse_args()
    load_dotenv()
    setup_logging()
    STEPS[args.step](args)


if __name__ == "__main__":
    main()
