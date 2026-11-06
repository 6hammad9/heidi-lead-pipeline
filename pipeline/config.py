"""All tunable values and rulebook numbers. Logic modules import from here, never hard-code."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
LOG_DIR = DATA_DIR / "logs"

# HTTP
USER_AGENT = "HeidiLeadResearch/0.1 (B2B lead research case study)"
HTTP_TIMEOUT_SECONDS = 30
HTTP_MAX_ATTEMPTS = 4
HTTP_MIN_DELAY_PER_HOST_SECONDS = 1.0

# OpenStreetMap / Overpass
OVERPASS_MIRRORS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]
OVERPASS_TIMEOUT_SECONDS = 180
OVERPASS_NAME_PATTERN = (
    "hausverwalt|immobilienverwalt|grundstücksverwalt|wohnungsverwalt"
    "|objektverwalt|property management"
)

# Agent (RULEBOOK → Pipeline): model decided by the Saturday accuracy test
CANDIDATE_MODELS = ["claude-haiku-5-5", "claude-sonnet-5-5"]
TOP_TIER_MODEL = "claude-opus-5-5"
BATCH_SIZE = 50

# Scoring (RULEBOOK → Step 3 and Final KPI set)
TIER_WEIGHTS = {"critical": 3, "important": 2, "useful": 1}
KPI_TIERS = {
    "units_managed": "critical",
    "residential_share": "important",
    "buyer_type": "important",
    "software": "useful",
}
BONUS_POINTS = {"association": 3, "growth": 3}
BASE_SCALE_FACTOR = 18.8  # base max 5 × 18.8 = 94, leaving 6 points for bonuses
LOW_CONFIDENCE_COMPLETENESS = 0.5
