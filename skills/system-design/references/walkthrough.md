# Walkthrough (--walkthrough)

An animated, step-by-step page that walks a reader through the design: the brief, the numbers,
the simplest draft, what breaks first, each fix and what it costs, one failure walked hop by hop,
the 10x step, and the trade-off table. It is a **rendering of the design doc**, not a second
source: every number, box and decision in it comes from the doc and the calculator output.

You write data; the player draws it. Never write HTML, CSS, SVG or JavaScript for it.

## Contents
- [When](#when)
- [Files](#files)
- [The story](#the-story)
- [Schema](#schema)
- [Layout on the grid](#layout-on-the-grid)
- [Writing a step](#writing-a-step)
- [Render and fix](#render-and-fix)
- [Traps](#traps)

## When

Only with `--walkthrough` or when the user asks for an animated or step-by-step walkthrough. Design
mode: after the gate prints `DESIGN_OK` in phase 10, so reviewer fixes never force a rewrite.
Review mode: walk the most severe finding (the failure path, then the fix). Deep-dive mode: the
problem, the options, the choice and one failure case. Never in interview mode.

In review and deep-dive modes the doc may have no Mermaid flowchart or calculator output: then
leave `doc` and `calc` out of the steps file (the gate says what it could not check) and use only
`nfr` and `derived` metrics. The steps file sits next to the reviewed doc or the write-up.

**Review mode recipe (5-8 steps).** Never edit the doc under review to make the walkthrough pass.
`frame` (what the doc promises, the target the defect breaks) -> `draft` (the doc's design as
written) -> `problem` (the defect, with its number) -> `case` (the failure walked hop by hop;
a second `case` if there is a second consequence) -> `fix` (your recommended change; `final`
goes here: the design as it should be) -> `recap` (optional; with no `doc`, the recap shows the
diagram and body only). Numbers you compute from the doc's own figures (3 retries at 3 layers =
64 calls) are `derived`: say the arithmetic in the body. Other findings stay in the review report.
**Deep-dive recipe:** `frame` -> `problem` -> one `fix` per option you weighed (state `removed`
for the losers) -> the chosen one `final` -> one `case` -> `recap`.

## Files

Next to the doc: `docs/design/<slug>.steps.json` (you write it) and
`docs/design/<slug>.walkthrough.html` (the script writes it: one self-contained file, no network,
light and dark, keyboard ←/→, R replay, Space pause, `#step-N` links, a print view).

## The story

8-14 steps. Each step changes one thing, and says what changed and by how much. Map them to the
phases you already did:

| chapter | from phase | the step shows |
|---|---|---|
| `frame` | 1 | the brief, the target that matters most; one or two boxes |
| `numbers` | 2 | the calculator's figures (a `table` panel), which ones force the design |
| `draft` | 4 | the simplest end-to-end path, requests flowing |
| `problem` | rule 8 | what breaks first at today's numbers: a gauge, a held queue, a breached chip |
| `fix` | 4-5 | the component that fixes it (the focus, state `new`), the number it moves; set `decision` to its trade-off row |
| `case` | 6 | one failure walked: a node `down`, `fail` and `retry` packets, the cascade in the chips; then a `fix` step with the defence |
| `scale` | 8 | what fires at 10x (`"scale": 10`), what changes first |
| `recap` | 8 | the settled diagram; the player shows the doc's trade-off table under it |

Exactly one step has `"final": true`: the one whose boxes and arrows are the doc's Mermaid
diagram (usually the last `fix` before the cases). Steps after it may add states, flows and
overlays, but keep the same boxes.

## Schema

```jsonc
{
  "title": "URL shortener",
  "summary": "One line: from what to what.",
  "doc": "url-shortener.md", "calc": "url-shortener.calc.json",   // paths relative to this file
  "grid": {"cols": 5, "rows": 3},                                   // cols 1-8, rows 1-6
  "zones": [{"id": "region", "label": "One region, 3 zones"}],      // optional: region, AZ, VPC, trust boundary
  "nodes": [
    {"id": "API", "label": "Redirect API", "sub": "stateless",       // id = the Mermaid node id
     "type": "service", "cell": [2, 1], "zone": "region"}            // type: service|db|cache|queue|ext|actor
  ],
  "edges": [
    {"id": "api_kv", "from": "API", "to": "KV", "label": "get by code",
     "mode": "sync", "route": "hv"}                                  // mode sync|async; route hv|vh
  ],
  "metrics": [
    {"id": "p99", "label": "p99 redirect", "unit": "ms", "source": "nfr", "target": "< 50"},
    {"id": "peak", "label": "peak redirects", "unit": "/s", "source": "calc:traffic.peak_read_qps"},
    {"id": "store", "label": "store reads", "unit": "/s", "source": "derived"}
  ],
  "steps": [{
    "short": "What breaks",                       // 1-2 words, the timeline label
    "chapter": "problem",
    "title": "Every click lands on the store",    // the result, not the mechanism
    "body": ["<= 2 paragraphs, <= 420 characters each"],
    "callout": {"kind": "warn", "text": "..."},   // insight | tip | warn; at most one
    "changes": ["~ Store 85% busy at peak", "~ p99 38 -> 120 ms", "- Target missed"],
    "show": ["C", "LB", "API", "KV"],             // every node visible in this step
    "focus": "KV",                                // at most one: the yellow node
    "state": {"R": "down"},                       // down | degraded | new | removed | ok
    "overlays": [{"on": "KV", "gauge": 85, "label": "! 11,458 reads/s"}],
    "flows": [{"edge": "api_kv", "packet": "req", "rate": 5, "held": 14}],
    "cut": ["eu_us"],                             // edges drawn broken (a partition)
    "zone_state": {"eu": "down"},                 // a whole zone or region lost
    "panels": [{"type": "table", "title": "...", "header": true, "rows": [["a", "b"]]}],
    "metrics": {"p99": "120", "store": "11,458"},
    "breach": ["store"],                          // optional: flag a chip that has no target
    "decision": "Redis cache-aside in front of the store",   // first cell of a trade-off row
    "doc_anchor": "#read-path",                   // a heading in the doc
    "final": true, "scale": 10, "cells": {"API": [2, 0]}, "hide_edges": ["e1"]
  }]
}
```

Field rules the gate holds you to:

- `changes` is required on `problem`, `fix`, `case` and `scale` steps, optional elsewhere. Each
  line starts with `+` (added), `-` (removed or broken) or `~` (changed: `~ p99 120 -> 9 ms`).
- Chip values are strings as you want them shown (`"11,458"`, `"114.6k"`, `"yes"`); `unit` is
  optional and appended unless the value carries one. A `calc:` value must be within 5% of the
  calculator's number (times the step's `scale`): round to 3-4 significant figures, never more.
  For a 10x step, use calculator x 10 even if a `--scale` table rounds differently.
- `target` is `<`, `<=`, `>` or `>=` and a number (`"< 50"`, `">= 99.95"`); a chip whose value
  crosses it is flagged. `breach` flags any chip, with or without a target.
- `final`: the step's visible node ids must equal the Mermaid node ids, and its visible edges'
  `from -> to` pairs must equal the Mermaid arrows (labels and dashes are not compared; a label
  difference is a note).
- `decision` is optional: set it only when the doc's trade-off table has that row (copy the first
  cell). A defence or a removal with no row simply has none.
- `doc_anchor` is `#` + a doc heading in lower case, punctuation dropped, spaces as hyphens
  (`## Read path` -> `#read-path`).
- `cells` (per step) moves a node for that step only; the next step without it puts the node back
  at its own `cell`, and the player slides it. `hide_edges` hides edges whose two nodes are both
  visible (an arrow the design dropped).
- An edge `label` is optional but most edges should name the protocol or event. `zone`: a node
  belongs to at most one zone.
- Gap messages number steps from 1 and name the step's `short`.

- **Packets** (by shape, never colour): `req` filled dot, `res` hollow dot (travels back),
  `fail` crossed square (stops part-way), `retry` dashed ring, `async` diamond, `heartbeat` small
  ring. `rate` is packets a second (0.3-6); `held: N` draws N waiting at the far end instead (a
  backlog, a full pool; `rate` is then ignored); `reverse: true` flips the direction.
- **Overlays**: `gauge` 0-100 draws a utilisation bar under the node; `label` (≤ 28 characters) a
  badge above it. Start a badge with `!` or `✕` when it is bad: it turns solid.
- **Panels** under the diagram: `table` (rows, optional `header`), `timeline` (rows of an
  interleaving, e.g. a race: `[["Ana reads", "left = 1"], ["Ben reads", "left = 1"]]`), `note`
  (`text`), `chart` (`points` [[x, y], ...], `mark` index, `mark_label`, `x_label`, `y_label`).
- **Metrics**: `source` is `calc:<section>.<key>` (the value must match `<slug>.calc.json`,
  times the step's `scale`), `nfr` (a target from the requirements) or `derived` (you computed it;
  say how in the body). A chip carries its last value forward; a value past its `target` is
  flagged `!` with a heavy border. Give the recap its steady-state values.

## Layout on the grid

Put each node in a cell `[col, row]`. Requests flow left to right: clients in column 0, the edge
next, services in the middle, stores and queues to the right, async consumers below.
The player routes every edge through the gaps between cells, so an edge never crosses a box. Two
things are yours:

- No two visible nodes in one cell. A node that replaces another (a monolith splitting) may take
  its cell in a later step; to move a node, give the step `cells`.
- A zone's box spans its members' cells; a node outside the zone must not sit inside that span.
- An edge between different rows and columns leaves sideways by default (`"route": "hv"`: out
  of the left or right side, then up or down). When a node already has an edge leaving that side
  (or two), set `"route": "vh"` on the edges that go to another row: they leave from the top or
  bottom instead and the picture stays readable.
- At most 15 visible nodes. Bigger: an overview step, then detail steps.

## Writing a step

- **Carry the number.** Every `problem`, `fix`, `case` and `scale` step moves at least one chip,
  and its `changes` say `before -> after` ("p99 120 -> 9 ms"). A step without a number is a slide,
  not a walkthrough.
- **One idea per step.** If the body needs a third paragraph, it is two steps.
- **Say what breaks next.** A `fix` step's callout or body names what the fix costs (staleness,
  a new dependency): the site this format borrows from earns its clarity by never letting a fix
  arrive free.
- **The focus is the thing that changed**, not the most important box overall.
- Labels ≤ 18 characters, sub-labels ≤ 22: detail goes in the body.

## Render and fix

```bash
python3 ${CLAUDE_SKILL_DIR}/scripts/render_walkthrough.py docs/design/<slug>.steps.json
```

`WALKTHROUGH_OK ... -> <slug>.walkthrough.html` or `WALKTHROUGH_GAPS` with a list. Fix every gap
and run it again; never edit the HTML. It checks the steps against the doc (the `final` step
equals the Mermaid flowchart, `decision` names a trade-off row, `doc_anchor` names a heading) and
against the calculator (`calc:` metrics). Its notes (no failure step, no recap) are worth fixing
too. Tell the user the file path and that it opens offline in any browser.

## Traps

- Inventing numbers for the chips. If the doc does not have the number, the walkthrough does not
  either: add it to the doc first (from the calculator), then show it.
- A `final` step that differs from the doc's Mermaid: change whichever is wrong, then re-run both
  gates.
- Every edge animated in every step. Animate only the path the step is about; let the rest sit.
