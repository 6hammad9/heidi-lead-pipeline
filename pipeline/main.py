"""Entry point: runs pipeline steps in order. Usage: python -m pipeline.main <step> [options]"""

import argparse
import logging
from collections.abc import Callable

from dotenv import load_dotenv

from pipeline import config
from pipeline.collectors.google_places import collect_google_places
from pipeline.collectors.osm import collect_osm
from pipeline.dedupe import merge_companies
from pipeline.models import Company
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
        save_companies(config.INTERIM_DIR / f"collected_{name}.json", companies)


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


STEPS: dict[str, Callable[[argparse.Namespace], None]] = {
    "collect": run_collect,
    "merge": run_merge,
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
    args = parser.parse_args()
    load_dotenv()
    setup_logging()
    STEPS[args.step](args)


if __name__ == "__main__":
    main()
