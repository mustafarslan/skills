# design-doc — Google Docs, Word and PDF

Hosted editors cannot read CSS variables or system-font stacks, so the tokens are mapped to
fixed values. The rules do not change: one accent, true neutrals, glyph-and-label meaning.

## Token mapping (Google Docs and Word)

| Element | Style |
|---|---|
| Font | **Arial** for text (installed everywhere, so nothing falls back); **Courier New** for code |
| Title (H1) | 24 pt, bold, `#121212` |
| H2 | 16 pt, bold, `#121212` |
| H3 | 13 pt, bold, `#121212` |
| Body | 11 pt, regular, `#2E2E2E`, line spacing 1.5 |
| Caption, source line, meta | 9 pt, regular, `#5C5C5C` |
| Section label | 9 pt, bold, `#5C5C5C`, sentence case |
| Link | `#121212`, underlined |
| Highlighted phrase | highlight colour `#FFC800`, text `#121212`; one per section; never in a table |
| Table header row | bold `#121212` text, no fill, 2 pt bottom border `#121212` |
| Table body | 10 pt, bottom border 0.75 pt `#DADADA`, every second row filled `#F2F2F2`, numbers right-aligned |
| Note callout | one-cell table, fill `#F2F2F2`, **left border 3 pt `#FFC800`**, first line "Note" in bold with a leading "ⓘ" |
| Warning callout | same, left border 6 pt, first line "Warning" in bold with a leading "⚠" (a glyph, not a colour) |
| Code block | one-cell table, fill `#161616`, text `#F5F5F5`, Courier New 9.5 pt |
| Do / Don't | two-column table; "✓ Do" and "✗ Don't" labels in bold; the Don't example struck through |
| Margins | 1 inch (2.54 cm) all round; A4 or Letter as the reader's region expects |
| Header | document title left, version or date right, 9 pt `#5C5C5C` |
| Footer | document identifier left, page number right, 9 pt `#5C5C5C` |

Check, at the end: the only coloured things in the document are highlight fills and callout left
borders (all `#FFC800`). If anything else has hue, remove it.

## Building a Google Doc

Two routes. Prefer the first, because it keeps the styles editable by the next person.

1. **Native styles.** Create the document, then set the *named styles* (Title, Heading 1–3,
   Normal text) to the table above and choose "Update … to match". Build tables and callouts as
   tables. This survives future edits and the outline pane.
2. **Upload HTML for conversion.** Write Docs-safe HTML and let the drive convert it. What the
   converter does with it:

   - **Survives:** inline `style=""` attributes; headings, paragraphs, lists; tables with
     `border-collapse`; `background-color` on a `<span>` (the highlight) and on a `<td>`;
     `font-family: Arial` and `Courier New`; links.
   - **Is lost or mangled:** `<style>` blocks, classes and CSS variables; flex, grid, positioning and
     columns; gradients, rounded corners, shadows and alpha colours; web-font links; inline
     `<svg>`; images that are not at a public URL.

   After conversion, read the document back and check that headings, tables, highlights and links
   survived. Leave the sharing settings to the document's owner.

## Word (`.docx`)

Define the same named styles in the template (Title, Heading 1–3, Normal, Caption, a "Code" style
and "Callout note" / "Callout warning" table styles), then apply styles to content. Never format by
hand-picking colours: the only allowed colours are the neutral table and `#FFC800`.

## PDF

- From HTML: use the print rules in `html.md` and headless Chrome. This is the preferred route
  because the page numbers, the page breaks and the colours are all under control.
- From Docs or Word: export as PDF; then check pages for a heading stranded at the bottom of a page
  and for tables split across pages.
- Check the PDF at 100% zoom: body text is at least 10 pt, and the highlight is still readable
  when printed in greyscale (ink on a mid-light fill: it is, at 12.06:1).
