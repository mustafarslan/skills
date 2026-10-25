# Where facts come from

## Source tiers (use the highest tier available; always record the tier)

| Tier | Kind | Examples |
|---|---|---|
| T1 | Regulatory filing | SEC 10-K / 20-F / 6-K, ESEF annual report, Companies House accounts, national stock-exchange disclosures and financial reports |
| T2 | Official registry | Trade-registry gazette, the national company register, Companies House officers/PSC, GLEIF record |
| T3 | Company's own published report | Annual report, sustainability/ESG report, investor presentation, parent's annual report segment |
| T4 | Company's own channels | Website, press releases, management-team page, careers page and job postings, official LinkedIn company page (only the parts visible without login) |
| T5 | Reputable press and rankings | Reuters, Bloomberg, FT, national business dailies, national top-500 rankings, regional business press |
| T6 | Aggregators (last resort, always `*`) | ZoomInfo, Revelio Labs, PitchBook, Crunchbase, job-board company brackets, RocketReach |
| Lead only (never cited as evidence) | Crowd or derived | Wikipedia, Wikidata, search-result snippets, AI summaries, agy's or any model's figures |

A T5 or T6 figure is marked `*` in the report. If T1–T4 contradict each other, show both values side by side, each with its source.

## Where to look, by country

These rows are examples. For a country not listed, find its exchange, company register and the business press that ranks its largest companies, and record what worked in the run notes.

| Market | Start here |
|---|---|
| Any | Company site and imprint; GLEIF `api.gleif.org/api/v1/lei-records?filter[entity.legalName]=...`, `/ultimate-parent`, `/direct-children` (leads for structure); the parent's annual report |
| US-listed (incl. foreign issuers) | SEC EDGAR: `data.sec.gov/submissions/CIK##########.json`, XBRL `data.sec.gov/api/xbrl/companyfacts/CIK##########.json`, full-text search `efts.sec.gov/LATEST/search-index?q=...`. Send a User-Agent that names you (SEC requires it). A 20-F can carry headcount by function. |
| UK | Companies House (the API needs a free key; the website pages work without one) |
| EU-listed | `filings.xbrl.org/api/filings` (ESEF annual reports) and the company's IR page |
| Gulf / MENA (example) | Exchange disclosures and IR PDFs (DFM, ADX, Tadawul, QSE), the company's IR page, regional business press |
| Turkey (example) | Listed: the public disclosure platform `kap.org.tr`, whose company page names the officers; the annual activity report for headcount and branches; financial reports note IAS 29. It has no public API, so use WebFetch on pages and the search. Private: the trade-registry gazette, national top-500 rankings, the parent's annual report, business press. |
| Other listed firms | The national exchange's disclosure system and the company's IR page |
| Other private firms | The company register (some countries publish filed accounts), national top-500 rankings, business press |

## Strong signals of a need, and where they show up

The profile's **Pain signals** table says which signals matter for the seller's products. Where the common ones show up:

| Signal | Where |
|---|---|
| Material weakness or a control deficiency | 10-K/20-F Item 9A/15, the auditor's report, a qualified opinion in local filings |
| Restatement | filings, press |
| A system migration or new platform programme | job postings, press, vendor case studies (T5) |
| M&A, carve-out, ownership change | filings, exchange disclosures, press |
| Number of entities, countries and currencies | annual-report subsidiary note, the 20-F list of subsidiaries |
| Shared-service centre or GBS | company site, job postings, press |
| Hiring in the buyer function (search with the profile's `buyer_titles` and research-track keywords, in the local language too) | careers page, job-board and LinkedIn snippets (T6 for counts, but a posting itself is T4 evidence of the need) |
| Volumes: sites, customers, partners, transactions, shipments | annual report, investor presentation, press releases |

## What failed before (save the search budget)

- **Large 10-K/20-F files (several MB) are cut off partway through a fetch.** Item 6 (employees) and Item 15 (controls) sit past the cut. Instead:
  - fetch the filing's index page and open the smaller exhibits and the XBRL "R" report pages;
  - run an EDGAR full-text search (`efts.sec.gov/LATEST/search-index?q="number of employees"&ciks=<CIK>`) to confirm which document holds it;
  - use the company's IR annual-report PDF or results release;
  - in Cowork or Code, where a shell is allowed, download the file and search it locally.

  Never record the figure from an aggregator as if it came from the filing.
- **LinkedIn** is behind a login wall; never count employees by function from it.
- **Job-board company pages** often return 403. Use the search snippet only, marked T6 and undated.
- **Large annual-report PDFs** can time out or return only the cover. Try the HTML or IR version, a smaller "summary" PDF, or the filing. In Cowork the operator can drop a downloaded PDF into the working folder; ask once.
- **Aggregator function buckets** (e.g. a "Finance & Operations" bucket) mix in other staff, so don't use them for the size of one function.
- **Top-500 ranking rows** can be years old and undated; check the year.
- **Hyperinflationary currencies** need the year and whether figures are restated (e.g. IAS 29) or nominal (they differ a lot).
- **Pre-event and post-event numbers** for events conflict; use the post-event actuals.
