# Heidi Lead Pipeline: Berlin Hausverwaltungen

An automated pipeline that finds Berlin property management companies (Hausverwaltungen),
has an AI agent research each company's website, checks every claim the agent makes against
the page it came from, and scores each company as a lead for a metering service provider.

Built for the Heidi Systems *AI Agent Builder* case study.

| Result of the full run (7 Nov 2026) | |
|---|---|
| Unique Berlin companies | 2,080 |
| Websites researched by the agent | 1,563 |
| Agent claims confirmed on the cited page | 96% (3,945 / 4,127) |
| Named contacts confirmed | 95% (1,601 / 1,686) |
| Total AI cost (Claude Haiku 5.5) | $2.93 (about $0.002 per company) |
| Google Places requests | 157 (free tier) |

- Methodology and every decision with its source: [RULEBOOK.md](RULEBOOK.md)
- Column-by-column KPI spec: [KPI_LIST.md](KPI_LIST.md)
- Write-up for the case study: [docs/writeup.tex](docs/writeup.tex)
- Presentation: [docs/presentation.tex](docs/presentation.tex)
- Coding standards: [CLAUDE.md](CLAUDE.md)

## How it works

The AI does what needs judgement; code does what needs to be exact. The AI reads websites and
extracts facts. It never calculates a score.

| Step | Done by | What happens |
|---|---|---|
| 1. Collect | code | Google Places Text Search, with Berlin split into map cells; OpenStreetMap Overpass |
| 2. Merge | code | Duplicates merged by website domain, then by normalised name |
| 3. Fetch | code | Up to 6 pages per site (home, Impressum, about, services, team, careers); robots.txt respected |
| 4. Research | AI | Claude reads the pages, may fetch up to 4 more on the same site, and submits each fact with its source URL and a word-for-word quote |
| 5. Verify | code | Every quote is checked against the page text. If it fails, the value becomes unknown |
| 6. Score | code | Weighted lead score from the rulebook (pure functions) |
| 7. Export | code | `output/heidi_leads_berlin.xlsx` with Leads, KPI definitions and Run log tabs |

Guardrails:
- A $4 total budget and $0.05 per-company limit, read from a spend ledger.
- A quality gate after 25 companies: the run stops itself if failure rate, verification rate or cost is out of range.
- Every company is checkpointed as soon as it finishes, so restarts skip finished work.
- One failing company never stops the run.

## Setup

Requires Python 3.12+ (developed on 3.14) on Windows. From the project folder:

```powershell
py -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
```

Then put your keys in `.env`. It's git-ignored, so the keys never leave your machine.

| Variable | Needed for |
|---|---|
| `ANTHROPIC_API_KEY` | the research step |
| `GOOGLE_PLACES_API_KEY` | collecting from Google Places |
| `GOOGLE_SHEET_ID`, `GOOGLE_SERVICE_ACCOUNT_FILE` | optional: also write the results to a Google Sheet |

## Running

Every command starts with `.venv\Scripts\python -m pipeline.main`, followed by the step name.

| Command | What it does | Cost |
|---|---|---|
| `... all` | The whole pipeline in one go. Collects only if nothing is collected yet; researches only companies not done yet | AI credit for new companies only |
| `... all --refresh` | Same, but collects from Google and OpenStreetMap again | Google requests + AI credit |
| `... collect` | Collect from all sources (`--sources google_places osm` to choose) | Google requests |
| `... merge` | Merge duplicates into one list | free |
| `... research` | Research the next 50 companies (`--limit N`, `--ids file.txt`, `--model claude-sonnet-5-5`) | AI credit |
| `... verify` | Re-check every quote against its page | free |
| `... export` | Score and write the Excel file (close it in Excel first) | free |
| `... eval-template` | Pick 10 companies and create a blank sheet to check by hand | free |
| `... evaluate` | Compare the agent's answers with the hand-checked sheet (`--model` to choose the model) | free |

Press Ctrl+C to stop at any time. Nothing is lost, and the next run continues where it stopped.
Logs go to the console and to `data/logs/`.

To try the pipeline without paying for Google, set `GOOGLE_PLACES_DRY_RUN=1` and collect.

## Tests and linting

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\ruff check . --fix; .venv\Scripts\ruff format .
```

The 247 tests cover the exact parts: scoring, merging, URL handling, HTTP retries, the agent
loop (with a fake model), quote verification, budget and quality gate. The LLM's own judgement
is measured by the hand-checked accuracy test, not by unit tests.

## Project structure

```
pipeline/
  main.py              one entry point; runs the steps in order
  config.py            every number: models, weights, budgets, limits, prices
  models.py            the one schema: Company, Fact (value + status + source + quote), Contact
  collectors/
    google_places.py   map-cell search of Berlin; free ID-only search, billed details only where needed
    osm.py             OpenStreetMap office=property_management, with mirror fallback
  dedupe.py            merges duplicates; result doesn't depend on input order
  fetching/
    fetcher.py         polite page fetcher: robots.txt, safe redirects, size limit
    robots.py          robots.txt rules per site
    html_text.py       HTML to clean text; picks the useful subpages
    page_store.py      cache of fetched pages (the exact text the agent saw)
  agent/
    research_agent.py  the agent loop: one company in, one research record out
    prompt.py          system prompt: KPI definitions and evidence rules
    tools.py           fetch_page (same site only) and submit_record
    schema.py          strict schema for what the agent submits
    validation.py      rejects claims without URL and quote
    cost.py, ledger.py token cost and the append-only spend ledger
    contracts.py       small interfaces between the parts
  research_step.py     picks the order, enforces budget, runs the quality gate
  checkpoint.py        saves each company's result; skips it on restart
  apply_research.py    turns an agent submission into Company facts
  verify.py            checks every quote against its page
  verify_step.py       applies the verification to all companies
  scoring.py           the lead score (pure functions)
  quality_gate.py      the automatic stop rule
  evaluation.py        accuracy against hand-checked answers
  export/
    table.py           rows and columns for the sheet
    excel.py           Excel file
    google_sheets.py   optional Google Sheets export
  utils/               HTTP client with retries, URL normalising, file I/O, logging
tests/                 pytest, one file per module
data/                  (not in git) raw collections, pages, research records, logs
output/                (not in git) the Excel file
```

`data/` and `output/` stay out of the repository on purpose: they contain names and contact
details of real people.
