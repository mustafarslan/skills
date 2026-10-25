---
name: cure-style
description: Use when a cure report needs styling as an HTML artifact or a Google Doc. Applies the user's own brand from the seller profile's style file (colours, fonts, logo URL, tone) when one was set up, and a clean neutral theme with light and dark mode otherwise. Covers typography, layout and the recurring report components.
---

# cure report styling

cure reports take the **user's own brand** when setup recorded one, and a neutral theme otherwise. This skill covers visual styling only, not voice; tone notes from the style file apply to headings and labels, never to facts.

| Output | Read |
|---|---|
| Claude artifact (HTML page) | `references/html.md`: tokens, light and dark mode, type scale, component recipes, logo |
| Google Doc | `references/google-docs.md`: what survives HTML-to-Docs conversion, and the Docs mapping of the tokens |

## Pick the theme

1. Read `cure-profile/style.md` in the working folder (or the copy in the conversation when there is no folder).
2. **`style: brand`:** map its tokens onto the CSS variables in `html.md` (`ink`, `background`, `surface`, `line`, `muted`, `accent`, `accent_text`, `negative`) and its fonts onto the font variables. Any token it leaves blank takes the neutral default. Follow its **Rules** where they don't conflict with the readability checks below.
3. **`style: neutral`, or no file:** use the neutral theme as written in `html.md`.
4. If the style file is DRAFT, still use it; the report footer already prints DRAFT.

**Readability checks (every theme):**
- Body text against its background reaches at least 4.5:1 contrast; large headings at least 3:1. If a brand pair fails, use the neutral `ink` for that text and keep the brand colour for rules, fills and accents.
- Never put accent-coloured text on a background where it fails the check; use the accent as a fill with `accent_text` on top instead.
- In dark mode, derive brand tokens only when the style file gives dark values; otherwise use the neutral dark tokens and keep the brand `accent` if it passes the check on the dark background.

## Neutral theme at a glance

| Role | Token | Light | Dark |
|---|---|---|---|
| Text | `--ink` | `#111827` | `#F3F4F6` |
| Text · soft | `--ink-soft` | `#1F2937` | `#D1D5DB` |
| Text · muted | `--muted` | `#64748B` | `#9CA3AF` |
| Background | `--bg` | `#FFFFFF` | `#0F1115` |
| Surface | `--surface` | `#F6F7F9` | `#171A21` |
| Divider | `--line` | `#E5E7EB` | `#2A2F3A` |
| Accent | `--accent` | `#2563EB` | `#60A5FA` |
| Accent · soft | `--accent-soft` | `#DBEAFE` | `#1E3A5F` |
| Text on accent | `--accent-text` | `#FFFFFF` | `#0F1115` |
| Negative | `--negative` | `#B91C1C` | `#F87171` |

- **Type:** the system sans stack (400/500/600/700) for everything, so nothing loads; the system monospace stack for kickers and labels. A brand font replaces the sans stack. Never a third typeface.
- **Accent** is the single highlight colour: links, the keyword highlight, the CTA, ✓ markers. **Negative** is only for warnings, ✗ markers and `verify` pills; never a large fill.

## Universal rules

- **One emphasis per headline:** a soft accent background behind one key phrase, instead of bold or italic.
- **Logo:** only from `logo_url` / `logo_dark_url` in the style file, as a public URL, never redrawn, recoloured or stretched. With no URL, use the `wordmark` text (or the org name) in the heading font at 600 weight.
- **Layout:**
  - Spacing scale 8 / 16 / 24 / 48 / 96px.
  - Content max-width 1200px.
  - Dense data tables may go full width and scroll inside their own container on a phone.
  - 16px side gutter at phone width; no horizontal page scroll.
- **Components:**
  - kicker (mono label above a headline);
  - metric tile;
  - KPI row;
  - comparison bullets (negative ✗ / accent ✓);
  - 3-up cards (two neutral, one accent-soft);
  - numbered cards;
  - a callout box;
  - one CTA link per page at most;
  - a mono footer line.

  Their recipes are in `references/html.md`.

## Cure report conventions

- **Header:** the logo or wordmark of the user's organization, then a mono kicker (`CURE · ACCOUNT RESEARCH` or `CURE · PROSPECT SIZING`), then a headline with one highlight.
- **Footer:** a mono line reading `Research date · Profile vN (date) · Capability catalog vX.Y.Z (date) · Sources: N · Models: orchestrator <model>, research Sonnet 5.5, skeptic <model>`, with `DRAFT` after any profile file that isn't confirmed.
- **Marking claims in tables:**
  - an estimate gets a muted `est.` tag;
  - an unverified or third-party figure gets `*`;
  - a stale name gets a small negative-outlined `verify` pill.
- **Use-case cards:** existing capabilities (CAP) use a neutral card. Extensions (EXT) use a surface card with a mono `NEEDS PRODUCT CONFIRMATION` kicker; an `unclear — confirm` CAP gets a `CONFIRM WITH PRODUCT` kicker.
