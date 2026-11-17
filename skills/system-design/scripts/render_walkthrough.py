#!/usr/bin/env python3
"""Validate a walkthrough steps file and bundle it into one offline HTML page (stdlib only).

Usage: render_walkthrough.py <slug>.steps.json [--doc <slug>.md] [--calc <slug>.calc.json]
                             [--out <slug>.walkthrough.html] [--check] [--json]
Exit:  0 = WALKTHROUGH_OK (and the page written unless --check), 1 = gaps found (listed),
       2 = usage or read error.

The model writes data, not animation code: nodes on grid cells, edges, metrics, and steps that
say what is visible, what changed, which node is in focus and which packets flow. The player in
assets/walkthrough/ draws it. This script checks the data against the design doc and the
calculator output, so the walkthrough cannot drift from what the doc says:

  - schema: known chapters, node types, packet kinds, states; ids exist; 4-16 steps;
  - layout: <= 15 visible nodes per step, cells inside the grid, no two visible nodes in one
    cell, a zone's box holds no node from outside the zone, at most one focus node;
  - narrative: every step after the first has a "What changed" list (+ / - / ~ lines), body is
    at most two short paragraphs, labels fit their boxes;
  - numbers: a metric whose source is calc:<section>.<key> must show the calculator's value
    (within 5%, times the step's "scale" for a 10x/100x step);
  - doc: exactly one step is "final": its nodes and edges are the Mermaid flowchart in the doc;
    a "recap" step needs the doc's trade-off table, and a step's "decision" must name a row of it.
"""
import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import check_design  # noqa: E402  (reuses sections() and tradeoff_tables())

ASSETS = os.path.join(os.path.dirname(HERE), "assets", "walkthrough")
CHAPTERS = {"frame", "numbers", "draft", "problem", "fix", "case", "tradeoff", "scale", "recap"}
NODE_TYPES = {"service", "db", "cache", "queue", "ext", "actor"}
PACKETS = {"req", "res", "fail", "retry", "async", "heartbeat"}
STATES = {"down", "degraded", "new", "removed", "ok"}
CALLOUTS = {"insight", "tip", "warn"}
NEEDS_CHANGES = {"problem", "fix", "case", "scale"}
PANELS = {"timeline", "table", "note", "chart"}
MAX_NODES = 15
LABEL_MAX, SUB_MAX = 18, 22
BODY_MAX_PARAS, BODY_MAX_CHARS = 2, 420
TOLERANCE = 0.05


def number(text):
    """First number in a display value, with k/M/G/T suffixes: '11.5k' -> 11500."""
    m = re.search(r"-?\d[\d,]*(?:\.\d+)?\s*([kmgt](?![a-z]))?", str(text).replace(" ", ""), re.I)
    if not m:
        return None
    raw = m.group(0)
    suffix = (m.group(1) or "").lower()
    val = float(re.sub(r"[^\d.\-]", "", raw[:-1] if suffix else raw) or "nan")
    return val * {"k": 1e3, "m": 1e6, "g": 1e9, "t": 1e12}.get(suffix, 1)


def calc_value(calc, path):
    cur = calc
    for part in path.split("."):
        if not isinstance(cur, dict) or part not in cur:
            return None
        cur = cur[part]
    return cur if isinstance(cur, (int, float)) else None


# Node shapes, longest delimiters first; a quoted label may hold any bracket.
_SHAPES = [(r'\[\[', r'\]\]'), (r'\[\(', r'\)\]'), (r'\(\[', r'\]\)'), (r'\(\(\(', r'\)\)\)'),
           (r'\(\(', r'\)\)'), (r'\{\{', r'\}\}'), (r'\[/', r'/\]'), (r'\[\\', r'\\\]'),
           (r'\[', r'\]'), (r'\(', r'\)'), (r'\{', r'\}'), (r'>', r'\]')]
MERMAID_NODE = re.compile(r"\b([A-Za-z_][\w-]*)\s*(?:" + "|".join(
    rf'{o}\s*"(?P<q{i}>[^"]*)"\s*{c}|{o}(?P<p{i}>[^"]*?){c}' for i, (o, c) in enumerate(_SHAPES)) + ")")
# Arrows with a text label become plain arrows before anything else is parsed, so a label such
# as "GET /links (302)" or "cache-aside" is never read as a node.
LABELLED = [(re.compile(r"--\s+[^|]+?\s+(-->|---)"), r"\1"), (re.compile(r"-\.\s+[^|]+?\s+\.->"), "-.->"),
            (re.compile(r"==\s+[^|]+?\s+==>"), "==>"), (re.compile(r"(-->|-\.->|==>|---|-\.-|--[ox])\s*\|[^|]*\|"), r"\1")]
ARROW = re.compile(r"\s*(?:<?-->|<?-\.->|<?==>|---|-\.-|--[ox]|~~~)\s*")
SKIP = re.compile(r"(subgraph|end|style|classDef|class|click|linkStyle|direction)\b")


def _node_label(m):
    for k, v in m.groupdict().items():
        if v is not None:
            return re.sub(r"<br\s*/?>", " ", v).strip()
    return m.group(1)


def mermaid_graph(doc_text):
    """Nodes {id: label} and edges {(from, to)} of the first flowchart/graph block in the doc."""
    for m in re.finditer(r"```mermaid\s*\n(.*?)```", doc_text, re.S):
        body = m.group(1)
        first = body.strip().splitlines()[0] if body.strip() else ""
        if not re.match(r"\s*(flowchart|graph)\b", first):
            continue
        nodes, edges = {}, set()
        for line in body.strip().splitlines()[1:]:
            line = re.sub(r":::[\w-]+", "", line.split("%%")[0]).strip().rstrip(";")
            if not line or SKIP.match(line):
                continue
            for pat, rep in LABELLED:
                line = pat.sub(rep, line)
            chunks = ARROW.split(line)
            ids_per_chunk = []
            for chunk in chunks:
                ids = []
                for part in chunk.split("&"):
                    part = part.strip()
                    nm = MERMAID_NODE.match(part)
                    if nm:
                        nodes[nm.group(1)] = _node_label(nm)
                        ids.append(nm.group(1))
                    else:
                        im = re.match(r"([A-Za-z_][\w-]*)\s*$", part)
                        if im:
                            nodes.setdefault(im.group(1), im.group(1))
                            ids.append(im.group(1))
                ids_per_chunk.append(ids)
            for a_ids, b_ids in zip(ids_per_chunk, ids_per_chunk[1:]):
                for a in a_ids:
                    for b in b_ids:
                        edges.add((a, b))
        return nodes, edges
    return None, None


def doc_tradeoffs(doc_text):
    for rows, _col in check_design.tradeoff_tables(doc_text):
        if len(rows) >= 2:
            return {"header": rows[0], "rows": rows[1:]}
    return None


def norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[`*_]", "", str(s))).strip().lower()


def validate(spec, doc_text=None, calc=None):
    problems, notes = [], []
    P = problems.append
    nodes = {n.get("id"): n for n in spec.get("nodes", []) if isinstance(n, dict)}
    edges = {e.get("id"): e for e in spec.get("edges", []) if isinstance(e, dict)}
    metrics = {m.get("id"): m for m in spec.get("metrics", []) if isinstance(m, dict)}
    zones = {z.get("id"): z for z in spec.get("zones", []) if isinstance(z, dict)}
    grid = spec.get("grid") or {}
    cols, rows = grid.get("cols"), grid.get("rows")
    steps = spec.get("steps") or []

    if not spec.get("title"):
        P("missing top-level 'title'")
    if not (isinstance(cols, int) and isinstance(rows, int) and 1 <= cols <= 8 and 1 <= rows <= 6):
        P("'grid' needs integer cols (1-8) and rows (1-6)")
        cols, rows = 8, 6
    if len(nodes) != len(spec.get("nodes", [])):
        P("every node needs a unique 'id'")
    for nid, n in nodes.items():
        if n.get("type", "service") not in NODE_TYPES:
            P(f"node {nid}: type '{n.get('type')}' is not one of {sorted(NODE_TYPES)}")
        if not n.get("label"):
            P(f"node {nid}: missing 'label'")
        elif len(n["label"]) > LABEL_MAX:
            P(f"node {nid}: label '{n['label']}' is longer than {LABEL_MAX} characters (put detail in 'sub')")
        if n.get("sub") and len(n["sub"]) > SUB_MAX:
            P(f"node {nid}: sub '{n['sub']}' is longer than {SUB_MAX} characters")
        if not _cell_ok(n.get("cell"), cols, rows):
            P(f"node {nid}: 'cell' must be [col, row] inside the {cols}x{rows} grid")
        if n.get("zone") and n["zone"] not in zones:
            P(f"node {nid}: unknown zone '{n['zone']}'")
    if len(edges) != len(spec.get("edges", [])):
        P("every edge needs a unique 'id'")
    for eid, e in edges.items():
        for end in ("from", "to"):
            if e.get(end) not in nodes:
                P(f"edge {eid}: '{end}' {e.get(end)!r} is not a node")
        if e.get("from") == e.get("to"):
            P(f"edge {eid}: an edge cannot loop to its own node")
        if e.get("mode", "sync") not in ("sync", "async"):
            P(f"edge {eid}: mode must be sync or async")
        if e.get("route", "hv") not in ("hv", "vh"):
            P(f"edge {eid}: route must be hv (leave sideways first) or vh (leave up or down first)")
    for mid, m in metrics.items():
        src = str(m.get("source", ""))
        if not m.get("label"):
            P(f"metric {mid}: missing 'label'")
        if not (src.startswith("calc:") or src in ("nfr", "derived")):
            P(f"metric {mid}: source must be 'calc:<section>.<key>', 'nfr' or 'derived'")
        elif src.startswith("calc:") and calc is not None and calc_value(calc, src[5:]) is None:
            P(f"metric {mid}: {src} is not a number in the calculator output")

    if not 4 <= len(steps) <= 16:
        P(f"{len(steps)} steps: a walkthrough has 4-16 steps (split it, or add the missing ones)")
    finals = [i for i, s in enumerate(steps) if s.get("final")]
    if len(finals) != 1:
        P(f"exactly one step must have \"final\": true (the settled design); found {len(finals)}")

    for i, s in enumerate(steps):
        tag = f"step {i + 1} ({s.get('short') or s.get('chapter') or '?'})"
        if s.get("chapter") not in CHAPTERS:
            P(f"{tag}: chapter '{s.get('chapter')}' is not one of {sorted(CHAPTERS)}")
        if not s.get("title"):
            P(f"{tag}: missing 'title'")
        if not s.get("short"):
            P(f"{tag}: missing 'short' (one or two words for the timeline)")
        body = s.get("body") or []
        if not body:
            P(f"{tag}: missing 'body'")
        if len(body) > BODY_MAX_PARAS or any(len(p) > BODY_MAX_CHARS for p in body):
            P(f"{tag}: body is at most {BODY_MAX_PARAS} paragraphs of {BODY_MAX_CHARS} characters; move detail to the doc")
        if s.get("chapter") in NEEDS_CHANGES and not s.get("changes"):
            P(f"{tag}: a {s.get('chapter')} step needs a 'changes' list ('+ added', '- removed', '~ before -> after')")
        for c in s.get("changes") or []:
            if not re.match(r"\s*[+\-~−]", str(c)):
                P(f"{tag}: change '{c}' must start with +, - or ~")
        if s.get("callout") and s["callout"].get("kind") not in CALLOUTS:
            P(f"{tag}: callout kind must be one of {sorted(CALLOUTS)}")
        show = s.get("show") or []
        if not show:
            P(f"{tag}: 'show' lists the nodes visible in this step")
        unknown = [x for x in show if x not in nodes]
        if unknown:
            P(f"{tag}: unknown nodes in show: {unknown}")
        vis = [x for x in show if x in nodes]
        if len(vis) > MAX_NODES:
            P(f"{tag}: {len(vis)} visible nodes; at most {MAX_NODES} (split into an overview and a detail step)")
        cells = s.get("cells") or {}
        for nid, c in cells.items():
            if nid not in nodes:
                P(f"{tag}: cells names unknown node {nid}")
            elif not _cell_ok(c, cols, rows):
                P(f"{tag}: cell for {nid} is outside the grid")
        placed = {}
        for nid in vis:
            c = tuple(cells.get(nid) or nodes[nid].get("cell") or ())
            if c in placed:
                P(f"{tag}: {placed[c]} and {nid} share cell {list(c)}")
            placed[c] = nid
        # zones: the box spanning a zone's members must not hold another visible node
        for zid in zones:
            members = [placed_c for placed_c, nid in placed.items() if nodes[nid].get("zone") == zid]
            if not members:
                continue
            c0, c1 = min(c[0] for c in members), max(c[0] for c in members)
            r0, r1 = min(c[1] for c in members), max(c[1] for c in members)
            for c, nid in placed.items():
                if nodes[nid].get("zone") != zid and c0 <= c[0] <= c1 and r0 <= c[1] <= r1:
                    P(f"{tag}: {nid} sits inside zone '{zid}' but is not in it; move it out of the zone's box")
        focus = s.get("focus")
        if isinstance(focus, list):
            P(f"{tag}: one focus node at most (the accent marks one thing)")
        elif focus and focus not in vis:
            P(f"{tag}: focus '{focus}' is not visible in this step")
        for nid, st in (s.get("state") or {}).items():
            if nid not in vis:
                P(f"{tag}: state for {nid}, which is not visible")
            if st not in STATES:
                P(f"{tag}: state '{st}' is not one of {sorted(STATES)}")
        for o in s.get("overlays") or []:
            if o.get("on") not in vis:
                P(f"{tag}: overlay on {o.get('on')!r}, which is not visible")
            if o.get("gauge") is not None and not (isinstance(o["gauge"], (int, float)) and 0 <= o["gauge"] <= 100):
                P(f"{tag}: gauge must be a number 0-100")
            if o.get("label") and len(str(o["label"])) > 28:
                P(f"{tag}: overlay label '{o['label']}' is longer than 28 characters")
        for p in s.get("panels") or []:
            if p.get("type") not in PANELS:
                P(f"{tag}: panel type must be one of {sorted(PANELS)}")
        vis_set = set(vis)
        vis_edges = {eid for eid, e in edges.items() if e.get("from") in vis_set and e.get("to") in vis_set
                     and eid not in (s.get("hide_edges") or [])}
        for f in s.get("flows") or []:
            if f.get("edge") not in vis_edges:
                P(f"{tag}: flow on edge {f.get('edge')!r}, which is not visible in this step")
            if f.get("packet") not in PACKETS:
                P(f"{tag}: packet '{f.get('packet')}' is not one of {sorted(PACKETS)}")
        for zid, zst in (s.get("zone_state") or {}).items():
            if zid not in zones:
                P(f"{tag}: zone_state names unknown zone {zid!r}")
            if zst not in ("down", "ok"):
                P(f"{tag}: zone_state must be down or ok")
        for mid in s.get("breach") or []:
            if mid not in metrics:
                P(f"{tag}: breach names unknown metric {mid!r}")
        for eid in s.get("cut") or []:
            if eid not in vis_edges:
                P(f"{tag}: cut edge {eid!r} is not visible")
        for mid, val in (s.get("metrics") or {}).items():
            if mid not in metrics:
                P(f"{tag}: metric {mid!r} is not defined in 'metrics'")
                continue
            src = str(metrics[mid].get("source", ""))
            if src.startswith("calc:") and calc is not None:
                want = calc_value(calc, src[5:])
                got = number(val)
                scale = s.get("scale", 1) or 1
                if want is not None and got is not None and want * scale:
                    if abs(got - want * scale) / abs(want * scale) > TOLERANCE:
                        P(f"{tag}: metric {mid} shows {val} but the calculator says {want:g}"
                          + (f" x {scale}" if scale != 1 else "") + " (use source 'derived' for a value you computed)")
                elif got is None:
                    P(f"{tag}: metric {mid} value {val!r} has no number")

    # cross-check against the design doc
    if doc_text is not None:
        mnodes, medges = mermaid_graph(doc_text)
        if mnodes is None:
            P("the design doc has no Mermaid flowchart to check the final step against")
        elif len(finals) == 1:
            s = steps[finals[0]]
            vis = {x for x in s.get("show") or [] if x in nodes}
            want_nodes = set(mnodes)
            if vis != want_nodes:
                missing, extra = sorted(want_nodes - vis), sorted(vis - want_nodes)
                P(f"final step {finals[0] + 1} does not match the doc's Mermaid: "
                  + (f"missing {missing}" if missing else "") + ("; " if missing and extra else "")
                  + (f"not in the doc {extra}" if extra else ""))
            have_edges = {(e["from"], e["to"]) for e in edges.values()
                          if e.get("from") in vis and e.get("to") in vis and e["id"] not in (s.get("hide_edges") or [])}
            if have_edges != medges:
                missing, extra = sorted(medges - have_edges), sorted(have_edges - medges)
                P("final step's edges do not match the doc's Mermaid: "
                  + (f"missing {missing}" if missing else "") + ("; " if missing and extra else "")
                  + (f"not in the doc {extra}" if extra else ""))
            for nid in vis & want_nodes:
                if norm(nodes[nid].get("label", "")) != norm(mnodes[nid]) and mnodes[nid] != nid:
                    notes.append(f"label of {nid} differs from the doc ('{nodes[nid].get('label')}' vs '{mnodes[nid]}')")
        to = doc_tradeoffs(doc_text)
        decisions = {norm(r[0]) for r in (to or {}).get("rows", [])}
        if any(s.get("chapter") == "recap" for s in steps) and not to:
            P("a recap step needs the doc's trade-off table (Decision | Solves | Worsens | Change it when)")
        for i, s in enumerate(steps):
            if s.get("decision") and norm(s["decision"]) not in decisions:
                P(f"step {i + 1}: decision '{s['decision']}' is not a row of the doc's trade-off table "
                  "(copy the row's first cell, or leave 'decision' out)")
            anchor = s.get("doc_anchor")
            if anchor and not _anchor_ok(anchor, doc_text):
                P(f"step {i + 1}: doc_anchor {anchor} matches no heading in the doc "
                  "(use '#' + the heading in lower case with spaces as hyphens)")
    if not any(s.get("chapter") == "recap" for s in steps):
        notes.append("no recap step: the trade-off table is not shown")
    if not any(f.get("packet") == "fail" for s in steps for f in s.get("flows") or []) and \
            not any((s.get("state") or {}) for s in steps):
        notes.append("no step shows a failure (no 'fail' packet or node state): walk at least one")
    return problems, notes


def _cell_ok(c, cols, rows):
    return (isinstance(c, list) and len(c) == 2 and all(isinstance(v, int) for v in c)
            and 0 <= c[0] < cols and 0 <= c[1] < rows)


def _slug(h):
    return re.sub(r"[^\w\- ]", "", h.lower()).strip().replace(" ", "-")


def _anchor_ok(anchor, doc_text):
    want = anchor.lstrip("#")
    return any(_slug(h) == want for h, _ in check_design.sections(doc_text))


def bundle(spec, doc_text, doc_rel):
    def read(name):
        with open(os.path.join(ASSETS, name), encoding="utf-8") as fh:
            return fh.read()
    payload = dict(spec)
    payload["_doc"] = {"path": doc_rel, "tradeoffs": doc_tradeoffs(doc_text) if doc_text else None}
    data = json.dumps(payload, ensure_ascii=False).replace("</", "<\\/")
    title = _html_escape(spec.get("title", "Walkthrough"))
    return ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
            "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1\">\n"
            f"<title>{title} - walkthrough</title>\n"
            f"<style>\n{read('tokens.css')}\n{read('player.css')}\n</style>\n</head>\n<body>\n"
            "<main id=\"wt\"></main>\n"
            f"<script type=\"application/json\" id=\"wt-data\">{data}</script>\n"
            f"<script>\n{read('player.js')}\n</script>\n</body>\n</html>\n")


def _html_escape(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main(argv=None):
    p = argparse.ArgumentParser(description="Validate a walkthrough steps file and bundle it into one HTML page.")
    p.add_argument("steps")
    p.add_argument("--doc", help="the design doc (default: the steps file's 'doc', next to it)")
    p.add_argument("--calc", help="capacity_calc.py output (default: the steps file's 'calc', next to it)")
    p.add_argument("--out", help="output page (default: <slug>.walkthrough.html next to the steps file)")
    p.add_argument("--check", action="store_true", help="validate only; write nothing")
    p.add_argument("--json", action="store_true")
    a = p.parse_args(argv)
    base = os.path.dirname(os.path.abspath(a.steps))
    try:
        with open(a.steps, encoding="utf-8") as fh:
            spec = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"render_walkthrough: cannot read {a.steps}: {e}", file=sys.stderr)
        return 2
    doc_path = a.doc or (os.path.join(base, spec["doc"]) if spec.get("doc") else None)
    calc_path = a.calc or (os.path.join(base, spec["calc"]) if spec.get("calc") else None)
    doc_text = calc = None
    try:
        if doc_path:
            with open(doc_path, encoding="utf-8") as fh:
                doc_text = fh.read()
        if calc_path:
            with open(calc_path, encoding="utf-8") as fh:
                calc = json.load(fh)
    except (OSError, ValueError) as e:
        print(f"render_walkthrough: cannot read input: {e}", file=sys.stderr)
        return 2
    problems, notes = validate(spec, doc_text, calc)
    if doc_text is None:
        notes.append("no design doc given: the final step and the recap were not checked")
    if calc is None:
        notes.append("no calculator output given: calc metrics were not checked")
    out = a.out or re.sub(r"(\.steps)?\.json$", "", a.steps) + ".walkthrough.html"
    if not problems and not a.check:
        doc_rel = os.path.relpath(doc_path, os.path.dirname(os.path.abspath(out))) if doc_path else None
        os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
        with open(out, "w", encoding="utf-8") as fh:
            fh.write(bundle(spec, doc_text, doc_rel))
    if a.json:
        print(json.dumps({"steps": a.steps, "ok": not problems, "problems": problems, "notes": notes,
                          "out": None if problems or a.check else out}, indent=2))
    elif problems:
        print(f"WALKTHROUGH_GAPS ({len(problems)}) in {a.steps}:")
        for x in problems:
            print(f"  - {x}")
    else:
        print(f"WALKTHROUGH_OK {a.steps}" + ("" if a.check else f" -> {out}")
              + (f" ({'; '.join(notes)})" if notes else ""))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
