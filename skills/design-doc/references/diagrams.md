# Diagrams

The one recipe for diagrams in the house style: architecture, data flow, sequence-like flows and
state diagrams drawn as inline SVG. `design-doc` uses the light variant, `design-video` the dark
one, and `system-design --html` draws its styled diagrams from it. This file is byte-identical in
`design-doc/references/` and `design-video/references/` (check with
`cmp design-doc/references/diagrams.md design-video/references/diagrams.md`); change one, copy
it to the other.

## Contents
- [Rules](#rules)
- [Palette](#palette)
- [Components](#components)
- [Layout](#layout)
- [Worked example](#worked-example)
- [Dark variant (video and dark blocks)](#dark-variant-video-and-dark-blocks)
- [From Mermaid](#from-mermaid)
- [Checklist](#checklist)

## Rules

- **Greys carry the structure; the accent marks one thing.** At most **one** accent-filled node
  per diagram: the component, step or state the reader must not miss. Its text is ink
  (`#121212`). The accent is never a line, an arrow, a border or text on a light background
  (1.55:1 on white).
- **No other hue.** Status (failed, degraded, new, removed) is a glyph plus a word in the node
  (`✕ down`, `⚠ degraded`, `+ new`, `− removed`), never red, green or blue.
- **System fonts only**, no webfont, no external resource of any kind: the SVG sits in the page
  and works offline. Sans for names, mono for identifiers, ports and protocols.
- **Sentence case** labels; no all-caps, no tracked letter-spacing.
- **Small:** at most about 15 nodes. Past that, split into two figures (overview, then detail).
- **Square-ish and flat:** corner radius 2, 1.5px strokes, no shadows, gradients or blur.
- **Accessible:** `role="img"`, a `<title>` and a `<desc>` that says what the diagram shows in a
  sentence, and a `<figcaption>` under it. Never rely on colour alone.

## Palette

| Role | Light (documents) | Dark (video, dark blocks) | Contrast |
|---|---|---|---|
| Stage (page / frame) | `#FFFFFF` (`--bg`) | `#0A0A0A` (`--dark-bg`) | - |
| Node fill | `#F2F2F2` (`--surface`) | `#161616` (`--dark-surface`) | - |
| Node name (ink) | `#121212` (`--text-1`) | `#F5F5F5` (`--on-dark-1`) | 16.73 on node / 16.60 on node |
| Sublabel, edge label | `#5C5C5C` (`--text-3`) | `#B3B3B3` (`--on-dark-2`) | 5.97 on node, 6.69 on stage / 8.63 on node, 9.44 on stage |
| Node border, arrows | `#121212` borders, `#5C5C5C` arrows | `#B3B3B3` borders and arrows | ≥ 3:1 against the stage (non-text) |
| Boundary (region, trust zone) | `#DADADA` dashed, label in `#5C5C5C` | `#242424` dashed, label in `#B3B3B3` | decorative line; the label carries the meaning |
| Focus node | fill `#FFC800`, text `#121212` | fill `#FFC800`, text `#121212` | 12.06 |

Contrast figures are computed from `tokens.css` (WCAG relative luminance).

## Components

Every diagram starts with this `<style>` block inside the `<svg>`, so it renders the same pasted
into any page. Literal hex values (not `var()`) keep a standalone `.svg` file correct too.

```html
<style>
  .stage { fill: #FFFFFF; }
  .node { fill: #F2F2F2; stroke: #121212; stroke-width: 1.5; }
  .focus { fill: #FFC800; stroke: #121212; stroke-width: 1.5; }
  .ext { fill: #FFFFFF; stroke: #121212; stroke-width: 1.5; stroke-dasharray: 2 3; }
  .boundary { fill: none; stroke: #DADADA; stroke-width: 1.5; stroke-dasharray: 6 4; }
  .edge { fill: none; stroke: #5C5C5C; stroke-width: 1.5; }
  .edge.async { stroke-dasharray: 6 4; }
  .name { font: 600 14px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; fill: #121212; }
  .sub { font: 400 12px ui-monospace, "SF Mono", Menlo, Consolas, monospace; fill: #5C5C5C; }
  .elabel { font: 400 12px ui-monospace, "SF Mono", Menlo, Consolas, monospace; fill: #5C5C5C; }
  .blabel { font: 600 12px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; fill: #5C5C5C; }
  .halo { fill: #FFFFFF; }
  .fx { fill: #121212; }
  .inner { fill: none; stroke: #121212; stroke-width: 1.5; }
</style>
<defs>
  <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8"
          orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" fill="#5C5C5C"/></marker>
</defs>
```

| Shape | Means | SVG |
|---|---|---|
| Rectangle | a service or component | `<rect class="node" x y width="160" height="56" rx="2"/>` + name and a mono sublabel |
| Accent rectangle | the one thing to notice | same with `class="focus"`; its texts add class `fx` (ink) |
| Cylinder | a datastore | a `node` path (ellipse top, straight sides, ellipse bottom) plus an `inner` arc for the rim (see the example) |
| Rectangle with two inner bars | a queue or stream | `node` rect plus two short vertical `inner` lines inside each end |
| Dashed-outline rectangle | an external system or actor (not ours) | `class="ext"` |
| Solid arrow | synchronous call | `<path class="edge" marker-end="url(#arrow)"/>`, label = protocol |
| Dashed arrow | asynchronous (event, message, job) | `class="edge async"`, label = event name |
| Dashed grey frame | a region, AZ, VPC or trust boundary | `class="boundary"`, label top-left in `.blabel` |

Edge labels sit on a white `halo` rectangle (2px padding) so a line never runs through text.

## Layout

- 4px grid: every x, y, width and height is a multiple of 4.
- Flow left to right (requests) or top to bottom (pipelines); never both in one figure.
- Nodes 160 x 56 by default; 48px horizontal gap, 32px vertical gap; 24px inside a boundary.
- Edges are straight or one right-angle bend; no curves, no crossings (re-order nodes instead).
- `viewBox` sized to the content plus 24px; width 100% in the page, so it scales.

## Worked example

Write path of a small service: client, load balancer, API (the focus), Postgres, Redis, and an
outbox relay feeding Kafka for a worker. Paste into an HTML page or save as a `.svg` file.

```html
<figure>
<svg viewBox="0 0 968 352" width="100%" role="img" aria-labelledby="d1t d1d"
     xmlns="http://www.w3.org/2000/svg">
  <title id="d1t">Order write path</title>
  <desc id="d1d">A client calls the API through a load balancer. The API writes orders to Postgres,
  reads from a Redis cache, and an outbox relay publishes OrderPlaced to Kafka for a worker.</desc>
  <style>
    .stage { fill: #FFFFFF; }
    .node { fill: #F2F2F2; stroke: #121212; stroke-width: 1.5; }
    .focus { fill: #FFC800; stroke: #121212; stroke-width: 1.5; }
    .ext { fill: #FFFFFF; stroke: #121212; stroke-width: 1.5; stroke-dasharray: 2 3; }
    .boundary { fill: none; stroke: #DADADA; stroke-width: 1.5; stroke-dasharray: 6 4; }
    .edge { fill: none; stroke: #5C5C5C; stroke-width: 1.5; }
    .edge.async { stroke-dasharray: 6 4; }
    .name { font: 600 14px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; fill: #121212; }
    .sub { font: 400 12px ui-monospace, "SF Mono", Menlo, Consolas, monospace; fill: #5C5C5C; }
    .elabel { font: 400 12px ui-monospace, "SF Mono", Menlo, Consolas, monospace; fill: #5C5C5C; }
    .blabel { font: 600 12px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; fill: #5C5C5C; }
    .halo { fill: #FFFFFF; }
    .fx { fill: #121212; }
    .inner { fill: none; stroke: #121212; stroke-width: 1.5; }
  </style>
  <defs>
    <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="8" markerHeight="8"
            orient="auto-start-reverse"><path d="M0,0 L8,4 L0,8 z" fill="#5C5C5C"/></marker>
  </defs>
  <rect class="stage" width="968" height="352"/>

  <!-- trust boundary -->
  <rect class="boundary" x="196" y="24" width="748" height="304" rx="2"/>
  <text class="blabel" x="212" y="44">VPC, one region</text>

  <!-- client (external) -->
  <rect class="ext" x="24" y="96" width="136" height="56" rx="2"/>
  <text class="name" x="40" y="120">Client</text>
  <text class="sub" x="40" y="140">web, mobile</text>

  <!-- load balancer -->
  <rect class="node" x="220" y="96" width="140" height="56" rx="2"/>
  <text class="name" x="236" y="120">Load balancer</text>
  <text class="sub" x="236" y="140">L7, TLS</text>

  <!-- API: the focus -->
  <rect class="focus" x="408" y="96" width="160" height="56" rx="2"/>
  <text class="name fx" x="424" y="120">Order API</text>
  <text class="sub fx" x="424" y="140">modular monolith</text>

  <!-- Postgres (cylinder) -->
  <path class="node" d="M616,68 a76,10 0 0,1 152,0 v56 a76,10 0 0,1 -152,0 z"/>
  <path class="inner" d="M616,68 a76,10 0 0,0 152,0"/>
  <text class="name" x="636" y="104">Postgres</text>
  <text class="sub" x="636" y="124">orders, outbox</text>

  <!-- Redis (cylinder) -->
  <path class="node" d="M616,196 a76,10 0 0,1 152,0 v48 a76,10 0 0,1 -152,0 z"/>
  <path class="inner" d="M616,196 a76,10 0 0,0 152,0"/>
  <text class="name" x="636" y="228">Redis</text>
  <text class="sub" x="636" y="248">cache-aside</text>

  <!-- Kafka (queue/stream) -->
  <rect class="node" x="808" y="96" width="120" height="56" rx="2"/>
  <path class="inner" d="M816,104 v40 M920,104 v40"/>
  <text class="name" x="828" y="120">Kafka</text>
  <text class="sub" x="828" y="140">orders</text>

  <!-- worker -->
  <rect class="node" x="808" y="244" width="120" height="56" rx="2"/>
  <text class="name" x="824" y="268">Worker</text>
  <text class="sub" x="824" y="288">fulfilment</text>

  <!-- edges: sync solid, async dashed -->
  <path class="edge" marker-end="url(#arrow)" d="M160,124 H218"/>
  <rect class="halo" x="168" y="104" width="44" height="14"/>
  <text class="elabel" x="170" y="115">HTTPS</text>

  <path class="edge" marker-end="url(#arrow)" d="M360,124 H406"/>
  <rect class="halo" x="366" y="104" width="32" height="14"/>
  <text class="elabel" x="368" y="115">HTTP</text>
  <path class="edge" marker-end="url(#arrow)" d="M568,112 H614"/>
  <rect class="halo" x="578" y="92" width="28" height="14"/>
  <text class="elabel" x="580" y="103">SQL</text>

  <path class="edge" marker-end="url(#arrow)" d="M512,152 V220 H614"/>
  <rect class="halo" x="524" y="200" width="44" height="14"/>
  <text class="elabel" x="526" y="211">GET/SET</text>

  <path class="edge async" marker-end="url(#arrow)" d="M768,96 H806"/>
  <rect class="halo" x="768" y="76" width="40" height="14"/>
  <text class="elabel" x="770" y="87">relay</text>
  <path class="edge async" marker-end="url(#arrow)" d="M868,152 V242"/>
  <rect class="halo" x="874" y="188" width="64" height="14"/>
  <text class="elabel" x="876" y="199">OrderPlaced</text>
</svg>
<figcaption class="caption">Figure 1. Order write path. Solid: synchronous; dashed: asynchronous.
The highlighted API is the component this design changes.</figcaption>
</figure>
```

## Dark variant (video and dark blocks)

Same markup; swap the `<style>` block for this one. The focus node keeps its yellow fill and ink
text; on dark, the accent may also be text (11.65:1 on `#161616`), but keep it to the one focus.

```html
<style>
  .stage { fill: #0A0A0A; }
  .node { fill: #161616; stroke: #B3B3B3; stroke-width: 1.5; }
  .focus { fill: #FFC800; stroke: #FFC800; stroke-width: 1.5; }
  .ext { fill: #0A0A0A; stroke: #B3B3B3; stroke-width: 1.5; stroke-dasharray: 2 3; }
  .boundary { fill: none; stroke: #242424; stroke-width: 1.5; stroke-dasharray: 6 4; }
  .edge { fill: none; stroke: #B3B3B3; stroke-width: 1.5; }
  .edge.async { stroke-dasharray: 6 4; }
  .name { font: 600 14px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; fill: #F5F5F5; }
  .sub { font: 400 12px ui-monospace, "SF Mono", Menlo, Consolas, monospace; fill: #B3B3B3; }
  .elabel { font: 400 12px ui-monospace, "SF Mono", Menlo, Consolas, monospace; fill: #B3B3B3; }
  .blabel { font: 600 12px system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; fill: #B3B3B3; }
  .halo { fill: #0A0A0A; }
  .fx { fill: #121212; }
  .inner { fill: none; stroke: #B3B3B3; stroke-width: 1.5; }
</style>
```

The focus node's texts carry `class="name fx"` / `class="sub fx"`, so they stay ink on yellow in
both variants. Change the arrow marker's fill to `#B3B3B3`.

**In a video** the diagram is a frame element: scale the SVG so node names are at least
`--v-caption` (40px at 1080p) - with these 14px names that is a scale of about 2.9, so a
1920-wide frame holds at most 4-5 nodes across. Build it up one node or edge at a time (one
animated moment per chapter, see `moments.md` in design-video); the focus node arrives last.

## From Mermaid

In a repository, the Mermaid block in the design doc is the source of truth and stays
unstyled (GitHub renders it, and fixed colours would break GitHub's dark mode). A styled SVG
is a rendering of it:

- one SVG node per Mermaid node, with the same name; one edge per Mermaid edge, with the same
  label; each Mermaid `subgraph` becomes a boundary;
- the focus node is the one the design changes or the doc's deep dive is about;
- if the Mermaid changes, redraw the SVG; never let the two disagree.

## Checklist

- [ ] At most one accent-filled node; accent nowhere else (no lines, arrows, borders, light-background text).
- [ ] No hue besides the accent; states carry a glyph and a word.
- [ ] System fonts; no `<link>`, `@import`, `<image href="http…">` or other external resource.
- [ ] At most ~15 nodes; no crossing edges; 4px grid.
- [ ] Sync solid, async dashed, every edge labelled (protocol or event).
- [ ] `role="img"`, `<title>`, `<desc>`, and a `<figcaption>`.
- [ ] Matches its Mermaid source node for node and edge for edge.
