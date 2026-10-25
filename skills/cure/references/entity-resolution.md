# Entity resolution: pin down who the company is before researching it

A brand, a legal entity and a group are different things. "Acme Retail" may be a brand; "Acme Retail Holdings PLC" the legal entity that files the annual report; and "Acme Logistics" may report inside a foreign parent. A short name can also belong to an unrelated company in another sector (a software vendor and a supermarket chain sharing three letters). Research on the wrong entity is worse than no research.

## Output: the entity card, written to `entity.md` before any other research

| Field | Required | Notes |
|---|---|---|
| Brand / trading name | yes | as the operator typed it |
| Legal name | yes | exact, with legal form (Inc., Ltd., GmbH, PLC, LLC, S.A., A.Ş., FZE…) |
| Country of incorporation | yes | |
| Registry ID or ticker | yes, or "not found" | the national company-registry number, the exchange ticker, SEC CIK, Companies House no., ESEF/LEI; see `sources.md` for examples by country |
| LEI | optional | from GLEIF; many private firms have none, so never block on it |
| Immediate parent | yes, or "independent" | with its country and listing |
| Ultimate parent | yes, or "same" | |
| Main subsidiaries and countries | yes, as far as public | from the annual report's subsidiary note, not from GLEIF alone |
| Buying entity | yes | where decisions in the profile's `buyer_function` are made for this business: local entity, regional HQ or group HQ. Give the evidence, e.g. "group head of the function signs; local head named in the exchange filing" |
| Disambiguation | yes | other entities with similar names that were ruled out, and why |
| Sources | yes | URL and date per field |

## Procedure

1. **Search the name with the country** and the local word for company (e.g. "Ltd", "GmbH", "S.A."). Open the company's own website: the imprint, "about us", investor relations, terms or privacy page usually names the legal entity.
2. **Confirm the legal entity in a registry or filing** (see `sources.md` for each country). For example:
   - US-listed: SEC EDGAR company search (the CIK). A 20-F/10-K Exhibit 8 or 21 lists the subsidiaries.
   - UK: Companies House (officers, persons with significant control).
   - EU-listed: filings.xbrl.org (ESEF).
   - Other listed firms: the national exchange's company page, then the trade-registry gazette.
   - Any country: the GLEIF API for the LEI and reported parents.
3. **Walk up and down the group.** Parent links come from filings and annual reports. GLEIF's `ultimate-parent` and `direct-children` are leads only, since it lists only the links companies have reported. Wikidata P749/P355 are leads, never evidence.
4. **Decide the buying entity.** It is local if a local leader in the buyer function is named and the entity files its own accounts. It is HQ if it is a branch or a fully integrated subsidiary, if the group runs a shared-service centre for that function, or if the group reports a single function. If it is unclear, say "unclear" and add a discovery question.
5. **If two or more candidates remain**, stop and ask the operator (show the legal name, country and website for each).

## Conglomerates

When the target is a holding company or conglomerate (e.g. "Acme Group", with retail, energy and logistics arms):

- **List the operating subsidiaries by segment** with their size where public. Research the holding itself only for group-level signals: a shared-service centre, a group-wide system programme, consolidation.
- **Ask the operator which subsidiaries to go deep on.** If they don't choose, pick at most 3 by evidenced pain signals from the profile.
