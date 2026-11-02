---
name: design-doc
description: The user's house style for documents people read — a neutral, achromatic look with one yellow accent, system fonts and a small component set. Use when the user says "design-doc" or "in my style", asks to style or polish a document, or when you produce a styled deliverable (HTML page, PDF, Google Doc or Word file for a report, spec, runbook, how-to or one-pager) and the project has no visual style of its own. Visual styling only, not voice or content. Not for plain Markdown in a repository (README, docs/), and not when the project or the user's request already names another brand or design system.
---

# design-doc — one accent on neutral grey

A styling guideline for documents people read: specs, runbooks, reports, how-tos, one-pagers.
It decides how a document looks, not what it says.

The scheme is an **achromatic scheme with a chromatic accent** (an accented achromatic palette):
every colour in the document is a true neutral (white, greys, near-black), and exactly **one**
saturated hue, a warm yellow, marks what matters. Yellow is the colour opposite the grey
field in attention terms: because nothing else has hue, a single yellow mark is found at a glance.

## When it applies

This is the user's own look, carried from project to project. Apply it when they ask for it, or
when you make a styled document and nothing else decides the look. **Step aside** when the project
has its own design system or brand (a theme file, a style guide, a docs site with its own CSS),
when the request names another style, or when the output is plain Markdown that a repository or
renderer styles for itself. When unsure, ask once.

Write the output where the user's work lives (their project or working folder), never into this
skill's folder.

## Files

All paths below are relative to this skill's folder: `${CLAUDE_SKILL_DIR}` (the base directory
shown when the skill loads; `~/.claude/skills/design-doc` for a copy install). Read, in this order:

1. `references/tokens.css` — the one token table: colours, type stack, scale, spacing.
2. `references/html.md` — type styles and component recipes for HTML and PDF.
3. `references/docs-and-pdf.md` — only when the output is a Google Doc, a Word file or a PDF.

## The rules

### Colour

- **One hue.** The accent is the only colour with hue. Never add a second one, not for warnings,
  not for success, not for links, not for charts. (Charts: grey series, with the accent on the
  one series the reader must see.)
- **Neutrals are true neutrals:** every neutral has R = G = B. A "warm grey" or a "blue-black" is
  a second hue in disguise.
- **The accent is a fill, not a text colour.** Text on an accent fill is always `--text-1`
  (12.06:1). Accent-coloured *text* appears only on dark surfaces (≥ 9.99:1). On white the accent
  is 1.55:1, so accent text or accent thin lines on white are never used.
- **Proportion:** about 60% light neutrals, 30% dark and mid neutrals (ink text, dark blocks), at
  most 10% accent. If the accent covers more than a tenth of a page, it has stopped being an accent.
- **Meaning without hue.** Warning, danger, success and "don't" are carried by a **glyph and a
  label**, plus weight, never by colour:

  | Meaning | Marker |
  |---|---|
  | Note | `i` glyph in a circle outline, label "Note" |
  | Warning | `!` glyph in a triangle outline, label "Warning", bold |
  | Do | `✓`, label "Do" |
  | Don't | `✗`, label "Don't", struck-through example |
  | Required | label "Required" in semibold, never a red asterisk |

### Type

- **System fonts only** (`--font-sans`, `--font-mono`), so a document renders the same on a
  fresh machine with no network. Mono is for code and identifiers, never for decoration.
- **Scale** is the 1.25 ratio in the tokens. Body is 16px at line-height 1.6; headings 1.2.
  Tracking is neutral (`0`), at most `-0.01em` on the two largest sizes.
- **Weights:** 400 body, 600 for emphasis and table headers, 700 for headings. No light weights.
- **Sentence case** for headings and labels. No all-caps labels, no letter-spaced captions.
- **Measure:** prose at most `--measure` (70ch). Tables and figures may use `--wide`.

### Layout

- 4px spacing base: use the `--s-*` tokens and do not introduce new spacing values.
- One column of prose, left-aligned, ragged right. No justified text.
- Corners nearly square (`--radius: 2px`). No shadows, no gradients, no blur.
- A page has: a header (document title and version or date), the content, a footer (document
  identifier left, page number right).
- Hierarchy comes from size, weight and space. Never from colour.

### Use of the accent (the whole list)

The accent may be used for **only** these:

1. `<mark>`: a highlighted phrase. At most **one per section** and never inside a table cell.
   (Browsers already render `<mark>` as a yellow highlight; this skill only tunes the colour
   and keeps the text ink.)
2. The 4px **left rule of a callout**.
3. The **single highlighted series or bar** in a chart.
4. The **selected or current** item (current page in a table of contents, selected tab).
5. A **text-selection or focus ring** (a 2px outline).

Anything else stays neutral.

## Components

Recipes are in `references/html.md`. The vocabulary:

- Callout (note, warning), with glyph and label
- Table (header row, zebra, numeric columns right-aligned)
- Code block (dark surface) and inline code
- Figure with caption
- Step list (numbered, with a short result line per step)
- Do / Don't pair
- Key figure (value, unit, label)
- Page header and page footer

Choose from these. Do not invent decorative components (badges, ribbons, pills, banners).

## Accessibility checks (run before you hand the document over)

| Pair | Contrast | Use |
|---|---|---|
| `--text-1` on `--bg` | 18.73 | headings, primary text |
| `--text-2` on `--bg` | 13.58 | body |
| `--text-3` on `--bg` / `--surface` | 6.69 / 5.97 | captions, meta |
| `--text-1` on `--accent` | 12.06 | text inside `<mark>` and accent fills |
| `--on-dark-1` on `--dark-surface` | 16.60 | text on dark blocks |
| `--on-dark-2` on `--dark-raised` | 7.40 | secondary text on dark blocks |
| `--accent` on `--dark-surface` | 11.65 | accent text, dark surfaces only |
| `--accent` on `--bg` | **1.55** | **never as text or a thin line** |

Body text needs at least 4.5:1; large text (24px and up, or 19px bold) at least 3:1. `--rule` is
decorative: it never carries text. Information never depends on colour alone (the glyph rule).

## Checklist

- [ ] Every colour is a token; every neutral is R = G = B.
- [ ] The only hue is the accent; it covers at most about a tenth of the page.
- [ ] No accent text on a light background; text on accent is ink.
- [ ] Warnings and "don't" are glyph + label, not colour.
- [ ] System fonts, sentence case, no all-caps labels.
- [ ] One `<mark>` per section at most; none in a table cell.
- [ ] Prose at most 70ch; tables right-align numbers.
- [ ] Header and footer present on multi-page output; page numbers work in print.
