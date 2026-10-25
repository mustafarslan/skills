# Setup: the seller profile

cure sells for **the user's own organization**. Before any research it needs to know what that organization sells, to whom, and what a prospect with the problem looks like. That lives in the **seller profile**: three files in the working folder.

```
<working folder>/
  cure-profile/
    profile.md        who we are, what we sell, who buys, what to look for
    capabilities.md   what our products do today (CAP-xx) and the gaps (EXT-xx)
    style.md          brand tokens, or "style: neutral"
  cure-runs/
    <YYYY-MM-DD>-<slug>/ …
```

Never store the profile in the skill or plugin folder: an update overwrites it.

**No writable folder** (plain chat on Desktop, web or mobile): run setup anyway, keep the three files in the conversation for this run, and tell the user in one line that the profile will not persist and setup runs again next time. Offer to print the files so they can paste them back.

## When setup runs

| Situation | Do |
|---|---|
| `cure-profile/profile.md` is missing | full setup, before intake |
| The user says "cure setup", or asks to refresh, update or redo the profile | full setup; read the old files first and show what changed |
| `profile.md` exists but `capabilities.md` or `style.md` is missing | set up the missing file only |
| A file's `status` is DRAFT | carry on with the run, ask once whether to confirm it now, and print DRAFT in the report footer |
| The user asks to add a product, fix a capability or change the style | edit that file, bump its version, keep `status` as it was unless they confirm |

## Step 1: ask, in one message

Use a multiple-choice question tool if the surface has one; otherwise a short numbered list.

| # | Question | Default |
|---|---|---|
| 1 | Your organization's name | none |
| 2 | Its website | none |
| 3 | Which products or product lines should cure sell? | all of them |
| 4 | Who buys them, if you know (function and titles) | cure proposes it from the research |
| 5 | Default report language | English |
| 6 | CRM for the CSV export | generic CSV |
| 7 | Markets or regions you sell into (optional) | none |
| 8 | Do you have a style or brand guideline? Paste it, give a URL or a file, or say no | no: neutral style |

If the user's request already answers any of these, pre-fill it and still ask the rest.

## Step 2: research your own organization

The rules in `claims.md` apply to the seller too: **every capability carries a source URL; nothing is invented.**

- **Where agents exist:** dispatch one `cure-researcher` with a **seller self-profile** assignment: the org name, website and product scope from step 1, the absolute paths of `claims.md`, `sources.md` and this file, evidence IDs S100–S199, about 25 searches, and a ledger at `cure-profile/ledger.md` (in the conversation when there is no folder).
- **Where they don't:** do it yourself with the same rules and budget. This is the one case where the orchestrator WebFetches pages itself (the seller's own site and docs); the no-fetch rule in SKILL.md §2 is about prospect research.

Sources, in this order:
1. Product and solution pages, feature lists, docs and help centre, API reference, changelog or release notes.
2. Pricing and plans pages (what is in which plan; what is "contact sales").
3. Case studies and customer stories: who bought, which function, what problem, what changed.
4. Press releases, the newsroom, blog posts announcing features.
5. Filings or annual reports, if the organization is listed.
6. Third-party reviews and analyst pages, as leads only (`*`).

The researcher returns, per product: what it does, the problem it solves in the buyer's words, the buyers named in case studies, the features marked beta, preview, roadmap or "coming soon", and the source URL of each.

## Step 3: draft the three files

### `cure-profile/profile.md`

```markdown
---
profile_version: 1
date: YYYY-MM-DD
status: DRAFT            # DRAFT until the user confirms; then CONFIRMED
org_name: ""
website: ""
report_language: English
crm: generic CSV
---
# Seller profile

## What we sell
One line, in plain words. [S1xx]

## Products
| Product | What it does (one line) | In scope for cure | Source |
|---|---|---|---|

## Buyer
- buyer_function: the function that owns the problem and the budget (e.g. "Operations: COO, Head of Logistics")
- buyer_titles: titles to look for, most senior first, including local-language forms where the user sells
- proposal: yes | confirmed

## Pain signals
Public signals that a prospect has the problem the products solve. Each: the signal, why it shows the problem, where it shows up publicly.
| Signal | Why it shows the problem | Where it shows up |
|---|---|---|

## Sizing metrics
The columns the sizing table estimates, beyond employees and revenue.
| Column | Definition | Method (estimates only) | Don't estimate for |
|---|---|---|---|

## Research tracks
What each use-case analyst focuses on for a single company.
| Track | Agent | Focus | Hiring and search keywords |
|---|---|---|---|
| structure and financials | cure-filings-analyst | group structure, size, financials, audit, corporate events (fixed) plus: | – |
| operations | cure-operations-analyst | | |
| buyer organization | cure-buyer-org-analyst | | |

## Competitors and partners
Categories cure should classify as competitor (sells what we sell) or channel/partner, with examples only where sourced.

## Market notes
Regions, languages, local registries or rules that matter to the user's market. Optional.

## Sources
S-numbered URLs with dates, from the self-profile ledger.
```

Derive `buyer_function`, `buyer_titles`, `pain_signals`, `sizing_metrics` and `research_tracks` from **what the products do and whom the case studies name**. They are proposals: mark them `proposal: yes` until the user confirms. A sizing metric always has a method, so the report can label it `est.`; prefer a metric a prospect's public documents could state.

### `cure-profile/capabilities.md`

Use the format in `capabilities.md` (the template in this skill's references). Rules:
- A `CAP-xx` exists today: a product page, docs page or case study says so. Its `Status` says GA, beta/preview, or `unclear — confirm` when sources conflict or don't say.
- Anything on a roadmap, marked "coming soon", only in a blog post about the future, or that you are unsure of, is an `EXT-xx`, or it is left out.
- **Never invent a capability**, and never widen one beyond what its source says.
- Every entry has a `Source` line with a URL. Keep `status: DRAFT` in the header until the user confirms.

### `cure-profile/style.md`

```markdown
---
style: brand             # brand | neutral
style_version: 1
date: YYYY-MM-DD
source: ""               # URL, file name, or "pasted"
status: DRAFT
---
# Style

## Colours (hex)
| Token | Hex | Use |
|---|---|---|
| ink | | headline and body text on light |
| background | | page background |
| surface | | cards, table stripes |
| line | | 1px rules and borders |
| muted | | captions, secondary text |
| accent | | the one accent: highlights, links, the CTA |
| accent_text | | text colour on an accent fill |
| negative | | warnings, `verify` pills only |

## Fonts
- heading: family, weights
- body: family, weights
- mono (optional): family, for kickers and labels

## Logo
- logo_url: public URL of the logo for light backgrounds, or none
- logo_dark_url: public URL for dark backgrounds, or none
- wordmark: text to show when there is no logo URL

## Tone
One to three lines from the guideline (formal or plain, words to avoid).

## Rules
The guideline's do's and don'ts that affect a document or web page.
```

- **Guideline given:** read it (WebFetch a URL, Read a file, or use the pasted text). Copy colours as hex, font families and weights, logo URLs, tone and rules. Record anything it doesn't say as blank; `cure-style` falls back to the neutral default for that token. Never guess a brand colour from a screenshot or a logo.
- **A local logo file only:** a page can't link it. Ask for a public URL, or set `logo_url: none` and use the wordmark.
- **No guideline:** write only the header with `style: neutral`. `cure-style` then uses its neutral theme.

## Step 4: confirm

Show the user the three drafts (a short summary table per file, with the full files in the folder). Ask in one message:
- Is the product list right and complete?
- Remove or correct any capability; anything unsure moves to `EXT-xx` or out.
- Are the buyer, pain signals, sizing metrics and research tracks right?
- Is the style right?

Apply the corrections, then set `status: CONFIRMED` in each file the user confirmed. A file the user doesn't confirm stays DRAFT, and the report footer says so.

---

## Worked example (illustrative, not a default)

> **Example profile: a fleet-management software vendor.** This shows the depth a confirmed profile reaches. It is not your profile; cure never uses it unless setup produced it for your organization.

**What we sell:** software that tracks vehicles, plans routes and maintenance, and records driver hours for companies running their own fleets.

**Buyer**
- buyer_function: Operations: COO, Head of Fleet
- buyer_titles: COO, Head of Fleet, Fleet Manager, Head of Logistics, Transport Manager, Health and Safety Director; local-language titles where relevant

**Pain signals** (what makes a good prospect)
- A large owned or leased fleet (vehicle count in a filing, sustainability report or fleet registry)
- Many depots, branches or service regions
- Regulated driving hours or tachograph rules in its markets
- Fuel or energy cost named as a margin pressure in its reports
- A fleet electrification target with a date
- Safety incidents, fines or insurance costs disclosed
- Recent M&A that merged two fleets
- A public job posting for fleet coordinators, dispatchers or telematics roles
- A stated digitisation or cost-reduction programme in operations

**Sizing metrics**

| Column | Definition | Method | Don't estimate for |
|---|---|---|---|
| Fleet (est.) | vehicles the company operates | a published figure always wins; else depots × a sector ratio, labelled `est.` | companies that fully outsource transport |
| Fleet pain | the strongest evidenced pain signal, in words, with its volume | from the ledger only | – |

**Research tracks**

| Track | Agent | Focus | Keywords |
|---|---|---|---|
| structure and financials | cure-filings-analyst | fixed, plus depot and country count, fleet capex and leases | – |
| operations | cure-operations-analyst | how goods or technicians move: own fleet vs subcontractors, routes, depots, delivery volumes, electrification | – |
| buyer organization | cure-buyer-org-analyst | operations and fleet leaders (dated), fleet hiring and its wording, telematics or routing tools only where sourced | "fleet", "dispatcher", "telematics", "route planning"; local-language equivalents where relevant |

**Competitors and partners:** competitor = sells fleet telematics or route planning; channel/partner = vehicle leasing firms, vehicle makers, fuel-card providers.

**A capability entry in this example**

```markdown
### CAP-03 · Preventive maintenance planning
- What it does: schedules servicing from mileage, engine hours and calendar rules, and flags overdue vehicles.
- Problem it solves: "Breakdowns take vehicles off the road, and we only find out a service was missed afterwards."
- Prospect signals that suggest it: a large or ageing fleet; breakdowns or downtime named in reports; maintenance-planner job ads.
- Status: GA. Parts inventory is out of scope (see EXT-02).
- Source: https://example.com/product/maintenance (2026-09)
```

**A pitch angle in this example:** "1,200 vans across 40 depots + 2030 electrification target → maintenance and charging planning, CAP-03".
