# Heidi Systems Case Study — Rulebook / Methodology

Living document of the approach agreed with the user for this case study
(find & qualify Berlin property management companies for Heidi Systems,
a metering/utility-billing service provider). Decisions get added here as
we make them, so the final write-up (Task 3) can be drawn from this file.

## Context recap

- Heidi Systems = metering service provider (heating/water consumption
  metering + billing under the Heizkostenverordnung). Customers are
  Hausverwaltungen (property management companies), not tenants.
- Deliverables: (1) list of Berlin Hausverwaltungen, Google Sheet/Excel,
  (2) qualifying KPIs filled in per company, (3) bonus: real named
  contact + email/LinkedIn per company, (4) short doc explaining
  sources/tools/validation approach.
- Deadline: Tue 2026-11-10, 18:00 Berlin time.

## Step 1 — How we derive KPIs (locked in)

We are NOT picking KPIs ad hoc from whatever data is easy to find. We use:

### a) Goal-Question-Metric (GQM)
1. **Goal** — Identify which Berlin Hausverwaltungen are the
   highest-value, most winnable leads for a metering service.
2. **Questions** — what we need to know to answer it:
   - Q1 How much metering volume could this company generate?
   - Q2 Is their portfolio covered by HeizkostenV billing duties?
   - Q3 Who signs the metering contract, and how easily can we win it?
   - Q4 How easily could they onboard onto Heidi?
   - Q5 Is there a reason for them to act now?
3. **Metrics (KPIs)** — one concrete, measurable KPI per question.

### b) SMART test (vetting each candidate KPI)
Specific / Measurable / Achievable / Relevant / Time-bound. Anything that
fails Measurable or Achievable gets demoted to an info column or dropped.

### c) Firmographic / Technographic / Behavioral segmentation
Standard B2B lead-scoring categorization. Every KPI lands in one of:
- **Firmographic** — company facts: size, portfolio, company type.
- **Technographic** — tools/tech they already run: property software,
  remote-reading meters.
- **Behavioral/intent** — activity signals: hiring, growth, association
  membership, recent news.

### d) Explicitly NOT used (and why)
- **BANT / MEDDIC** — qualify a deal already in conversation with a known
  buyer. We're scoring a cold list, so these don't apply yet.

## Step 2 — Importance tiering

Three tests per candidate KPI:
1. **Correlation** — does it actually move deal size / win-probability?
2. **Discriminating power** — does it vary across companies?
3. **Data feasibility** — can we reliably get/verify it for most
   companies, not guess it?

Tiers: **Critical** (strong on correlation + discrimination),
**Important** (moderate), **Useful** (adds real context, weaker or
unproven correlation), **Good to have** (tie-breaker only).

### No double counting
One KPI per underlying concept. Units managed, number of properties and
employee count all measure size, so only **units managed** is scored.
Properties and employees are kept as inputs to estimate units when a
company doesn't publish them.

### Lead quality ≠ actionability
Whether we found a contact says nothing about how good a customer the
company would be. The sheet has two separate outputs:
- **Lead Score** — how good a customer they would be.
- **Contact Status** — whether sales can act on it yet (named person +
  email / LinkedIn only / generic only / none).

## Step 3 — Scoring mechanism (weighted scoring model)

1. Weight per tier: Critical=3, Important=2, Useful=1. Good-to-have
   signals are NOT in the weighted average (see Bonus signals).
2. Each KPI value maps to a 0–5 sub-score (scales below, each with a
   stated reason).
3. **Base = Σ(weight × sub-score) / Σ(weight of known KPIs)** → 0–5.
4. **Lead Score = Base × 18.8 + Bonus** → base part max 94, bonus max 6,
   total 0–100, single sortable column.

### Bonus signals (positive-only)
Signals we can only observe when present (membership, growth) must never
lower a score. Inside a re-normalised average, a found signal scored
below the company's current average would pull it down (e.g. all KPIs 5
→ 100; add membership = 4 → ~98). So they sit outside the average as
flat bonus points: membership +3, growth signal +3. The base is scaled
to 94 instead of capping the total at 100, so the bonus still breaks
ties at the very top.

### Missing-data rule (decided)
- "Unknown" is never scored as 0 — that would rank small, transparent
  companies above big, quiet ones.
- Unknown KPIs are dropped from both numerator and denominator, and the
  score is re-normalised over the KPIs we do know.
- A **Data Completeness** column (% of scored KPI weight known; bonus
  signals excluded, they can never be "known absent") sits next to the
  score.
- **Low confidence** flag if completeness < 50% **or** units managed is
  unknown and can't be estimated. Size is the most important KPI; without
  it, buyer type + residential share alone (both nearly always findable)
  would give 94 with no idea of size.
- Estimated values (e.g. units estimated from employees) are marked
  **Estimated** in the sheet, never shown as published figures.

### Unit estimation (fallback)
When units aren't published: estimate from employees or number of
properties using a ratio **calibrated from companies in our own dataset
that publish both** (Evidence from our data, not an industry rule of
thumb). Ratio and sample size get documented here once computed, and the
write-up states the sample size ("based on N companies publishing
both"). If N < 10, the write-up carries an explicit warning.
- Unit bands for scoring are set from **published values only**, so
  estimates don't shape the scale they're scored on.

## Standing rule — every score needs a stated reason

- No KPI score or scoring scale goes in without a written reason linked
  to its GQM question.
- Every reason is labelled **Evidence** (with source) or **Assumption**
  (not yet verified).
- Assumptions are listed openly in the final write-up, not presented as
  facts.

## Evidence log

| # | Finding | Label | Source |
|---|---|---|---|
| E1 | Heidi prices per housing unit per year, installation free | Evidence | heidisystems.com/blog/messdienstleister |
| E2 | Heidi integrates with Domus, Immoware24, Wodis Sigma, Immocloud | Evidence | heidisystems.com/blog/messdienstleister |
| E3 | WEG: owners decide on the metering provider by resolution, usually on the manager's proposal; manager can't switch provider alone | Evidence. Legal basis is **§ 19 WEG** (ordinary management by resolution, WEMoG version since 1 Dec 2020). Heidi's blog cites § 21, which since the reform covers costs of structural changes — outdated citation. | heidisystems.com/blog/messdienstleister; buzer.de/19_WEG.htm; lexetius.com/WEG/21 |
| E4 | Rental property: landlord decides, or the manager if contractually authorised | Evidence | heidisystems.com/blog/messdienstleister |
| E5 | Many existing metering contracts run up to 10 years | Evidence (Heidi's own claim) | heidisystems.com/blog/messdienstleister |
| E6 | WBM handles metering management via in-house subsidiary MMB Multi-Media Berlin (job post Oct 2026) | Evidence | WBM job posting via search |
| E7 | HOWOGE Wärme GmbH ran metering in-house for some new builds (old tender, ~9 years) | Evidence, dated | bauportal-deutschland.de Los-ID 1333040 |
| E8 | No metering tenders found for degewo, Gewobag, GESOBAU, STADT UND LAND | Not found — absence of evidence, not proof | one extended search |
| E9 | HeizkostenV: existing non-remote-readable meters must be retrofitted/replaced by **31 Dec 2026**; once remote-readable, monthly consumption info (UVI, § 6a) is mandatory | Evidence (several sources agree; some are metering vendors with an interest — check final wording on gesetze-im-internet.de before quoting) | haufe.de UVI-Fristen; oekotest.de; ista.com blog; Techem EED flyer |
| E10 | If not retrofitted, tenants may cut their heating/hot-water cost share by 3% (§ 12 HeizkostenV) | Evidence (same caveat as E9) | oekotest.de |
| E11 | Several directories block automated access (jacasa.de 403, reviewhero.io 410) | Evidence (observed) | own fetch attempts |
| E12 | VDIV publishes no member list; its "Verwaltersuche" is only a request form for owners. Membership has to come from logos/mentions on company websites | Evidence | vdiv.de/verwaltersuche |
| E13 | OSM run 2026-11-06: 95 entries, 88 distinct, 51 with website. Includes branch offices of the same company (degewo, Deutsche Wohnen) and wrong websites (HOWOGE entry links to a third-party directory) — dedupe and the agent must not trust OSM websites blindly | Evidence (observed) | data/raw/osm_20261106-210934.json |

## "Why now" argument for Heidi

E9 + E10: the remote-reading deadline is 31 Dec 2026, about 8 weeks from
today (2026-11-06). Managers whose buildings still have non-remote meters
face a hard deadline and tenant cost cuts. Combined with E5 (long
contracts), the retrofit is a natural moment to switch providers —
**Assumption**: that managers actually reconsider the provider at
retrofit time rather than letting the incumbent swap devices.

## Final KPI set

### Scored KPIs (feed the Lead Score)

| KPI | GQM | Tier | Segment | Scale (0–5) | Label |
|---|---|---|---|---|---|
| Units managed | Q1 | Critical | Firmographic | Quantile bands from published values only | Evidence: revenue is per unit (E1) |
| Residential share of portfolio | Q2 | Important | Firmographic | Mainly residential = 5, mixed = 3, mainly commercial = 1 | **Proxy**, not a legal claim: HeizkostenV applies to centrally heated buildings with several users, commercial included. Assumption: residential portfolios contain more such buildings. Demoted from Critical — most Hausverwaltungen are mainly residential, so it discriminates weakly |
| Buyer type (who signs) | Q3 | Important | Firmographic | See table below | Mixed — see table |
| Uses software Heidi integrates with | Q4 | Useful | Technographic | Yes = 5, other software named = 2, unknown = not scored | Evidence: integration list (E2); Assumption: integration raises win-probability |

#### Bonus signals (outside the average, can only add)

| Signal | GQM | Segment | Bonus | Label |
|---|---|---|---|---|
| Association membership (BVI/IVD/VDIV) | Q3 | Behavioral | +3 | Assumption: professionalism/channel signal, correlation unproven |
| Growth signal (hiring, expansion) | Q1 | Behavioral | +3 | Assumption |

Q5 ("reason to act now") has no scored KPI: it's answered by the
remote-reading info column and the "why now" argument, which applies to
the whole market.

#### Buyer-type scale (Q3)

| Company type | Score | Reason | Label |
|---|---|---|---|
| Third-party manager, mainly Mietverwaltung | 5 | Can sign for the owner when authorised (E4); one relationship covers many owners | Evidence (E4) + Assumption (manager usually has authority) |
| Third-party manager, mainly WEG | 4 | Manager proposes, owners decide by § 19 resolution (E3): strong influence, extra approval step | Evidence (E3) |
| Third-party manager, focus unclear/balanced | 4 | Conservative: owners' resolution step applies to part of the portfolio | Rule (decided) |
| Cooperative (Genossenschaft) | 3 | Owns and manages its own stock, single decision-maker | Assumption — not researched |
| Private landlord managing own stock | 3 | Same logic as cooperatives; may have central/national framework contracts | Assumption — not researched |
| Municipal housing company | 2 | At least two run metering in-house or via subsidiaries (E6, E7); likely formal procurement | Evidence for WBM/HOWOGE only; Assumption for the other four |

### Info columns (not scored)

| Column | Why not scored |
|---|---|
| Contact Status + contact name/role/email/LinkedIn | Actionability, not lead quality (see Step 2) |
| Data Completeness % / Low-confidence flag | Meta-information about the score |
| Employees, number of properties | Inputs for unit estimation only (no double counting) |
| District / address | Every company is in Berlin; nothing in the evidence says district matters to Heidi (fails correlation test) |
| Remote reading / monthly consumption info (UVI) mentioned on website | Silence isn't information (missing-data rule), and almost every company will be "not mentioned", so it fails the discrimination test. Kept as sales context for the "why now" pitch |
| Current metering provider (if found, e.g. "Ablesung durch ista/Techem/Brunata" on tenant FAQ pages) | Useful for sales, but score direction unclear: an incumbent may be locked in (E5) or facing a retrofit switch moment (E9) — Assumption either way |

## Scope (decided) — two layers

1. **Broad list, target 300+ companies** — basic data (name, website,
   address, type) with KPIs filled automatically where possible.
   Shows the automation, which is the point of the AI Agent Builder role.
2. **Verified top tier, ~40–60 companies** — data checked by hand,
   named contacts researched (bonus task).

## Pipeline (decided 2026-11-06)

Principle: **LLM where judgement is needed, code where exactness is
needed.** The LLM never calculates scores.

```
1. Collect   (code)  Google Places (breadth) + OpenStreetMap
                     (office=property_management) + VDIV Berlin-Brandenburg
                     member list (quality + fills membership bonus)
2. Dedupe    (code)  website domain first, then normalised name
3. Impressum (code)  scrape /impressum: managing director, address,
                     register number — cheap waterfall step before the agent
4. Agent     (LLM)   researches only what's still missing (units, portfolio,
                     buyer type, software, growth, contacts). Tools:
                     web_search, web_fetch (Anthropic-hosted), submit_record
                     (rejects any value without source URL + quote)
5. Verify    (code)  re-fetch each source URL, check the quote is on the
                     page (whitespace-normalised, fuzzy match); fail → value
                     becomes Unknown. Report "X% of agent claims verified".
6. Score     (code)  rulebook formula
7. Export    (code)  Excel + KPI definitions tab
```

- **Google Places:** used for discovery. In production, stored data would
  come from the companies' own websites (Google's terms restrict storing
  Places content beyond place IDs) — which the pipeline already does.
  Billing account with a budget alert; check current free quotas.
- **Model:** decided by measurement, not guessing. Saturday: same 10
  hand-checked companies with Haiku 5.5 and Sonnet 5.5; compare accuracy
  and tokens (Haiku price rises above 100K input tokens per request).
  Winner runs the full list; optionally Opus 5.5 for the top 40–60.
  Check live prices before relying on estimates; web search is billed per
  search.
- **API key:** spending limit set in the Anthropic console.
- **Robustness:** checkpoint every company's result to disk as it
  finishes; run in batches of ~50, review the first batch before the rest.
- **Access:** respect robots.txt and rate limits; sites that block
  automated access are skipped and noted, never worked around (E11).

## Open decisions / not yet locked

- Deliverable format: Excel (.xlsx) — no Google Sheets/Drive connector
  available in this environment, user can import to Sheets themselves.
  Write-up as an Artifact (shareable webpage).
