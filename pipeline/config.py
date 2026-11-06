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

# Google Places API (New), Text Search. Used for discovery; stored data comes from company sites.
GOOGLE_PLACES_TEXT_SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
GOOGLE_PLACES_QUERIES = ["Hausverwaltung"]
# Two phases: a free exploration (IDs-only field mask, "Text Search Essentials (IDs Only)",
# unlimited) finds cells that fit in one query; only those are searched with the billed
# Enterprise mask (website/phone).
# Billed requests per calendar month across all runs (earlier runs counted from data/raw/).
# Enterprise free quota is 1,000/month, the margin absorbs timeout retries Google may also bill.
GOOGLE_PLACES_MAX_REQUESTS = 900
GOOGLE_PLACES_MAX_FREE_REQUESTS = 3000  # per run; free, only a guard against runaway splitting
# Env var: "1" = explore and log the plan only, zero billed requests. Read when the collector
# runs (never at import), so a value from .env or the shell always takes effect.
GOOGLE_PLACES_DRY_RUN_ENV = "GOOGLE_PLACES_DRY_RUN"
BERLIN_BBOX = {"low": (52.3382, 13.0883), "high": (52.6755, 13.7611)}  # (lat, lng)
GOOGLE_PLACES_MIN_CELL_DEGREES = 0.005  # ~550 m; stop splitting below this
GOOGLE_PLACES_PAGE_SIZE = 20  # API maximum; fewer pages = fewer billed requests
GOOGLE_PLACES_MAX_PAGES = 3  # API returns at most 60 results (3 x 20) per query
GOOGLE_PLACES_LANGUAGE_CODE = "de"
GOOGLE_PLACES_REGION_CODE = "DE"  # two-letter CLDR code

# Deduplication
SOURCE_PRIORITY = ["google_places", "osm"]  # first non-empty field wins in this order
# Websites on these domains belong to a platform, not the company: never merge on them.
PLATFORM_DOMAINS = [
    "facebook.com",
    "instagram.com",
    "linkedin.com",
    "xing.com",
    "google.com",
    "goo.gl",
    "business.site",
    "hilfelotse-berlin.de",
    "immobilienscout24.de",
    "immowelt.de",
    "gelbeseiten.de",
    "11880.com",
    "dasoertliche.de",
    "dastelefonbuch.de",
    "jimdosite.com",
    "wixsite.com",
    "wordpress.com",
    "t-online.de",
    "web.de",
    "gmx.de",
]
LEGAL_FORM_SUFFIXES = [
    "gmbh & co. kg",
    "gmbh & co kg",
    "ug (haftungsbeschränkt)",
    "gmbh",
    "mbh",
    "ag",
    "kg",
    "ohg",
    "gbr",
    "e.k.",
    "eg",
    "e.v.",
    "ug",
    "partg mbb",
    "partg",
]

# Normalised names too generic to merge on (after legal forms are stripped).
GENERIC_COMPANY_NAMES = [
    "hausverwaltung",
    "hausverwaltung berlin",
    "immobilienverwaltung",
    "immobilienverwaltung berlin",
    "immobilien",
    "verwaltung",
    "property management",
]

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
