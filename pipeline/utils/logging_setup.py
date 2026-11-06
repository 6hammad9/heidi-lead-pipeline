"""Log to console and to a dated file in data/logs/."""

import logging
from datetime import datetime

from pipeline import config


def setup_logging(level: int = logging.INFO) -> None:
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_file = config.LOG_DIR / f"pipeline_{datetime.now():%Y%m%d}.log"
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(log_file, encoding="utf-8")],
    )
