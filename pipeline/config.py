"""All tunable values and rulebook numbers. Logic modules import from here, never hard-code."""

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
INTERIM_DIR = DATA_DIR / "interim"
LOG_DIR = DATA_DIR / "logs"
OUTPUT_XLSX = ROOT / "output" / "heidi_leads_berlin.xlsx"

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

# Research agent (RULEBOOK → Budget constraint: €5 prepaid Anthropic credit)
AGENT_MODEL = "claude-haiku-5-5"  # the only model whose full run fits the budget
AGENT_EFFORT = "medium"  # Haiku 5.5 default, set explicitly; revisit after the accuracy test
AGENT_MAX_TOKENS = 8000  # per response; adaptive thinking counts toward it
AGENT_MAX_TURNS = 6  # API calls per company, including corrected resubmissions
AGENT_MAX_FETCHES_PER_COMPANY = 4  # pages the agent may request beyond the prefetched ones
AGENT_MAX_SUBMIT_CORRECTIONS = 1  # then invalid claims are nulled and the rest is kept
AGENT_MAX_COST_PER_COMPANY_USD = 0.05  # Haiku expected ~$0.003/company; stops runaway loops
AGENT_RUN_BUDGET_USD = 4.00  # all Anthropic spend in the ledger, kept below the €5 credit
SPEND_LEDGER = DATA_DIR / "anthropic_spend.jsonl"
# Automatic quality gate (RULEBOOK → Automation principle): checked once per run after this many
# researched companies; outside a limit the run stops itself before spending more.
GATE_AFTER_COMPANIES = 25
GATE_MAX_FAILURE_RATE = 0.2  # errors, turn/cost caps, invalid or refused submissions
GATE_MIN_VERIFIED_RATE = 0.8  # agent claims whose quote code finds on the cited page
GATE_MAX_UNKNOWN_RATE = 0.95  # almost nothing found suggests broken fetching or prompt
GATE_MAX_AVG_COST_USD = 0.01  # per researched company (measured ~$0.002)
# Researched first (name contains one of these), so a budget stop cuts the least likely leads.
RESEARCH_PRIORITY_NAME_KEYWORDS = [
    "verwalt",
    "property management",
    "immobilienmanagement",
    "genossenschaft",
    "wohnungsbau",
]  # append-only, one line per API call
RESEARCH_DIR = INTERIM_DIR / "research"  # one checkpoint per company, per model
PAGES_DIR = DATA_DIR / "pages"  # page texts exactly as the agent saw them (quote checks)

# USD per million tokens, platform.claude.com/docs/en/about-claude/pricing, checked 2026-11-06.
# cache_write = 5-minute TTL writes.
MODEL_PRICES = {
    "claude-haiku-5-5": {"input": 0.10, "cache_write": 0.125, "cache_read": 0.01, "output": 0.50},
    "claude-sonnet-5-5": {"input": 2.00, "cache_write": 2.50, "cache_read": 0.10, "output": 10.00},
    "claude-opus-5-5": {"input": 4.00, "cache_write": 5.00, "cache_read": 0.20, "output": 20.00},
}
# Haiku 5.5 bills a whole request on a higher rate card when its prompt exceeds 100K tokens.
LONG_PROMPT_PRICES = {
    "claude-haiku-5-5": (
        100_000,
        {"input": 0.50, "cache_write": 0.625, "cache_read": 0.05, "output": 2.50},
    ),
}

# Page fetching for the agent (own code instead of paid web search; robots.txt respected)
PREFETCH_MAX_PAGES = 6  # homepage + up to 5 linked pages picked by keyword group
# Keyword groups in priority order; one link per group (matched in URL path or link text).
PREFETCH_KEYWORD_GROUPS = [
    ["impressum"],
    ["ueber-uns", "uber-uns", "über-uns", "about", "unternehmen", "wir-ueber-uns"],
    ["leistungen", "verwaltung", "service", "angebot"],
    ["team", "ansprechpartner", "mitarbeiter"],
    ["karriere", "jobs", "stellen"],
]
PAGE_TEXT_MAX_CHARS = 8000  # per page after HTML cleaning; keeps prompts far below 100K tokens
PAGE_MAX_BYTES = 2_000_000
PAGE_LINKS_MAX = 60  # links listed to the agent per company
QUOTE_MAX_CHARS = 300
QUOTE_MATCH_MIN_SCORE = 90  # rapidfuzz partial_ratio when an exact (normalised) match fails

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
RESIDENTIAL_SHARE_SCORES = {"mainly_residential": 5, "mixed": 3, "mainly_commercial": 1}
# Buyer-type scale (RULEBOOK → Company-type scoring); not_property_manager is excluded.
BUYER_TYPE_SCORES = {
    "third_party_rental": 5,
    "third_party_weg": 4,
    "third_party_unclear": 4,
    "cooperative": 3,
    "private_landlord": 3,
    "municipal": 2,
}
INTEGRATED_SOFTWARE = ["domus", "immoware24", "wodis", "immocloud"]  # Heidi integrations (E2)
SOFTWARE_SCORES = {"integrated": 5, "other": 2}
UNIT_ESTIMATION_MIN_SAMPLE = 3  # companies publishing both values before a ratio is used
