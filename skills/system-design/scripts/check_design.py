#!/usr/bin/env python3
"""Structural gate for a system-design document or ADR (stdlib only).

It checks that the parts a reviewer needs are present and concrete. It cannot
judge whether the design is good - that is the reviewer's job - but it stops a
document that hand-waves the parts that are easiest to hand-wave.

Usage: check_design.py <file.md> [--kind design|adr] [--draft] [--json]
Exit:  0 = passes, 1 = gaps found (listed), 2 = usage or read error.

Design documents need:
  - a requirements section with functional and non-functional parts, and at
    least two numeric targets (latency, availability, throughput, RPO/RTO, ...)
  - a non-goals / out-of-scope section
  - an estimation / capacity section with numbers
  - a trade-off table with a "Change it when" column, at least three rows, and
    in every row an observable trigger: a number plus a comparison
  - a failure section (failure modes, cascades, disaster recovery)
  - an evolution section (10x / 100x, migration)
  - a review log (skipped with --draft, for a check before the review phase)
ADRs need: Context, Decision, Consequences, and at least one "change it when"
trigger with a number. Both fail on template leftovers (TODO, TBD, <...>).
"""
import argparse
import json
import re
import sys

UNIT = (r"(ms|s|sec|seconds?|min|minutes?|h|hours?|%|nines|qps|rps|tps|req/s|requests?/s|"
        r"writes?/s|reads?/s|ops/s|msg/s|events?/s|[kmgtp]i?b(/s)?|bytes?|users?|dau|mau|"
        r"tenants?|items?|rows?|records?|connections?|regions?|x|times)")
NUMBER_WITH_UNIT = re.compile(r"(?<![\w.])\d[\d,_.]*\s*[kmb]?\s*" + UNIT + r"(?![a-z0-9])", re.I)
NUMBER = re.compile(r"\d")
COMPARISON = re.compile(
    r"(>|<|≥|≤|>=|<=|exceeds?|exceeding|above|below|over|under|more than|less than|"
    r"reach(es)?|drops?|falls?|rises?|grows?|beyond|at least|at most|crosses|hits?|surpass)", re.I)
PLACEHOLDER = re.compile(r"\b(TODO|TBD|FIXME|XXX)\b|\?\?\?|<([a-z][a-z _-]*)>", re.I)
# Real HTML that GitHub-flavoured Markdown allows in prose and tables is not a placeholder.
HTML_TAGS = {"br", "b", "i", "em", "strong", "sup", "sub", "details", "summary", "kbd", "code",
             "p", "div", "span", "hr", "ul", "ol", "li", "table", "tr", "td", "th", "img", "a",
             "s", "u", "mark", "small", "pre", "blockquote", "picture", "source"}

SECTIONS = {
    "requirements": r"requirement",
    "non_functional": r"non[- ]?functional|nfr|quality attributes|slo",
    "functional": r"(?<!non-)(?<!non )\bfunctional\b|use cases|user stories|scope",
    "non_goals": r"non[- ]?goals?|out of scope|not in scope|exclusions",
    "estimation": r"estimat|capacity|back[- ]of[- ]the[- ]envelope|sizing|scale numbers",
    "failure": r"fail|cascade|resilien|disaster|outage|degrad",
    "evolution": r"evolution|10x|100x|growth path|migration|roadmap|scaling path",
    "context": r"context|problem",
    "decision": r"decision",
    "consequences": r"consequence|trade[- ]?off",
    "review": r"review",
}


def sections(text):
    """(heading, body) pairs. A body runs to the next heading of the same or a higher level,
    so it includes its own subsections. Headings inside code fences are not headings."""
    lines = text.splitlines()
    heads, fence = [], False  # (line index, level, title)
    for i, line in enumerate(lines):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        m = None if fence else re.match(r"^\s{0,3}(#{1,6})\s+(.*?)\s*#*\s*$", line)
        if m:
            heads.append((i, len(m.group(1)), m.group(2)))
    out = []
    for n, (i, level, title) in enumerate(heads):
        end = next((j for j, lv, _ in heads[n + 1:] if lv <= level), len(lines))
        out.append((title, "\n".join(lines[i + 1:end])))
    return out


def find(secs, key):
    pat = re.compile(SECTIONS[key], re.I)
    return [(h, b) for h, b in secs if h and pat.search(h)]


def tables(text):
    """Yield markdown tables as lists of cell rows (header first, separator dropped)."""
    rows = []
    for line in text.splitlines() + [""]:
        s = line.strip()
        if s.startswith("|") and s.count("|") >= 2:
            cells = [c.strip() for c in s.strip("|").split("|")]
            if all(re.fullmatch(r":?-{2,}:?", c) for c in cells if c):
                continue
            rows.append(cells)
        elif rows:
            yield rows
            rows = []


def tradeoff_tables(text):
    for t in tables(text):
        header = [c.lower() for c in t[0]]
        col = next((i for i, c in enumerate(header) if re.search(r"change (it )?when|revisit when", c)), None)
        if col is not None:
            yield t, col


def check(text, kind, draft=False):
    problems, notes = [], []
    secs = sections(text)

    # Placeholders are looked for in prose only: code fences and `inline code` legitimately
    # hold things like `<tenant>` or WHERE ... AND <condition>.
    fence = False
    for i, line in enumerate(text.splitlines(), 1):
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence or line.lstrip().startswith("<!--"):
            continue
        prose = re.sub(r"`[^`]*`", "", line)
        hits = [m for m in PLACEHOLDER.finditer(prose)
                if not (m.group(2) and m.group(2).strip().lower() in HTML_TAGS)]
        if hits:
            problems.append(f"line {i}: template leftover or placeholder: {line.strip()[:80]}")

    found_tables = list(tradeoff_tables(text))

    if kind == "adr":
        for key in ("context", "decision", "consequences"):
            if not find(secs, key):
                problems.append(f"missing section: {key}")
        triggers = [row[col] for t, col in found_tables for row in t[1:] if col < len(row)]
        prose = re.findall(r"change (?:it )?when[^\n]*", text, re.I)
        if not any(NUMBER.search(x) and COMPARISON.search(x) for x in triggers + prose):
            problems.append("no 'change it when' trigger with a number and a comparison "
                            "(when would this decision be revisited?)")
        return problems, notes

    req = find(secs, "requirements")
    if not req:
        problems.append("missing section: requirements")
    if not find(secs, "functional"):
        problems.append("missing section: functional requirements (or use cases / scope)")
    nfr = find(secs, "non_functional")
    if not nfr:
        problems.append("missing section: non-functional requirements")
    else:
        nums = sum(len(NUMBER_WITH_UNIT.findall(b)) for _, b in nfr)
        if nums < 2:
            problems.append(f"non-functional requirements have {nums} numeric target(s); need at least 2 "
                            "(e.g. p99 < 200 ms, 99.95% availability, RPO 5 min)")
    if not find(secs, "non_goals"):
        problems.append("missing section: non-goals / out of scope")
    est = find(secs, "estimation")
    if not est:
        problems.append("missing section: estimation / capacity")
    elif not any(NUMBER.search(b) for _, b in est):
        problems.append("estimation section has no numbers")
    if not find(secs, "failure"):
        problems.append("missing section: failure modes / cascades / disaster recovery")
    if not find(secs, "evolution"):
        problems.append("missing section: evolution (10x / 100x, migration)")
    if not draft and not find(secs, "review"):
        problems.append("missing section: review log (reviewer and agy findings, accepted or "
                        "rejected); pass --draft to check a doc before review")

    if not found_tables:
        problems.append("no trade-off table with a 'Change it when' column")
    else:
        rows = [(row, col) for t, col in found_tables for row in t[1:]]
        if len(rows) < 3:
            problems.append(f"trade-off table has {len(rows)} row(s); need at least 3 decisions")
        for row, col in rows:
            name = row[0][:60] if row else "?"
            cell = row[col] if col < len(row) else ""
            if not NUMBER.search(cell) or not COMPARISON.search(cell):
                problems.append(f"trade-off row '{name}': trigger is not observable "
                                f"(needs a number and a comparison): '{cell[:80]}'")
        notes.append(f"{len(rows)} trade-off row(s) checked")
    return problems, notes


def main(argv=None):
    p = argparse.ArgumentParser(description="Structural gate for a design doc or ADR.")
    p.add_argument("file")
    p.add_argument("--kind", choices=["design", "adr"], default="design")
    p.add_argument("--json", action="store_true")
    p.add_argument("--draft", action="store_true", help="the doc has not been reviewed yet; skip the review-log check")
    a = p.parse_args(argv)
    try:
        with open(a.file, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        print(f"check_design: cannot read {a.file}: {e}", file=sys.stderr)
        return 2
    problems, notes = check(text, a.kind, draft=a.draft)
    if a.json:
        print(json.dumps({"file": a.file, "kind": a.kind, "ok": not problems,
                          "problems": problems, "notes": notes}, indent=2))
    else:
        if problems:
            print(f"DESIGN_GAPS ({len(problems)}) in {a.file}:")
            for x in problems:
                print(f"  - {x}")
        else:
            print(f"DESIGN_OK {a.file} ({'; '.join(notes) or a.kind})")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
