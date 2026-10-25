# Heuristics: estimates, pain signals, classification

The seller profile (`cure-profile/profile.md`) says what to estimate and what to look for. This file says how. Every number produced here is an **estimate**. It is labelled `est.` in the report, and its method is stated once.

## Estimating a sizing metric

Each row of the profile's **Sizing metrics** table gives a column, its definition, its method and where not to estimate.

- **Method:** usually a public base figure × a ratio (e.g. total employees × the sector's share in the buyer function). State the base figure's ledger ID, the ratio and its range, and the result as a range.
- **A sourced figure always wins.** A function-level figure from a filing (e.g. headcount by department in an annual report) replaces the estimate.
- **"Don't estimate for"** means: show "not public" or the sourced figure, never a computed one. Typical cases are organizations that run the function in a way the ratio doesn't capture (in-house operations units, state-scale directorates, outsourced functions).
- **No ratio in the profile for a sector:** don't invent one. Show the base figure and "est. not available for this sector".
- **Mark untested ratios** as untested until a sourced run has checked one.

`setup.md` has a worked example of a ratio table.

## Pain signals (what makes a good prospect)

Use the profile's **Pain signals** table. A signal counts only when a ledger row evidences it; the report shows the signal and its volume (e.g. "120 stores, 6 warehouses" or "2,000 shipments/day"). Signals that apply to most products:

- Scale and complexity in the area the product addresses: volumes, channels, sites, entities, countries, currencies
- A recent M&A, carve-out or ownership change, which means a system migration
- A stated automation, digitisation or cost goal from leadership
- Public job postings for roles the product helps or replaces, especially wording that describes manual work
- An audit finding, restatement or regulatory action in the area the product addresses
- A leadership change in the buyer function in the last 18 months

## Classify every company before ranking it

| Class | Meaning | In the report |
|---|---|---|
| Buyer | Has the problem the product solves and decides locally | main table |
| Long cycle / hard target | Large, decides at global HQ, regulated, or in post-merger integration | "Hard targets" box |
| Competitor | Sells what the profile says we sell (see its **Competitors and partners** section) | "Partners & competitors" box |
| Channel / partner | Resellers, implementers, platforms or data sources the profile lists as partner categories | "Partners & competitors" box |
| No local entity | No legal entity in the target market | excluded, with a one-line note |

## Priority (sizing)

- **A:** strong evidenced pain signals, the decision is made in a reachable market, and the company is reachable (mid-size or listed with a named buyer-function lead, or a fast-growing network).
- **B:** large but a long cycle, or the data is too thin.
- **C:** low fit.

Offer two sorts: **volume** (by scale and pain signals) and **winnable** (by reachability). They often disagree, and both views are useful.
