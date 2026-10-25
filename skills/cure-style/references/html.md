# HTML reference: cure reports

For Claude artifacts and other HTML pages. Start from the neutral tokens below; when `cure-profile/style.md` says `style: brand`, overwrite the matching variables with its hex values and fonts (see the cure-style SKILL.md for the mapping and the readability checks).

## CSS variables: paste into the page

Use `var(--token)` everywhere instead of hard-coding hex values. Light is the default; dark mode applies when the viewer's system asks for it, unless the page forces a theme with `data-theme`.

```css
:root {
  /* Colours (neutral light) */
  --ink:         #111827;
  --ink-soft:    #1F2937;
  --muted:       #64748B;
  --bg:          #FFFFFF;
  --surface:     #F6F7F9;
  --line:        #E5E7EB;
  --accent:      #2563EB;
  --accent-soft: #DBEAFE;
  --accent-text: #FFFFFF;
  --negative:    #B91C1C;

  /* Fonts */
  --font-sans: system-ui, -apple-system, 'Segoe UI', Roboto, 'Helvetica Neue', Arial, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;

  /* Layout */
  --gutter: 48px;
  --maxw:   1200px;

  /* Spacing scale */
  --sp-xs: 8px; --sp-s: 16px; --sp-m: 24px;
  --sp-l: 48px; --sp-xl: 96px;

  color-scheme: light;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --ink:         #F3F4F6;
    --ink-soft:    #D1D5DB;
    --muted:       #9CA3AF;
    --bg:          #0F1115;
    --surface:     #171A21;
    --line:        #2A2F3A;
    --accent:      #60A5FA;
    --accent-soft: #1E3A5F;
    --accent-text: #0F1115;
    --negative:    #F87171;
    color-scheme: dark;
  }
}

:root[data-theme="dark"] {
  --ink:         #F3F4F6;
  --ink-soft:    #D1D5DB;
  --muted:       #9CA3AF;
  --bg:          #0F1115;
  --surface:     #171A21;
  --line:        #2A2F3A;
  --accent:      #60A5FA;
  --accent-soft: #1E3A5F;
  --accent-text: #0F1115;
  --negative:    #F87171;
  color-scheme: dark;
}

@media (max-width: 640px) {
  :root { --gutter: 16px; }
}
```

**Brand style:** replace the light values with the style file's colours, and its fonts in `--font-sans` / `--font-mono` (keep the system fallbacks after them). Replace the dark values only if the style file gives dark colours; otherwise keep the neutral dark set, and keep the brand accent there only if it passes the contrast check on `#0F1115`.

## Fonts

The neutral theme loads no web font: `--font-sans` and `--font-mono` are system stacks.

For a **brand font**, load it from Google Fonts with a `<link>` if it is there, and put its family first in `--font-sans` (or `--font-mono`):

```html
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=<Brand+Font>:wght@400;600;700&display=swap" rel="stylesheet">
```

If it isn't on Google Fonts, don't embed it: use the system stack and say in one line that the brand font needs a licence to embed.

## Base typography

```css
body {
  margin: 0;
  font-family: var(--font-sans);
  font-weight: 400;
  color: var(--ink);
  background: var(--bg);
  -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}

/* Type scale */
.t-display { font-size: clamp(40px, 6vw, 64px); font-weight: 700; letter-spacing: -0.03em; line-height: 1.0; }
.t-h1      { font-size: clamp(32px, 4.5vw, 44px); font-weight: 700; letter-spacing: -0.025em; line-height: 1.1; }
.t-h2      { font-size: 28px; font-weight: 600; letter-spacing: -0.02em; line-height: 1.15; }
.t-h3      { font-size: 20px; font-weight: 600; letter-spacing: -0.01em; line-height: 1.25; }
.t-body-lg { font-size: 18px; line-height: 1.55; }
.t-body    { font-size: 16px; line-height: 1.55; }
.t-caption { font-size: 13px; font-weight: 500; line-height: 1.45; color: var(--muted); }

/* Mono kicker */
.t-kicker {
  font-family: var(--font-mono);
  font-size: 11px;
  font-weight: 500;
  letter-spacing: 0.14em;
  text-transform: uppercase;
  color: var(--muted);
}

a { color: var(--accent); }
```

## Layout container

```css
.page {
  max-width: var(--maxw);
  margin: 0 auto;
  padding: var(--sp-l) var(--gutter) var(--sp-xl);
}
section { margin-bottom: var(--sp-xl); }
.table-wrap { overflow-x: auto; }
table { border-collapse: collapse; width: 100%; font-size: 14px; }
th, td { text-align: left; padding: 8px 10px; border-bottom: 1px solid var(--line); vertical-align: top; }
th { font-weight: 600; color: var(--ink); background: var(--surface); }
```

## Component recipes

### Headline with one highlighted phrase

```html
<h1 class="t-h1">Where the work <span class="kw">piles up.</span></h1>
```

```css
.kw {
  background: var(--accent-soft);
  color: var(--ink);
  padding: 0 0.12em;
  box-decoration-break: clone;
  -webkit-box-decoration-break: clone;
}
```

Use it **instead of** bold or italic, once per headline.

### Comparison bullets: ✗ vs ✓

```html
<ul class="bullets-bad"><li>Done by hand in spreadsheets each month.</li></ul>
<ul class="bullets-good"><li>Handled automatically, with exceptions routed to a person.</li></ul>
```

```css
.bullets-bad, .bullets-good { list-style: none; padding: 0; }
.bullets-bad li, .bullets-good li {
  position: relative; padding-left: 1.5em; margin-bottom: 0.5em;
  font-size: 14px; color: var(--ink-soft);
}
.bullets-bad li::before  { content: "×"; position: absolute; left: 0; color: var(--negative); font-weight: 700; }
.bullets-good li::before { content: "✓"; position: absolute; left: 0; color: var(--accent); font-weight: 700; }
```

### Kicker block (section open)

```html
<div class="kicker-block">
  <span class="t-kicker">Section 03 · Volume drivers</span>
  <h2 class="t-h2">What creates the work.</h2>
</div>
```

```css
.kicker-block { display: flex; flex-direction: column; gap: var(--sp-s); margin-bottom: var(--sp-m); }
```

### Callout box

```html
<div class="callout">
  <span class="t-kicker">Key takeaway</span>
  <p class="t-body-lg">One sentence the reader should leave with.</p>
</div>
```

```css
.callout { background: var(--surface); border-left: 3px solid var(--accent); padding: var(--sp-m); border-radius: 6px; }
```

### Metric tile and KPI row

```html
<div class="kpis">
  <div class="metric"><span class="metric-v">3,611</span><span class="metric-lbl">Employees · FY2025 · E12</span></div>
</div>
```

```css
.kpis { display: grid; grid-template-columns: repeat(auto-fit, minmax(160px, 1fr)); gap: var(--sp-m); }
.metric { display: flex; flex-direction: column; gap: var(--sp-xs); padding: var(--sp-m); border: 1px solid var(--line); border-radius: 8px; }
.metric-v { font-size: 40px; font-weight: 700; letter-spacing: -0.02em; color: var(--ink); }
.metric-v small { font-size: 0.45em; font-weight: 600; color: var(--muted); margin-left: 2px; }
.metric-lbl { font-size: 13px; color: var(--muted); }
```

### Cards (3-up, use-case cards)

```css
.cards { display: grid; grid-template-columns: repeat(auto-fit, minmax(280px, 1fr)); gap: var(--sp-m); }
.card { border: 1px solid var(--line); border-radius: 8px; padding: var(--sp-m); background: var(--bg); }
.card.accent { background: var(--accent-soft); border-color: transparent; }
.card.ext { background: var(--surface); }   /* EXT: kicker NEEDS PRODUCT CONFIRMATION */
```

### Claim markers

```css
.est    { font-size: 11px; color: var(--muted); margin-left: 4px; }
.verify { font-size: 11px; color: var(--negative); border: 1px solid var(--negative); border-radius: 999px; padding: 0 6px; margin-left: 4px; }
```

### CTA link: one per page at most

```css
.cta { display: inline-flex; align-items: center; gap: 8px; background: var(--accent); color: var(--accent-text);
       border-radius: 6px; padding: 10px 18px; font-weight: 600; font-size: 14px; text-decoration: none; }
```

### Footer line

```html
<footer class="foot-line">
  <span>Research date · Profile v1 (date) · Capability catalog v1.0.0 (date) · Sources: 42 · Models: …</span>
</footer>
```

```css
.foot-line { font-family: var(--font-mono); font-size: 11px; color: var(--muted);
             border-top: 1px solid var(--line); padding-top: var(--sp-s); }
```

## Logo

- Only from the style file: `logo_url` on light, `logo_dark_url` on dark, as `<img src="<public URL>" alt="<org name>">`, at least 96px wide.
- If only `logo_url` exists and it is dark, it may vanish in dark mode. Put it on a small light `--surface`-coloured plate, or use the wordmark in dark mode.
- No URL: a text wordmark (`wordmark` from the style file, or the org name) in `--font-sans`, 600 weight, 18px.
- A published artifact is a single page: never reference a local file path for the logo.

## Quick page skeleton

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Acme Retail research</title>
  <!-- brand font <link> here, only when style.md names one -->
  <style>
    /* paste the variables, base typography and components from above */
  </style>
</head>
<body>
  <main class="page">
    <header style="display:flex; justify-content:space-between; align-items:end; gap:16px; flex-wrap:wrap;
                   padding-bottom:24px; border-bottom:1px solid var(--line); margin-bottom:var(--sp-l);">
      <span style="font-weight:600; font-size:18px;">Your org</span>
      <span class="t-kicker">CURE · ACCOUNT RESEARCH</span>
    </header>

    <section>
      <h1 class="t-h1">Acme Retail: where the work <span class="kw">piles up.</span></h1>
      <p class="t-body-lg" style="max-width:62ch; color:var(--muted);">Three to five lines of summary.</p>
    </section>

    <footer class="foot-line"><span>Research date · Profile v1 · Capability catalog v1.0.0 · Sources: N · Models: …</span></footer>
  </main>
</body>
</html>
```

Set `lang` to the report language.

## Don'ts

- Accent as a large flat fill behind body text.
- Accent-coloured text that fails the contrast check.
- A third typeface.
- Hard-coded hex values inline; use the variables.
- Stretching, recolouring or redrawing a logo.
- More than one CTA on a page.
