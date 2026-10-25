# Flow 2: account use cases (one company)

The output tells the seller:
- who the company really is;
- what public evidence suggests it has the problem the seller's products solve;
- which capabilities in `cure-profile/capabilities.md` fit, and which would need a product extension;
- what to ask in the meeting to confirm it.

Filings never say "we have the problem you solve". So **evidence** (facts with sources) and **hypotheses** (our inference from the evidence) are kept in separate sections, and nothing is moved from the second into the first.

## Steps

1. **Resolve the entity.** Follow `entity-resolution.md` and write `entity.md`. If the target is a conglomerate, agree with the operator which subsidiaries to cover (at most 3) before going on. Run the scope checklist in SKILL.md §4 yourself (and the advisor, if listed); no reviewer agent at this step.
2. **Research: three analyst personas, in parallel** (Full depth). Each gets `entity.md`, the absolute paths of the reference files and of `cure-profile/profile.md`, an evidence-ID range, about 25 searches and its ledger file. Each takes its focus from the profile's **Research tracks** row and has its own source checklist in its agent file.

   | Agent | Track | IDs |
   |---|---|---|
   | `cure-filings-analyst` | structure and financials: revenue, employees, entities, countries and currencies, reporting complexity, the subsidiary list, M&A and ownership changes, material weaknesses and restatements, the auditor; plus any additions in the profile's track row | E100–E199 |
   | `cure-operations-analyst` | how the company operates in the area the product addresses: flows, channels, partners, sites and volumes, per the profile's operations track | E200–E299 |
   | `cure-buyer-org-analyst` | the buyer function: its leaders (dated), how it is organised, hiring and the wording of postings, systems and tools only where sourced, leadership and strategy changes in the last 18 months | E300–E399 |

   **Quick depth:** run the three tracks one after another in the main session, with about 15 searches in total. Analysts log facts outside their lane as `handoff` rows; merge those into the right section.
3. **Merge** the three ledgers into `claims.md` in the run folder. Where two analysts sourced the same field, keep the higher tier and show conflicts.
4. **Evidenced volume drivers.** From the ledger only, list the facts that create the work the product addresses. Each is one line: the fact, which pain signal it is and why it creates that work, and its evidence IDs.
5. **Map to capabilities.** For each driver, read `cure-profile/capabilities.md` and match it on the "Prospect signals" lines.
   - **The use case:**
     - bottleneck (inference) → `CAP-xx` → what it would change for them;
     - confidence (High, Med or Low);
     - the evidence IDs it rests on.
   - **If the matched CAP's Status line says "unclear — confirm"**, the card carries a `CONFIRM WITH PRODUCT` kicker and is never presented as available today.
   - **If no CAP fits** but an `EXT-xx` does, it goes under Extensions with "needs product confirmation".
   - **If nothing fits**, say so. A short honest list beats a padded one.
6. **Draft the meeting prep.**
   - **Discovery questions:** for each use case, 1–2 questions that would confirm it or rule it out (e.g. "How many of these do you handle per day, and how?").
   - **People:** named leaders in the buyer function with role, source and date. Anyone with a stale source or only a snippet is tagged `verify`.
7. **Two critics, in parallel, blind to each other** (Full depth):
   - **`cure-reviewer`:** audits the draft against the ledger (checkpoint 2).
   - **`cure-buyer-skeptic`:** reacts as the prospect's buyer from `buyer_function`. Pass it only `claims.md` and the draft use-case cards, with the profile's `buyer_function` and one-line "What we sell" pasted into its brief; never raw pages, the profile file or the reference folder.

   Then fix every reviewer finding. Reorder the cards if the skeptic's ranking is better argued, and merge its discovery questions into step 6. **The skeptic's text never moves into sections 1–7 as fact.**
8. **Publish** (see SKILL.md).

## Report sections

1. **Snapshot:** a 3–5 line summary, then a metric row: revenue, employees, entities/countries, the headline volume driver.
2. **Who they are:** the entity card (legal name, registry, parent, buying entity), with a small group-structure list or diagram.
3. **Evidenced volume drivers:** a table of fact, why it matters, and sources (evidence IDs linked to Sources).
4. **Use cases:** one card per use case, ordered by confidence. Each card has:
   - a title in the buyer's words;
   - bottleneck (labelled **inference**);
   - the capability (CAP name; the ID is fine to show internally);
   - expected change;
   - confidence;
   - evidence IDs;
   - the discovery question.
5. **Extensions:** the same card shape, with the `NEEDS PRODUCT CONFIRMATION` kicker.
6. **Not a fit / risks:** a competitor already in place (only if evidenced), HQ decides, post-merger freeze, and so on.
7. **People to meet.**
8. **Second opinions**, as separate voices (see `second-opinions.md`). The skeptic appears here under the heading **"Buyer skeptic: simulated buyer view (opinion, not evidence)"**, in three parts: what lands, what gets shrugged off, and the top blocker to test.
9. **Sources:** every URL with tier and date, numbered by evidence ID.
10. **Footer:** research date, profile version, catalog version and date, source count.

Keep it tight: tables and cards, no intro or outro prose, no padding.
