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
        r"tenants?|items?|rows?|records?|connections?|regions?|x|times|"
        r"/s|/sec|/min|/h|/day|/week|/month|/quarter|/year|"
        r"per (?:second|minute|hour|day|week|month|quarter|year))")
NUMBER_WITH_UNIT = re.compile(r"(?<![\w.])\d[\d,_.]*\s*[kmb]?\s*" + UNIT + r"(?![a-z0-9])", re.I)
NUMBER = re.compile(r"\d")
# A trigger's number must count something: a unit (50 ms, 8k/s), a currency ($80k), or a noun
# within two words ("> 12 engineers", "more than 5 enterprise tenants", "2 per year"). A bare
# digit ("grows beyond 2") or a date ("in Q3 2027") is not observable.
COUNTED = re.compile(
    r"[$€£]\s?\d|(?<![\w.])(?!(?:19|20)\d\d\b)\d[\d,_.]*\s*[kmb%]?\s*(?:[a-z][a-z-]*\s+){0,2}"
    r"(?:(?!(?:soon|later|now|again|ago|or|and|the|then|more|less|than|once|twice)\b)[a-z]{3,}|"
    + UNIT + r")(?![a-z0-9])", re.I)


def observable(cell):
    """A trigger is observable when it has a counted number and a comparison."""
    return bool((NUMBER_WITH_UNIT.search(cell) or COUNTED.search(cell)) and COMPARISON.search(cell))
COMPARISON = re.compile(
    r"(>=|<=|>|<|≥|≤|\b(?:exceeds?|exceeding|above|below|over|under|more than|less than|"
    r"reach(?:es)?|drops?|falls?|rises?|(?:out)?grows?|beyond|at least|at most|crosses|hits?|surpass(?:es)?)\b)", re.I)
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


TIME_NUMBER = re.compile(r"(?<![\w.])\d[\d,_.]*\s*(ms|s|sec|seconds?|min|minutes?|h|hours?)(?![a-z0-9])", re.I)
QPS_TRIGGER = re.compile(r"(?<![\w.])(\d[\d,_.]*)\s*([km])?\s*(qps|rps|tps|req/s|requests?/s|writes?/s|reads?/s|"
                         r"ops/s|msgs?/s|messages?/s|events?/s|/sec|/s|per second)(?![a-z0-9])", re.I)


def paragraphs(text, skip_sections=r"review|non[- ]?goals?|out of scope"):
    """Prose paragraphs outside code fences and tables, and outside the sections that only
    report on the design (review log) or exclude things from it (non-goals)."""
    out, cur, fence, skipping, skip_level = [], [], False, False, 0
    for line in text.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fence = not fence
            continue
        if fence:
            continue
        h = re.match(r"^\s{0,3}(#{1,6})\s+(.*)", line)
        if h:
            level = len(h.group(1))
            if skipping and level <= skip_level:
                skipping = False
            if not skipping and re.search(skip_sections, h.group(2), re.I):
                skipping, skip_level = True, level
            if cur:
                out.append(" ".join(cur))
                cur = []
            continue
        if skipping or line.lstrip().startswith("|"):
            if cur:
                out.append(" ".join(cur))
                cur = []
            continue
        if line.strip():
            cur.append(line)
        elif cur:
            out.append(" ".join(cur))
            cur = []
    if cur:
        out.append(" ".join(cur))
    return out


DOWNWARD = re.compile(r"(<|≤|<=|\b(?:below|under|less than|at most|drops?|falls?|shrinks?)\b)", re.I)
PER_ENTITY = re.compile(r"\b(?:per|each|any|one|a single|single|tenant|customer|user|sku|item|key|"
                        r"partition|shard|endpoint|merchant|group|device|error|retr(?:y|ies)|lag)\b", re.I)


def qps_value(m):
    v = float(m.group(1).replace(",", "").replace("_", ""))
    return v * {"k": 1e3, "m": 1e6}.get((m.group(2) or "").lower(), 1)


def strawman_triggers(rows, calc, low=1.0, high=100.0):
    """System-wide scale-up rate triggers that sit below today's peak (already fired) or far
    above it. Each clause of a trigger ("A, or B") is judged on its own."""
    t = calc.get("traffic", {})
    reads, writes = t.get("peak_read_qps", 0) or 0, t.get("peak_write_qps", 0) or 0
    found = []
    for row, col in rows:
        cell = row[col] if col < len(row) else ""
        for clause in re.split(r"\s*(?:,\s*or\b|;|\bor\b|,\s*and\b|\band\b)\s*", cell, flags=re.I):
            # a scale-down trigger, or one about a single tenant, key, SKU or endpoint, measures
            # a different quantity than the system peak
            if not clause or DOWNWARD.search(clause) or PER_ENTITY.search(clause):
                continue
            if re.search(r"\bwrites?\b", clause, re.I) and not re.search(r"\breads?\b", clause, re.I):
                peak = writes
            elif re.search(r"\breads?\b", clause, re.I) and not re.search(r"\bwrites?\b", clause, re.I):
                peak = reads
            else:
                peak = max(reads, writes)
            if not peak:
                continue
            for m in QPS_TRIGGER.finditer(clause):
                v = qps_value(m)
                if v < peak * low:
                    found.append(f"trade-off row '{row[0][:60]}': trigger {m.group(0)} is already below "
                                 f"today's estimated peak ({peak:,.0f}/s) - it has fired")
                elif v > peak * high:
                    found.append(f"trade-off row '{row[0][:60]}': trigger {m.group(0)} is more than {high:g}x "
                                 f"today's estimated peak ({peak:,.0f}/s) - a strawman unless the evolution "
                                 f"section projects that load")
    return found


def check(text, kind, draft=False, calc=None):
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
        if not any(observable(x) for x in triggers + prose):
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
    else:
        body = "\n".join(b for _, b in est)
        if not re.search(r"\b(given|assumed)\b", body, re.I):
            problems.append("estimation does not label its inputs as given or assumed")
        if not re.search(r"capacity_calc|\.calc\.json", body):
            problems.append("estimation does not cite the calculator run (capacity_calc.py command "
                            "or the .calc.json it saved)")
    if not find(secs, "failure"):
        problems.append("missing section: failure modes / cascades / disaster recovery")
    if not find(secs, "evolution"):
        problems.append("missing section: evolution (10x / 100x, migration)")
    review = find(secs, "review")
    if not draft and not review:
        problems.append("missing section: review log (reviewer and agy findings, accepted or "
                        "rejected); pass --draft to check a doc before review")
    elif not draft and not re.search(r"\b(accepted|rejected|no findings|self-review)\b",
                                     "\n".join(b for _, b in review), re.I):
        problems.append("review log records no dispositions (say which findings were accepted or "
                        "rejected, or 'no findings')")

    if not found_tables:
        problems.append("no trade-off table with a 'Change it when' column")
    else:
        rows = [(row, col) for t, col in found_tables for row in t[1:]]
        if len(rows) < 3:
            problems.append(f"trade-off table has {len(rows)} row(s); need at least 3 decisions")
        for t, _ in found_tables:
            header = [c.lower() for c in t[0]]
            for label in ("solves", "worsens"):
                idx = next((i for i, c in enumerate(header) if label in c), None)
                if idx is None:
                    continue
                for row in t[1:]:
                    val = row[idx].strip() if idx < len(row) else ""
                    if re.fullmatch(r"(-+|—|n/?a|none|nothing|tbd)?", val, re.I):
                        problems.append(f"trade-off row '{row[0][:60]}': '{label}' is empty - every "
                                        "decision costs something and buys something")
        for row, col in rows:
            name = row[0][:60] if row else "?"
            cell = row[col] if col < len(row) else ""
            if not observable(cell):
                problems.append(f"trade-off row '{name}': trigger is not observable "
                                f"(needs a number and a comparison): '{cell[:80]}'")
        notes.append(f"{len(rows)} trade-off row(s) checked")
        if calc:
            problems.extend(strawman_triggers(rows, calc))

    for para in paragraphs(text):
        if re.search(r"\beventual(ly)?\s+consisten", para, re.I) and not TIME_NUMBER.search(para):
            problems.append("'eventual consistency' without a staleness window (a time number in the "
                            f"same paragraph): '{para.strip()[:80]}'")

    fail = find(secs, "failure")
    if fail:
        body = "\n".join(b for _, b in fail)
        fail_tables = list(tables(body))
        for term in ("RPO", "RTO"):
            inline = (re.search(rf"\b{term}\b[^\n]{{0,40}}?(\d|\bzero\b|near[- ]zero)", body, re.I)
                      or re.search(rf"(\d[\d.,]*\s*-?\s*(?:ms|s|sec|seconds?|min|minutes?|h|hours?|days?)"
                                   rf"|\bzero\b)[^\n]{{0,20}}?\b{term}\b", body, re.I))
            in_table = False
            for t in fail_tables:
                idx = next((i for i, c in enumerate(t[0]) if re.search(rf"\b{term}\b", c, re.I)), None)
                if idx is not None and any(idx < len(row) and re.search(r"\d|\bzero\b", row[idx], re.I)
                                           for row in t[1:]):
                    in_table = True
            if not (inline or in_table):
                problems.append(f"failure section has no numeric {term} (e.g. '{term} 5 min')")
    return problems, notes


def main(argv=None):
    p = argparse.ArgumentParser(description="Structural gate for a design doc or ADR.")
    p.add_argument("file")
    p.add_argument("--kind", choices=["design", "adr"], default="design")
    p.add_argument("--json", action="store_true")
    p.add_argument("--draft", action="store_true", help="the doc has not been reviewed yet; skip the review-log check")
    p.add_argument("--calc", help="capacity_calc.py JSON output; flags trade-off rate triggers that are "
                                  "already exceeded or far above the estimated peak")
    a = p.parse_args(argv)
    try:
        with open(a.file, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        print(f"check_design: cannot read {a.file}: {e}", file=sys.stderr)
        return 2
    calc = None
    if a.calc:
        try:
            with open(a.calc, encoding="utf-8") as fh:
                calc = json.load(fh)
        except (OSError, ValueError) as e:
            print(f"check_design: cannot read --calc {a.calc}: {e}", file=sys.stderr)
            return 2
    problems, notes = check(text, a.kind, draft=a.draft, calc=calc)
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
