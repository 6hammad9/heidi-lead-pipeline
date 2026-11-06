# KPI List — Heidi Systems Lead Qualification

Column specification for the lead sheet. Derived from RULEBOOK.md
(GQM → SMART → three tests → weighted scoring). Each KPI states what is
recorded, where to find it, allowed values and how it is scored.

## 1. Scored KPIs (weighted average → Base 0–5)

| # | KPI | GQM question | Tier / Weight | Segment |
|---|---|---|---|---|
| K1 | Units managed | Q1 Metering volume | Critical / 3 | Firmographic |
| K2 | Residential share | Q2 HeizkostenV relevance (proxy) | Important / 2 | Firmographic |
| K3 | Buyer type | Q3 Who signs | Important / 2 | Firmographic |
| K4 | Software Heidi integrates with | Q4 Onboarding ease | Useful / 1 | Technographic |

Total weight when all known: 8.

### K1 — Units managed
- **Records:** number of units (Einheiten / Wohneinheiten / WE / VE) the
  company manages, plus a status: `Published` / `Estimated` / `Unknown`.
- **Where:** company website (Über uns, Startseite, Leistungen), press
  releases, LinkedIn "About", industry lists.
- **Search terms:** "Einheiten", "Wohneinheiten", "WE", "verwalten über".
- **Estimated:** only via the calibrated employees- or properties-to-units
  ratio (RULEBOOK → Unit estimation).
- **Score:** quintiles of *published* values → 1 (smallest 20%) to 5
  (largest 20%). Estimated values are scored on the same bands.
  Unknown → not scored.
- **Label:** Evidence (E1: Heidi prices per unit per year).

### K2 — Residential share
- **Records:** `Mainly residential` / `Mixed` / `Mainly commercial`.
- **Where:** stated portfolio split if published; otherwise the list of
  services (WEG-Verwaltung, Mietverwaltung, Gewerbeverwaltung).
- **Classification rule:** stated split wins. Without one: only
  WEG/Miet services → Mainly residential; commercial listed alongside
  residential with no stated focus → Mixed; commercial/office focus
  stated → Mainly commercial.
- **Score:** 5 / 3 / 1. Unknown → not scored.
- **Label:** Proxy, not a legal claim. HeizkostenV covers centrally
  heated buildings with several users, commercial included.

### K3 — Buyer type (who signs the metering contract)
- **Records:** one of the types below.
- **Where:** website (services for third-party owners vs. own stock),
  legal form (eG = cooperative), ownership (Land Berlin).
- **Classification rule:** focus is taken from a stated portfolio split,
  otherwise from the services list. If a third-party manager's focus is
  unclear or balanced → `Third-party, mainly WEG` (conservative: the
  owners' resolution step applies to part of the portfolio).

| Type | Score | Label |
|---|---|---|
| Third-party manager, mainly Mietverwaltung | 5 | Evidence (E4) + Assumption |
| Third-party manager, mainly WEG / unclear | 4 | Evidence (E3) |
| Cooperative (eG) | 3 | Assumption |
| Private landlord managing own stock (e.g. listed housing companies) | 3 | Assumption — not researched |
| Municipal housing company | 2 | Evidence for WBM/HOWOGE (E6, E7); Assumption for others |

### K4 — Software Heidi integrates with
- **Records:** `Yes` + name (Domus, Immoware24, Wodis Sigma, Immocloud) /
  `Other` + name / `Unknown`.
- **Where:** tenant/owner portal links on the website, job ads
  ("Kenntnisse in …"), software vendors' customer references.
- **Score:** Yes = 5, Other = 2, Unknown → not scored.
- **Label:** Evidence (E2: integration list); Assumption: integration
  raises win-probability.

## 2. Bonus signals (outside the average, can only add)

| # | Signal | Records | Where | Bonus |
|---|---|---|---|---|
| B1 | Association membership | BVI / IVD / VDIV (which) or blank | Logos on website, association member searches (IVD Verwaltersuche) | +3 if any |
| B2 | Growth signal | What + date | Job ad for property-management roles in the last 90 days (StepStone, Indeed, careers page), or expansion/acquisition news in the last 12 months | +3 if any |

Blank means "not found", never "no". Both labelled Assumption
(correlation unproven).

## 3. Output columns

| Column | Formula / values |
|---|---|
| **Lead Score** (0–100) | Base × 18.8 + B1 + B2, where Base = Σ(weight × score) / Σ(weight of known KPIs) |
| **Data Completeness** | Σ(weight of known K1–K4) / 8, as % |
| **Confidence** | `Low` if completeness < 50% or K1 = Unknown; otherwise `OK` |
| **Contact Status** | `Named + email` / `Named + LinkedIn` / `Named only` / `Generic only` / `None` |

## 4. Contact columns (bonus task)

- **Records:** name, role, email, LinkedIn URL, source URL.
- **Target role (Assumption):** small firms → managing director
  (Geschäftsführer); larger firms → head of operating-cost billing
  (Betriebskosten-/Heizkostenabrechnung), technical department or
  property management.
- **Email rule:** only emails found published (website, Impressum,
  team page) count as `Named + email`. Pattern-guessed addresses
  (vorname.nachname@…) are not entered as fact; at most noted as
  `pattern, unverified`.

## 5. Info columns (not scored)

| Column | Purpose |
|---|---|
| Company name, legal form | Identification |
| Website, address, district, phone, general email | Basic data |
| Employees, number of properties | Inputs for K1 estimation only |
| Remote reading / UVI mentioned | Sales context for the "why now" pitch |
| Current metering provider (if found) | Sales context; e.g. "Ablesung durch ista/Techem/Brunata" on tenant FAQ pages |
| Source URLs | Every filled KPI traceable to a source |
| Last verified (date) | Freshness, SMART "time-bound" |
| Layer | `Broad` (auto-filled) or `Verified` (top tier, checked by hand) |
