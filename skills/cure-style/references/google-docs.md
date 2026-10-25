# cure reports in Google Docs

**Before any connector call, read the `google-workspace` skill** (and its `references/docs.md`) if it is available. It owns the connector rules: create vs edit, revision guards, verification. This file only says how the theme maps onto a Doc.

## Route: upload HTML, let Drive convert it

1. Build a **Docs-safe HTML** file (rules below).
2. Create the file with Drive `create_file`. The content is that HTML and the target type is `application/vnd.google-apps.document`. Drive converts it into a native Doc.
3. Read the new Doc back (Drive `read_file_content`) and check:
   - the headings, tables and highlights survived the conversion;
   - every source URL is still a link.
4. Any later change goes into the **same** Doc through the Google Docs editor connector, never by creating a second file.
5. The Doc is created **private**. Sharing it is the operator's decision, so never share it unasked.

## What survives conversion

| Use | Avoid (dropped or mangled) |
|---|---|
| Inline `style=""` on each element | `<style>` blocks, CSS variables, classes, media queries (Docs has no dark mode) |
| `<h1>`–`<h3>`, `<p>`, `<ul>`/`<ol>`, `<table>` with `border-collapse` | flex, grid, `position`, multi-column layout |
| `background-color` on a `<span>` (the highlight) and on `<td>` | gradients, `border-radius`, box-shadow, alpha colours |
| A font family that Google Docs offers (Arial, Roboto, Roboto Mono and many others) | web-font `<link>`s, which Docs ignores |
| `<a href>` links | inline `<svg>`, and images from local files (Docs fetches images only from public URLs) |

## Token mapping

Use the **light** values: the style file's brand colours when `style: brand`, else the neutral light tokens below. The neutral body font is Arial. If the brand font isn't a Google Docs font, use Arial and say so in one line.

| Element | Docs styling (neutral values) |
|---|---|
| Title (H1) | body font 26pt, 700, `ink` `#111827` |
| Highlight | `<span style="background-color:#DBEAFE;color:#111827">…</span>` (`accent-soft` on `ink`), one per heading |
| Kicker | Roboto Mono 9pt, uppercase, `muted` `#64748B`, with letter spacing added through spaces (Docs ignores `letter-spacing`) |
| H2 | body font 16pt, 700, `ink` |
| Body | body font 10.5pt, 400, `ink-soft` `#1F2937`, line height 1.4 |
| Caption / source line | body font 8.5pt, `muted` |
| Table header row | `<td>` background `surface` `#F6F7F9`, `ink` 9pt 600, bottom border 1px `ink` |
| Table body | body font 9pt, borders 1px `line` `#E5E7EB` |
| Callout (key takeaway) | one-cell table, background `accent-soft`, `ink` text, left border 3px `accent` `#2563EB` |
| EXT (extension) item | one-cell table, background `surface`, kicker `NEEDS PRODUCT CONFIRMATION` |
| Negative marker | ✗ and `verify` in `negative` `#B91C1C`; positive ✓ in `accent` |

For a brand theme, check every text/background pair for 4.5:1 contrast; if one fails, use `ink` for the text.

## Logo

Docs can't take a local file. Use one of:
- the style file's `logo_url` (a public PNG or JPG works best; Docs may not render SVG). Insert it at 96px or wider.
- otherwise, a text wordmark: the style file's `wordmark` (or the org name) in the body font 14pt, 700, `ink`, with the kicker below it. Tell the operator they can drop in the logo by hand.

## Footer

The last paragraph is a mono caption: `Research date · Profile vN (date) · Capability catalog vX.Y.Z (date) · Sources: N · Models: …` (see the cure-style SKILL.md footer).
