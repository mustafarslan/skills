# Flow 1: prospect sizing (an event or a list of companies)

The output is a ranked table of companies with size, the buyer-function lead, the profile's sizing metrics, class and priority, every figure sourced.

## Steps

1. **Build the roster** and write it to `roster.md`.
   - **For an event:** look for exhibitor, sponsor or partner pages, speakers, hosted buyers, and post-event press.
   - **Say on line one whether this is a real exhibitor list or a proxy.** A sponsor roster is not an exhibitor list.
   - **Record where each list came from** (URL and date).
   - **For a pasted or attached list**, use it as it is and note its origin.
2. **Scope it.** Tier the roster:
   - **Tier A** (research one by one, at most about 30, or the operator's cap): the strategic and top tiers, plus big companies hidden in lower tiers, hosted buyers and speakers' employers.
   - **Tier B** (bucketed, not researched): small agencies, startups.
   - **Excluded:** community, government and media partners.
   - **Grouped:** entities of one group are merged (e.g. Acme Logistics + Acme Global).

   Classify each company (`heuristics.md`). Sponsor tier does not show company size; look for size signals beyond it.
3. **Review the scope.** Send `roster.md` to `cure-reviewer` (or run the scoping checklist yourself; see SKILL.md). Adjust and record what changed.
4. **Fan out.** Split Tier A into homogeneous segments (e.g. by sector and country: domestic retailers, domestic logistics, global players, one region), at most 4 researchers. Use the prompt below. Research priority-A segments first.
5. **Consolidate.** Merge the `claims-*.md` files into one table. Compute each sizing-metric estimate per `heuristics.md` and the profile's method. Assign the class and A/B/C priority. Write a one-line **pitch angle** per A company, drawn from its strongest evidenced pain signal and mapped to a `CAP-xx` in `cure-profile/capabilities.md` (e.g. "12 country entities + new parent → group roll-out, CAP-03"). If that CAP's Status says "unclear — confirm", end the angle with "(confirm with product)".
6. **Two critics, in parallel, blind to each other** (Full depth):
   - **`cure-reviewer`** audits the merged table against the ledgers.
   - **`cure-buyer-skeptic`** gets only the merged ledger and the draft table, plus the profile's `buyer_function` and one-line "What we sell" pasted into its brief. It gives each A company's likely objection and the **winnable** rank.

   The scale-based order is the **volume** sort; the skeptic's rank is the **winnable** sort. Fix the reviewer's findings.
7. **Publish** (see SKILL.md).

## Report sections

1. **Scope:** what the source list is and isn't; the event facts; the line "columns marked est. are estimates".
2. **Target table:** 30 rows at most, sortable. Columns:
   - Company and group;
   - Segment / listing;
   - Employees;
   - Revenue (year and currency);
   - Buyer lead (the most senior `buyer_titles` match found);
   - one column per row of the profile's **Sizing metrics** (estimates tagged `est.`);
   - Pain signal (the strongest evidenced one);
   - Class;
   - Priority;
   - Pitch angle.
3. **Estimation method** box.
4. **Hard targets** box.
5. **Partners & competitors** box.
6. **Who to meet:** speakers from A companies whose role is in the buyer function, if the event lists them.
7. **Second opinions**, as separate voices (see `second-opinions.md`).
8. **Sources.**
9. **Footer:** research date, profile version and catalog version.

Also save `prospects.csv` for import into the CRM named in the profile (`crm`; a generic CSV when it says so). Columns:
- company, domain, segment, country;
- employees, revenue, revenue_year, buyer_lead;
- one column per sizing metric, snake_case (e.g. `team_size_est`);
- priority, class, pain_signal, pitch_angle;
- source_urls.

If the profile names a CRM whose import needs other header names, say so and keep these; never guess its field names.

## Researcher prompt (fill the angle brackets; nothing else changes)

```
Research these companies for a prospect-sizing report for <ORG NAME>, which sells <WHAT WE SELL>.
Today is <DATE>; prefer the newest data (<YEAR-1>/<YEAR>).
Companies (<segment>): <list, with tickers/parents where known>.
Rules: <ABSOLUTE PATH>/references/claims.md (read it first and follow it exactly).
Sources by country: <ABSOLUTE PATH>/references/sources.md.
Classes and estimates: <ABSOLUTE PATH>/references/heuristics.md.
Seller profile (buyer, pain signals, sizing metrics, competitors): <ABSOLUTE PATH>/cure-profile/profile.md.
Your evidence IDs: E<N>00–E<N>99. Search budget: about 25 searches. Write your ledger to <RUN DIR>/claims-<N>.md as you go.

For EACH company find: legal entity and parent; HQ; sector; listed or private (ticker); total employees (figure, date, URL);
latest annual revenue (figure, currency, period, restated/nominal for hyperinflationary currencies, URL);
the most senior person matching the profile's buyer_titles (name, source date); the public base figure each sizing
metric needs, or a sourced figure for the metric itself; evidenced pain signals from the profile; whether it is itself
a competitor or partner per the profile. "not public" is a valid answer; never guess.
Return the ledger rows plus a 3-line note on gaps.
```
