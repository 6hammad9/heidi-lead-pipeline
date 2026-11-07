"""Entry point: runs pipeline steps in order. Usage: python -m pipeline.main <step> [options]"""

import argparse
import logging
from collections.abc import Callable
from datetime import datetime
from pathlib import Path

import anthropic
from dotenv import load_dotenv

from pipeline import config
from pipeline.agent.ledger import SpendLedger
from pipeline.agent.research_agent import ResearchAgent
from pipeline.agent.schema import ResearchRecord
from pipeline.checkpoint import CheckpointStore
from pipeline.collectors.google_places import collect_google_places
from pipeline.collectors.osm import collect_osm
from pipeline.dedupe import merge_companies
from pipeline.evaluation import compare, read_truth, write_template
from pipeline.export.excel import write_workbook
from pipeline.export.table import KPI_DEFINITIONS, lead_rows, run_log_rows
from pipeline.fetching.fetcher import PageFetcher
from pipeline.fetching.page_store import PageStore
from pipeline.fetching.robots import RobotsPolicy
from pipeline.models import Company
from pipeline.quality_gate import GateResult, evaluate
from pipeline.research_step import Gate, likely_property_manager, run_research, select_companies
from pipeline.scoring import score_all
from pipeline.utils.http import HttpClient
from pipeline.utils.io import load_companies, save_companies
from pipeline.utils.logging_setup import setup_logging
from pipeline.verify_step import build_verified

log = logging.getLogger(__name__)

COLLECTORS: dict[str, Callable[[HttpClient], list[Company]]] = {
    "osm": collect_osm,
    "google_places": collect_google_places,
}
MERGED_FILE = config.INTERIM_DIR / "companies_merged.json"
VERIFIED_FILE = config.INTERIM_DIR / "companies_verified.json"
EVAL_SIZE = 10
EVAL_IDS = config.DATA_DIR / "eval" / "eval10.txt"
EVAL_TEMPLATE = config.DATA_DIR / "eval" / "ground_truth.xlsx"


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
    pages = PageStore(config.PAGES_DIR)
    fetcher = PageFetcher(http, pages, RobotsPolicy(http))
    ledger = SpendLedger(config.SPEND_LEDGER)
    agent = ResearchAgent(anthropic.Anthropic(), args.model, fetcher, ledger, effort=args.effort)
    companies = load_companies(MERGED_FILE)
    summary = run_research(
        companies,
        agent,
        CheckpointStore(config.RESEARCH_DIR, args.model),
        ledger,
        budget_usd=config.AGENT_RUN_BUDGET_USD,
        reserve_per_company_usd=config.AGENT_MAX_COST_PER_COMPANY_USD,
        limit=args.limit,
        only_ids=read_ids(args.ids) if args.ids else None,
        gate=make_gate(companies, pages),
    )
    log.info("Research summary: %s", summary.model_dump_json())


def make_gate(companies: list[Company], pages: PageStore) -> Gate:
    """The gate re-runs the code-side quote check on this run's records."""
    by_id = {c.id: c for c in companies}

    def gate(records: list[ResearchRecord]) -> GateResult:
        researched = [by_id[r.company_id] for r in records if r.company_id in by_id]
        _, stats = build_verified(researched, records, pages)
        return evaluate(records, stats)

    return gate


def run_all(args: argparse.Namespace) -> None:
    """The whole pipeline, no manual steps. Collected data is reused unless --refresh."""
    if args.refresh or not list(config.INTERIM_DIR.glob("collected_*.json")):
        run_collect(args)
    for step in (run_merge, run_research_step, run_verify, run_export):
        step(args)


def run_verify(args: argparse.Namespace) -> None:
    records = CheckpointStore(config.RESEARCH_DIR, args.model).load_all()
    companies, stats = build_verified(
        load_companies(MERGED_FILE), records, PageStore(config.PAGES_DIR)
    )
    save_companies(VERIFIED_FILE, companies)
    rate = stats.claims_verified / stats.claims_checked if stats.claims_checked else 0.0
    log.info(
        "Verified %d research records: %d/%d claims confirmed on their page (%.0f%%), "
        "%d/%d contacts, %d published emails -> %s",
        len(records),
        stats.claims_verified,
        stats.claims_checked,
        rate * 100,
        stats.contacts_verified,
        stats.contacts_checked,
        stats.emails_published,
        VERIFIED_FILE,
    )
    for failure in stats.failures:
        log.info("Not confirmed: %s", failure)


def run_export(args: argparse.Namespace) -> None:
    companies = load_companies(VERIFIED_FILE)
    scores, model = score_all(companies)
    run_log = run_log_rows(companies, scores, model, datetime.now())
    write_workbook(config.OUTPUT_XLSX, lead_rows(companies, scores), KPI_DEFINITIONS, run_log)
    scored = sum(s.lead_score is not None for s in scores)
    log.info("Exported %d companies (%d scored) to %s", len(companies), scored, config.OUTPUT_XLSX)


def run_eval_template(args: argparse.Namespace) -> None:
    """10 likely property managers spread over the list, and a blank template to check by hand."""
    if EVAL_TEMPLATE.exists():
        log.warning("%s exists; not overwriting hand-checked work", EVAL_TEMPLATE)
        return
    selected, _, _ = select_companies(load_companies(MERGED_FILE), None)
    managers = [c for c in selected if likely_property_manager(c)]
    picks = managers[:: max(len(managers) // EVAL_SIZE, 1)][:EVAL_SIZE]
    EVAL_IDS.write_text("\n".join(c.id for c in picks) + "\n", encoding="utf-8")
    write_template(EVAL_TEMPLATE, picks)
    log.info("Accuracy test: %d companies in %s; fill %s", len(picks), EVAL_IDS, EVAL_TEMPLATE)


def run_evaluate(args: argparse.Namespace) -> None:
    records = CheckpointStore(config.RESEARCH_DIR, args.model).load_all()
    companies, _ = build_verified(load_companies(MERGED_FILE), records, PageStore(config.PAGES_DIR))
    results = compare(read_truth(EVAL_TEMPLATE), companies)
    correct, total = sum(r.correct for r in results), sum(r.total for r in results)
    share = 100 * correct / total if total else 0
    log.info("Accuracy of %s: %d/%d fields (%.0f%%)", args.model, correct, total, share)
    for r in results:
        log.info("  %-18s %d/%d %s", r.field, r.correct, r.total, "; ".join(r.misses))


def read_ids(path: Path) -> set[str]:
    """One company id per line; blank lines and # comments ignored."""
    lines = path.read_text(encoding="utf-8").splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


STEPS: dict[str, Callable[[argparse.Namespace], None]] = {
    "collect": run_collect,
    "merge": run_merge,
    "research": run_research_step,
    "verify": run_verify,
    "export": run_export,
    "all": run_all,
    "eval-template": run_eval_template,
    "evaluate": run_evaluate,
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
        "--limit",
        type=int,
        help=f"companies per research run (research: {config.BATCH_SIZE}, all: no limit)",
    )
    parser.add_argument("--ids", type=Path, help="file of company ids to research (one per line)")
    parser.add_argument("--refresh", action="store_true", help="all: collect sources again")
    args = parser.parse_args()
    if args.limit is None and args.step == "research":
        args.limit = config.BATCH_SIZE
    load_dotenv()
    setup_logging()
    STEPS[args.step](args)


if __name__ == "__main__":
    main()
