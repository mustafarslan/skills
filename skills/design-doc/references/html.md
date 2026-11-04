# design-doc — HTML and PDF reference

Paste the contents of `tokens.css` into a `<style>` block, then add the base styles and the
components you need. Do not link it from the skill folder: the document has to render on its own
after it is mailed, moved or the skill is updated. Everything below uses only tokens.

## Base

```css
*, *::before, *::after { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; }
body {
  margin: 0;
  font-family: var(--font-sans);
  font-size: var(--t-base);
  line-height: 1.6;
  color: var(--text-2);
  background: var(--bg);
}
.page { max-width: var(--wide); margin: 0 auto; padding: var(--s-8) var(--s-5); }
.prose { max-width: var(--measure); }

h1, h2, h3, h4 { color: var(--text-1); font-weight: 700; line-height: 1.2; margin: var(--s-7) 0 var(--s-3); }
h1 { font-size: var(--t-4xl); letter-spacing: -0.01em; margin-top: 0; }
h2 { font-size: var(--t-2xl); letter-spacing: -0.01em; }
h3 { font-size: var(--t-xl); }
h4 { font-size: var(--t-lg); }
p, ul, ol, dl { margin: 0 0 var(--s-4); }
a { color: var(--text-1); text-decoration: underline; text-underline-offset: 0.15em; }
a:focus-visible, button:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
small, .caption { font-size: var(--t-xs); color: var(--text-3); }
hr { border: 0; border-top: 1px solid var(--rule); margin: var(--s-7) 0; }
::selection { background: var(--accent); color: var(--text-1); }

/* The one inline accent: one per section */
mark { background: var(--accent); color: var(--text-1); padding: 0 0.15em; border-radius: var(--radius);
       box-decoration-break: clone; -webkit-box-decoration-break: clone; }

/* Section label: small, sentence case, muted */
.label { font-size: var(--t-xs); font-weight: 600; color: var(--text-3); margin: 0 0 var(--s-2); }
```

Why `<mark>`: it is the semantic element for "highlighted for relevance", so assistive tech and
copy-paste keep the meaning, and the accent fill carries ink text at 12.06:1.

## Page header and footer

```html
<header class="doc-head">
  <span class="doc-title">Runbook: restoring a database backup</span>
  <span class="doc-meta">v1.2 · 2 Nov 2026</span>
</header>
...
<footer class="page-foot">
  <span>OPS-014</span>
  <span class="page-no"></span>
</footer>
```

```css
.doc-head, .page-foot { display: flex; justify-content: space-between; gap: var(--s-4);
                       font-size: var(--t-xs); color: var(--text-3); }
.doc-head { padding-bottom: var(--s-3); border-bottom: 2px solid var(--text-1); margin-bottom: var(--s-7); }
.page-foot { padding-top: var(--s-3); border-top: 1px solid var(--rule); margin-top: var(--s-8); }
```

For print, the running page number comes from `@page` (see below); on screen the footer's
`.page-no` can hold a static "1 / 1" or be left empty.

## Callout (note, warning)

Glyph and label carry the meaning; the accent only draws the left rule.

```html
<aside class="callout" role="note">
  <p class="callout-label"><span class="glyph" aria-hidden="true">i</span> Note</p>
  <p>Backups older than 30 days are archived and take longer to restore.</p>
</aside>

<aside class="callout callout-warn" role="note">
  <p class="callout-label"><span class="glyph" aria-hidden="true">!</span> Warning</p>
  <p><strong>Restoring overwrites the current data.</strong> Take a fresh backup first.</p>
</aside>
```

```css
.callout { border-left: 4px solid var(--accent); background: var(--surface);
           padding: var(--s-4) var(--s-5); margin: var(--s-5) 0; border-radius: 0 var(--radius) var(--radius) 0; }
.callout > :last-child { margin-bottom: 0; }
.callout-label { margin: 0 0 var(--s-2); font-weight: 700; color: var(--text-1); display: flex; align-items: center; gap: var(--s-2); }
.glyph { display: inline-grid; place-items: center; width: 1.4em; height: 1.4em; font-size: var(--t-xs);
         font-weight: 700; border: 2px solid var(--text-1); border-radius: 50%; color: var(--text-1); }
.callout-warn .glyph { border-radius: 0; clip-path: polygon(50% 0, 100% 100%, 0 100%); border: 0;
                       background: var(--text-1); color: var(--bg); padding-top: 0.25em; }
.callout-warn { border-left-width: 8px; }   /* weight, not colour, marks the stronger message */
```

## Table

```html
<table class="data">
  <caption class="caption">Table 1. Restore times by backup age</caption>
  <thead><tr><th>Backup age</th><th class="num">Size (GB)</th><th class="num">Restore time (min)</th></tr></thead>
  <tbody>
    <tr><td>Under 7 days</td><td class="num">42</td><td class="num">12</td></tr>
    <tr><td>7 to 30 days</td><td class="num">40</td><td class="num">15</td></tr>
  </tbody>
</table>
```

```css
table.data { width: 100%; max-width: var(--wide); border-collapse: collapse; font-size: var(--t-sm); margin: var(--s-5) 0; }
table.data caption { text-align: left; padding-bottom: var(--s-2); }
table.data th { text-align: left; font-weight: 600; color: var(--text-1); padding: var(--s-2) var(--s-3);
                border-bottom: 2px solid var(--text-1); }
table.data td { padding: var(--s-2) var(--s-3); border-bottom: 1px solid var(--rule); color: var(--text-2); }
table.data tbody tr:nth-child(even) td { background: var(--surface); }
table.data .num { text-align: right; font-variant-numeric: tabular-nums; }
```

No accent inside tables (no `<mark>`, no coloured cells). To single a row out, make it bold.

## Code

```css
code { font-family: var(--font-mono); font-size: 0.92em; background: var(--surface);
       padding: 0.1em 0.35em; border-radius: var(--radius); color: var(--text-1); }
pre { background: var(--dark-surface); color: var(--on-dark-1); padding: var(--s-4) var(--s-5);
      border-radius: var(--radius); overflow-x: auto; line-height: 1.5; margin: var(--s-5) 0; }
pre code { background: none; padding: 0; color: inherit; font-size: var(--t-sm); }
```

## Figure with caption

```html
<figure><img src="restore-flow.svg" alt="Flow: pick backup, stop writes, restore, verify"><figcaption class="caption">Figure 1. The restore flow.</figcaption></figure>
```

```css
figure { margin: var(--s-6) 0; max-width: var(--wide); }
figure img { max-width: 100%; height: auto; display: block; }
figcaption { margin-top: var(--s-2); }
```

Diagrams use greys; the one step the reader must not miss gets the accent fill with ink text.
Draw them with `references/diagrams.md` (shapes, palette, a worked example), inline in the page.

## Step list

```html
<ol class="steps">
  <li><strong>Stop writes.</strong> <span class="result">Result: the app shows a maintenance page.</span></li>
  <li><strong>Restore the backup.</strong> <span class="result">Result: the restore job reports "complete".</span></li>
</ol>
```

```css
.steps { list-style: none; counter-reset: step; padding: 0; max-width: var(--measure); }
.steps li { counter-increment: step; position: relative; padding-left: var(--s-8); margin-bottom: var(--s-4); }
.steps li::before { content: counter(step); position: absolute; left: 0; top: 0.05em; width: 1.9em; height: 1.9em;
                    display: grid; place-items: center; font-weight: 700; font-size: var(--t-sm);
                    color: var(--bg); background: var(--text-1); border-radius: 50%; }
.steps .result { display: block; color: var(--text-3); font-size: var(--t-sm); }
```

## Do / Don't pair

```html
<div class="pair">
  <div><p class="pair-label">✓ Do</p><p>Name the file after the system it restores.</p></div>
  <div><p class="pair-label">✗ Don't</p><p><s>Name the file "final2".</s></p></div>
</div>
```

```css
.pair { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-5); margin: var(--s-5) 0; }
.pair > div { border-top: 2px solid var(--text-1); padding-top: var(--s-3); }
.pair-label { font-weight: 700; color: var(--text-1); margin: 0 0 var(--s-2); }
@media (max-width: 640px) { .pair { grid-template-columns: 1fr; } }
```

## Key figure

```html
<div class="stat"><span class="stat-num">12<span class="stat-unit"> min</span></span><span class="stat-label">Median restore time</span></div>
```

```css
.stat { display: inline-flex; flex-direction: column; gap: var(--s-1); margin-right: var(--s-7); }
.stat-num { font-size: var(--t-4xl); font-weight: 700; color: var(--text-1); line-height: 1.1; font-variant-numeric: tabular-nums; }
.stat-unit { font-size: var(--t-lg); font-weight: 600; color: var(--text-3); }
.stat-label { font-size: var(--t-sm); color: var(--text-3); }
```

## Print and PDF

```css
@page { size: A4; margin: 20mm 18mm 22mm;
        @bottom-right { content: counter(page) " / " counter(pages); font: 11px system-ui, sans-serif; color: #5C5C5C; } }
@media print {
  body { font-size: 11pt; }
  .page { max-width: none; padding: 0; }
  h1, h2, h3, h4 { break-after: avoid; }
  table, figure, pre, .callout, .steps li { break-inside: avoid; }
  a { text-decoration: none; }
  .no-print { display: none; }
  .page-foot .page-no { display: none; }   /* the @page counter numbers every page in print */
}
```

`@page` margin boxes do not read `var()`, so the font and the colour are written as literals
(`#5C5C5C` is the value of `--text-3`). Margin boxes need a current Chrome (tested on a recent
stable release, where page 1 of 2 prints "1 / 2"); on an older browser the footer number is
simply absent. The static `.page-no` in the footer is for the screen view; print hides it, so a
current Chrome does not print a stray "1" under the counter.

Headless Chrome prints it:

```bash
# macOS; on Linux use google-chrome or chromium, on Windows "%ProgramFiles%\Google\Chrome\Application\chrome.exe"
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" --headless --no-pdf-header-footer \
  --print-to-pdf="$PWD/out.pdf" "file://$PWD/doc.html"
```

Write the PDF next to the document in the user's project, never into the skill folder.

(`--no-pdf-header-footer` stops Chrome adding its own header and footer on top of the `@page` one.)

## Page skeleton

```html
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Document title</title>
  <style>/* tokens.css, then base, then the components you use */</style>
</head>
<body>
  <main class="page">
    <header class="doc-head"><span class="doc-title">Document title</span><span class="doc-meta">v1.0 · date</span></header>
    <h1>Document title</h1>
    <div class="prose">
      <p>Opening paragraph. One <mark>key phrase</mark> at most per section.</p>
    </div>
    <footer class="page-foot"><span>DOC-001</span><span class="page-no">1</span></footer>
  </main>
</body>
</html>
```
