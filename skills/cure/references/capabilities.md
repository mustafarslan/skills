# The capability catalog: format

cure reads what the seller's products do from **`cure-profile/capabilities.md`** in the working folder, never from this file. Setup (`setup.md`) drafts it from the seller's own public sources, and the user confirms it. This file is the format and an empty template.

## Rules

- **CAP-xx** describes what a product does today. Its `Status` says how firmly: `GA` runs for customers; `beta` (or preview) is built but switched on per customer; `unclear — confirm` means the sources conflict or don't say.
- **EXT-xx** is a gap or an adjacent idea: roadmap, "coming soon", out of scope, or not confirmed. Never pitch an EXT as available; word it as "on the roadmap / in discussion" at most, after product confirms it.
- A beta or `unclear — confirm` CAP also needs a product check before a report promises it.
- Map a prospect's evidenced bottleneck to the nearest CAP through its **Prospect signals** line.
- Every entry has a **Source** line with a public URL and date. A capability without one is not in the catalog.
- Number entries once and never reuse a number; a removed entry leaves a gap.
- Bump `catalog_version` on every change. Reports print it in the footer.

## Template

```markdown
---
catalog_version: 1.0.0
generated: YYYY-MM-DD
sources_read: list of the product, docs and pricing URLs read, with dates
status: DRAFT            # DRAFT until the user confirms; then CONFIRMED (YYYY-MM-DD)
---
# <org name> capability catalog

One paragraph: what the products do, in the buyer's words.

## Capabilities

### CAP-01 · <name in the buyer's words>
- What it does:
- Problem it solves: "<the buyer's sentence>"
- Prospect signals that suggest it:
- Status: GA | beta | unclear — confirm
- Source: <URL> (<date>)

## Extensions (EXT)

### EXT-01 · <name>
- Gap:
- Why a prospect would want it:
- Nearest CAP:
- Confirm with product: yes
- Source: <URL> (<date>), or "user, at setup"
```

`setup.md` ends with a worked example that includes one filled-in CAP entry.
