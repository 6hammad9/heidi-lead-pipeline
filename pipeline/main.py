"""Entry point: runs pipeline steps in order. Usage: python -m pipeline.main <step>"""

import argparse
import logging
from collections.abc import Callable

from dotenv import load_dotenv

from pipeline import config
from pipeline.collectors.osm import collect_osm
from pipeline.models import Company
from pipeline.utils.http import HttpClient
from pipeline.utils.io import save_companies
from pipeline.utils.logging_setup import setup_logging

log = logging.getLogger(__name__)

COLLECTORS: dict[str, Callable[[HttpClient], list[Company]]] = {
    "osm": collect_osm,
}


def run_collect() -> None:
    client = HttpClient()
    for name, collector in COLLECTORS.items():
        try:
            companies = collector(client)
        except Exception:
            log.exception("Collector %s failed, continuing with the others", name)
            continue
        save_companies(config.INTERIM_DIR / f"collected_{name}.json", companies)


STEPS: dict[str, Callable[[], None]] = {
    "collect": run_collect,
}


def main() -> None:
    parser = argparse.ArgumentParser(description="Heidi lead pipeline")
    parser.add_argument("step", choices=STEPS)
    args = parser.parse_args()
    load_dotenv()
    setup_logging()
    STEPS[args.step]()


if __name__ == "__main__":
    main()
