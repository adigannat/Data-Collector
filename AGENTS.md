AGENTS.MD
Purpose

This repository implements a repeatable, auditable data-collection pipeline to fulfill an assessment task from GEW LLC:

Using AI tools/agents, provide a list of oil-related companies in the UAE from official online databases and organize the results into a file with:
company name, business activity, telephone, email address, suitable for automated outreach.

The pipeline prioritizes:

Completeness (full scrape where feasible)

Correctness (structured fields, validation, deduplication)

Traceability (source attribution per row, reproducible runs)

Compliance (no bypass of authentication/CAPTCHA; use public data only)

Assessment Context
Target Sources (as provided by the employer)

Ministry of Economy (MoE) Growth portal (UAE national registry): https://www.growth.gov.ae/G2C/

Dubai Chamber of Commerce directory (Siebel portal): https://dcdigitalservices.dubaichamber.com/siebel/app/pseservicesso/enu?SWECmd=GotoView&SWEBHWND=&SWEView=DC+Commercial+Directory+Landing+View&_tid=1769625342&SWETS=1769625342&SWEHo=dcdigitalservices.dubaichamber.com

Dubai Department of Economy & Tourism / DED (public lookup): https://eservices.dubaided.gov.ae/pages/anon/gsthme.aspx?dedqs=PM671p6QBb0lV1okx2JABgxoLLKXOgPx

Sharjah Economic Development Department (SEDD) license search: https://eservices.sedd.ae/eservicesweb/license-transactions/search_license/main-inq-lic.xhtml?lang=en&filterTrdNameEn=

Ground Truth Constraints (Important)

MoE Growth portal requires UAE Pass login → manual intervention required. End-to-end automation is not feasible without user-authenticated sessions.

Sharjah SEDD requires reCAPTCHA click on each search → must be human-in-the-loop; do not attempt to bypass.

Dubai DED “codes → companies” mapping is unclear; DED is better treated as a gap-filler via keyword-based searches rather than activity-code enumeration.

Dubai Chamber provides oil-related activity codes and should be treated as the primary structured entrypoint for “oil-related” discovery in Dubai.

Primary Discovery Set: Dubai Chamber Oil-Related Codes

Use the Dubai Chamber SIC/activity codes containing “oil” as the core search space. Iterate through all codes and collect all result pages for each code (full scrape).
These codes are provided in:

Chamber of Commerce

Codes (oil-related)

K742142 — Oil Exploration Engineering Services

K742133 — Oil Refining Engineering Services

C112010 — Oil Related Services

D281108 — Oil and Gas Fields Equipment Manufacturing

K742154 — Oil and Gas Tanks pipes construction engineering services

C111003 — Oil and Natural Gas Development

K742109 — Oil and Natural Gas Exploration Consultancies

F452014 — Oiland Natural Gas Pipelines Contracting

C112001 — Oil and Natural Gas Well Drilling

C112004 — Oil and Natural Gas Well Equipment Repairing and Maintenance

C112002 — Oil and Natural Gas Well Maintenance

C112003 — Oil and Natural Gas Well Reinforcement Services

G514920 — Oilfield Chemicals Trading

D281116 — Oilfield Drilling Equipment and Components Manufacturing

K742216 — Oilfield High Pressure Equipment Testing

G515906 — Oilfield and Natural Gas Equipment and Spare Parts Trading

D242904 — Oilfield Chemicals Manufacturing

Rule: Treat this code list as the authoritative “oil-related” filter for Dubai Chamber scraping.

Output Requirements
Deliverable file

output/uae_oil_companies.csv

Required columns (minimum)

company_name

business_activity

phone

email

Strongly recommended columns (for auditability and quality)

source (e.g., dubai_chamber, dubai_ded, sharjah_sedd, moe_growth_manual)

emirate (e.g., Dubai, Sharjah, UAE)

activity_code (Dubai Chamber codes)

source_url (deep link to result or detail page if available)

last_seen_utc (timestamp of extraction)

notes (e.g., email_not_listed_publicly, captcha_required, uaepass_required)

CSV must be UTF-8 and safe to open in Excel.

Best Strategy (Recommended Execution Order)
Phase 1 — Dubai Chamber (Primary, “Contact-First”)

Iterate all oil-related codes (above).

For each code:

Execute search

Scrape all results pages (pagination until exhausted)

If details require opening a record, open and scrape detail fields

Extract:

Company name

Business activity / category

Phone (if present)

Email (if present)

Store raw HTML snapshots per page for audit (optional but recommended).

Why: This source is most likely to include phone/email and has structured codes.

Phase 2 — Sharjah SEDD (Human-in-the-loop reCAPTCHA)

Use a controlled set of keywords (example):

oil, petroleum, petro, gas, drilling, refinery, oilfield

For each keyword search:

Agent fills form

Human clicks reCAPTCHA

Agent scrapes results + pagination

Extract:

Company name

Activity (if shown)

Phone/email (if shown; often not)

If phone/email are not visible publicly:

Leave blank

Add a note: contact_not_listed_in_sedd_public_view

Phase 3 — Dubai DED (Gap-Filler)

Do not attempt to find activity codes unless there’s a clear, public mapping to company lists.

Instead:

Run keyword-based company lookups (same keyword set).

Capture:

company name

license identifier (optional internal field)

activity/description (if present)

Merge into dataset:

If company already exists from Chamber, keep Chamber contact fields

If new, add row with blank contacts and notes=ded_public_lookup_no_contact

Phase 4 — MoE Growth (UAE Pass Manual)

If MoE Growth portal access is possible:

Perform manual session login via UAE Pass.

Collect a sample export or small verification set (if no automation possible).

In any case, document:

uaepass_required limitation

what was/was not collected

Do not attempt to bypass UAE Pass authentication.

Automation Approach
Preferred technical approach: Browser Automation

Use Playwright (Python) as the default:

Works across JS-heavy sites

Handles session cookies and pagination reliably

Supports “pause for human action” (reCAPTCHA / UAE Pass login)

Alternative: Selenium is acceptable if Playwright is not available.

Non-goals / prohibited

No captcha bypass tools or services

No credential theft or session hijacking

No scraping behind paywalls/logins unless explicitly performed by the user in the browser

No collecting personal data beyond what is publicly presented (company-level info only)

Data Quality Rules
Normalization

company_name: trim whitespace; preserve original casing as displayed; maintain a normalized variant for dedupe

phone: keep as displayed but also store normalized +971... when possible (optional)

email: must be validated (contains @ and domain-like suffix); if multiple emails, separate by ;

Deduplication (must)

Deduplicate across:

multiple Dubai Chamber activity codes

multiple keywords and sources

Recommended key priority

normalized_company_name + email (strong)

normalized_company_name + phone (strong)

normalized_company_name + emirate (fallback)

Merge precedence

When merging duplicates:

Prefer Dubai Chamber for phone/email if present

Prefer the most explicit business_activity (often NER/registry style if available)

Keep notes unioned (append unique notes)

Validation / sanity checks

Total rows > 0 for each Chamber code (flag any code that returns 0)

Email column should not contain placeholders like N/A unless required; prefer blank + note

Keep a run log: record counts per source and per code

Repo Structure (Recommended)
.
├─ agents/
│ ├─ scrape_dubai_chamber.py
│ ├─ scrape_sharjah_sedd.py
│ ├─ scrape_dubai_ded.py
│ ├─ merge_and_clean.py
│ └─ config.py
├─ input/
│ └─ dubai_chamber_oil_codes.csv
├─ raw/
│ ├─ dubai_chamber/
│ ├─ sharjah_sedd/
│ └─ dubai_ded/
├─ output/
│ └─ uae_oil_companies.csv
├─ logs/
│ └─ run_YYYYMMDD_HHMM.log
└─ AGENTS.MD

Operational Notes for Agents
Dubai Chamber (Siebel portal)

Expect hidden form fields and session tokens.

Prefer “drive the UI” with Playwright:

fill activity code field

submit query

parse results table

click next until disabled

If record detail pages exist, open each result row and extract contact fields there.

Sharjah SEDD (reCAPTCHA)

Use Playwright to fill the search term.

Pause and request user to click reCAPTCHA.

Continue automatically after the checkbox is completed.

If reCAPTCHA appears per search, batch keywords carefully to minimize clicks.

MoE UAE Pass

Treat as manual-only unless an authenticated export endpoint is provided after login.

Document limitations explicitly in notes and/or a short README.

What “Done” Looks Like (Acceptance Criteria)

A successful submission includes:

output/uae_oil_companies.csv with required columns populated where publicly available

Evidence of full scrape from Dubai Chamber across all oil-related codes

Chamber of Commerce

Sharjah SEDD results included (even if partial contacts), with notes indicating captcha constraint

Dubai DED entries included as gap-fillers, with notes indicating contact availability limitations

Clear limitations recorded for MoE UAE Pass requirement

Communication Template (If Needed)

If the employer asks why some emails are missing:

“Email/phone were captured where publicly provided on the official portals. Some registries list license and activity information only and do not publish direct contact details in the public view. Those entries are included for completeness with blank contact fields and a note indicating the limitation.”
