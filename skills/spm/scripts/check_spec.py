#!/usr/bin/env python3
"""spm leak and consistency checker.

Two modes:
  check_spec.py <pack-dir> [--repo <git-root>] [--json]
      Check a whole spm pack (intent.md, world.md, scenarios.md). Exit 0 clean, 1 findings, 2 error.
  check_spec.py --approve <pack-dir>
      Final gate before engineering promotes the pack. Exit 0 ready, 1 not ready.
  check_spec.py --pack-hash <pack-dir>
      Print the hash a red-team report must carry in its header.
  check_spec.py --hook
      PreToolUse hook for Write/Edit/MultiEdit. Reads the tool call from stdin. Only files that carry
      the spm marker are checked. Findings -> deny. Any failure on a marked file -> exit 2 (fail closed).

Standard library only, Python 3.9+.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, asdict

MARKER = '<!-- spm:draft'
PACK_FILES = ('intent.md', 'world.md', 'stories.md', 'scenarios.md', 'design-input.md')
REQUIRED_FILES = ('intent.md', 'world.md', 'stories.md', 'scenarios.md')
DESIGN_FILE = 'design-input.md'
EXEMPT_HEADING = re.compile(r'accepted terms', re.I)
SOURCE_GLOBS = [
    '*.py', '*.ts', '*.tsx', '*.js', '*.jsx', '*.mjs', '*.go', '*.java', '*.kt', '*.rb', '*.rs',
    '*.cs', '*.php', '*.swift', '*.scala', '*.sql', '*.vue', '*.svelte',
]
ALLOWED_FENCES = {'text', 'csv', 'eml', 'email', 'txt', ''}
# Raw example inputs (an email, a CSV) are data, so their fences are not checked, but only in the files
# that hold examples. Anywhere else a fence would hide prose from every check.
DATA_FENCE_FILES = ('scenarios.md', 'world.md')
EXEMPT_FILES = ('world.md',)  # where an "Accepted terms" heading exempts its section

# Shapes that only code has.
SHAPES = [
    ('backticks', re.compile(r'`([^`\n]+)`'),
     'code formatting; quote literal text with "double quotes" instead'),
    ('snake_case', re.compile(r'\b[a-z][a-z0-9]*(?:_[a-z0-9]+)+\b'),
     'identifier-shaped name'),
    ('SCREAMING_CASE', re.compile(r'\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b'),
     'constant/event/error-code-shaped name'),
    ('CamelCase', re.compile(r'\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)+\b'),
     'class-shaped name'),
    ('camelCase', re.compile(r'\b[a-z]+(?:[A-Z][a-z0-9]+)+\b'),
     'variable-shaped name'),
    ('CamelCase', re.compile(r'\b[A-Z]{2,}[a-z]+(?:[A-Z][a-z0-9]*)+\b|\b[A-Z][a-z0-9]+(?:[A-Z][a-z0-9]+)*[A-Z]{2,}\b'),
     'class-shaped name'),
    ('camelCase', re.compile(r'\b[a-z]+(?:[A-Z][a-z0-9]+)*[A-Z]{2,}[a-z0-9]*\b'),
     'variable-shaped name'),
    ('call', re.compile(r'\b\w+(?:\.\w+)+\([^)\n]*\)|\b\w*_\w*\([^)\n]*\)|\b\w+\(\)'
                       r'|\b[A-Za-z_]\w{2,}\((?!e?s\))[^)\s][^)\n]*\)'),  # validate(input), not approver(s)
     'function-call syntax'),
    ('operator', re.compile(r'==|!=|&&|<=|>=|=>'),
     'code operator; state the rule in words ("at most", "strictly above")'),
    ('url-path', re.compile(r'(?<![\w.:/<])/[a-z][a-z0-9_-]*(?:/[a-z0-9_<>{}:-]+)+'),
     'route/URL path'),
    ('url-path', re.compile(r'https?://[^\s)]+/[^\s)]*'),
     'URL with a path'),
    ('http', re.compile(r'\b(?:GET|POST|PUT|PATCH|DELETE)\b|\bHTTP\s*\d{3}\b'),
     'HTTP method/status'),
    ('http', re.compile(r'\b(?:status|returns?|error|response|code)\b[^.\n]{0,20}\b[1-5]\d\d\b', re.I),
     'HTTP-like status code'),
    ('header', re.compile(r'\bX-[A-Z][\w-]+'),
     'custom protocol header'),
]

# Words a finance user would also use (query, queue, method, flag, trigger, config) are left out on
# purpose: they are caught by the red team, not by this list.
TECH_WORDS = [
    'database', 'db', 'sql', 'schema', 'migration', 'migrations', 'endpoint', 'endpoints', 'api',
    'apis', 'graphql', 'json', 'yaml', 'payload', 'webhook', 'cron', 'cron job', 'scheduler',
    'background job', 'cache', 'cached', 'caching', 'redis', 'postgres', 'postgresql', 'hash',
    'hashed', 'hashing', 'sha256', 'sha-256', 'md5', 'hmac', 'base64', 'uuid', 'regex',
    'microservice', 'backend', 'frontend', 'server-side', 'client-side', 'orm', 'foreign key',
    'primary key', 'enum', 'boolean', 'varchar', 'null', 'column', 'columns', 'table', 'tables',
    'router', 'middleware', 'serializer', 'http', 'https', 'library', 'framework', 'pipeline',
    'stored procedure', 'lambda', 'docker', 'kubernetes', 'feature flag', 'token', 'tokens',
]
# "table" is fine in these phrases: they name parts of the spec itself.
TABLE_OK = re.compile(r'\b(?:outcome|examples?|constants|scenario|summary|decision|this)\s+tables?\b', re.I)
TECH_RE = re.compile(r'\b((?:' + '|'.join(re.escape(w) for w in sorted(TECH_WORDS, key=len, reverse=True))
                     + r')(?:e?s)?)\b', re.I)

NUMBER_RE = re.compile(r'(?<![\w.,/-])(\d{1,3}(?:[.,]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)(\s*%)?')
TIME_RE = re.compile(r'\b\d{1,2}:\d{2}\b')
SKIP_NUMBER_CONTEXT = re.compile(
    r'\b[A-Z][A-Z0-9]*-\d+[a-z]?\b'          # scenario / requirement IDs
    r'|\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}\.\d{1,2}\.\d{4}\b'  # dates
    r'|\bv\d+(?:\.\d+)*\b|\bP[0-3]\b'          # versions, priorities
)
SCENARIO_HEAD = re.compile(r'^#{2,4}\s+([A-Z][A-Z0-9]*-\d+[a-z]?)\b')
RECORD_FILES = ('decisions.md',)

# UI and interaction design: allowed only in design-input.md, where every item names the UI/UX
# designer as its source.
UI_RE = re.compile(
    r'\b(?:pages?|screens?|links?|buttons?|tabs?|fields?|forms?|pop-?ups?|dialogs?|modals?|menus?|icons?'
    r'|dropdowns?|drop-downs?|checkbox(?:es)?|toggles?|tooltips?|banners?|toasts?|sidebars?|navbars?'
    r'|wizards?|widgets?|dashboards?|landing pages?|text boxe?s?)\b'
    r'|\b(?:click(?:s|ed|ing)?|double-click\w*|tap(?:s|ped|ping)?|drag(?:s|ged|ging)?|scroll(?:s|ed|ing)?'
    r'|hover(?:s|ed|ing)?|swipe[sd]?|swiping|types?\s+(?:in|into)|select(?:s|ed)?\s+(?:from|in)'
    r'|fill(?:s|ed)?\s+(?:in|out)|navigat(?:e|es|ed|ing)\s+to|tick(?:s|ed)?\s+the)\b', re.I)
UI_COPY_RE = re.compile(r'["“]([^"”\n]+)["”]')
CHANNEL_RE = re.compile(r'\b(e-?mails?|sms|text messages?|whatsapp|mobile|phones?|apps?|portal|slack'
                        r'|pdfs?|excel|spreadsheets?|csv|fax)\b', re.I)
STORY_LINE = re.compile(r'^\s*(?:[-*+]\s+|\d+[.)]\s+)?\*\*(US-\d+)[^*]*\*\*\s*(.*)$')
STORY_SHAPE = re.compile(r'^as an?\s+(.+?),\s*i want\s+(.+?),\s*so that\s+(.+)$', re.I)
STORY_HEAD = re.compile(r'^#{2,4}\s+(US-\d+)\b')
DESIGN_HEAD = re.compile(r'^#{2,4}\s+(D-\d+)\b')
DESIGN_SOURCE = re.compile(r'^\s*source:.*\bui\s*/?\s*ux\b.*designer|^\s*source:.*\b(?:ui|ux) designer', re.I)
REDTEAM_FILES = ('redteam-1.md', 'redteam-2.md')

# Design decisions written in plain words. English only (requirements are written in English).
_UI = r'(?:screen|page|tab|view|menu|app|area|component|module|service|endpoint|table|database|store|storage|job)s?'
MECHANISMS = [
    (re.compile(r'\b(?:its|their)\s+own\s+(?:list|section|workflow|process|' + _UI[3:], re.I),
     'dedicated screen/storage/process is a design choice'),
    (re.compile(r'\b(?:dedicated|separate|standalone)\s+(?:list|section|workflow|process|' + _UI[3:], re.I),
     'dedicated screen/storage/process is a design choice'),
    (re.compile(r'\bnew\s+' + _UI + r'\b', re.I), 'a new screen/module/storage is a design choice'),
    (re.compile(r'\b(?:stored?|storing|persist(?:s|ed|ing)?|saved?|kept|cached|indexed|logged)\s+'
                r'(?:separately|apart|per\b|in\s+(?:a|its|their)\s+own)', re.I),
     'how data is stored is a design choice'),
    (re.compile(r'\b(?:nightly|hourly|daily|weekly|monthly|periodic(?:ally)?|batch|scheduled|background)\s+'
                r'(?:run|job|batch|process|sync|import|export|recalculation|task|update|refresh)(?:es|s)?\b', re.I),
     'scheduled processing is a design choice; state when the person sees the result'),
    (re.compile(r'\brecalculat\w*|\bre-?comput\w*|\bre-?sync\w*|\bsync(?:s|ed|ing|hroni[sz]\w*)?\b'
                r'|\bpoll(?:s|ed|ing)?\b|\bidempoten\w*|\bdeduplicat\w*', re.I),
     'processing mechanism'),
    (re.compile(r'\b(?:system|platform|app|application|software|service|backend|server|engine)\s+'
                r'(?:(?:will|shall|must|should|would|can|may)\s+(?:then\s+|also\s+|automatically\s+)?)?'
                r'(?:stores?|saves?|keeps|creates?|writes?|generates?|computes?|calculates?|runs?|schedules?'
                r'|calls?|checks?|validates?|maps?|parses?|extracts?|records?|marks?|sets?|updates?|sends?)\b', re.I),
     'the system is not an actor; say who observes what'),
]
OBS_VERBS = re.compile(
    r'\b(?:sees?|receives?|can(?:not)?|can\'t|gets?|finds?|may(?:\s+not)?|must(?:\s+not)?'
    r'|(?:is|are)\s+(?:not\s+)?(?:told|shown|asked|notified|able\s+to)'
    r'|(?:does|do)\s+not\s+(?:see|receive|get|find)|never\s+(?:sees?|receives?|gets?))\b', re.I)
BANNED_SUBJECT = re.compile(r'^\s*(?:the\s+)?(?:system|platform|app|application|software|service|backend|'
                            r'server|engine|it|we|they)\b', re.I)
QUANTIFIERS = re.compile(r'\b(?:nobody|no\s+one|anyone|everyone|every\s+user|any\s+user|a\s+user|users?'
                         r'|a\s+person|people)\b', re.I)
REQ_LINE = re.compile(r'^\s*(?:[-*+]\s+|\d+[.)]\s+)?\*\*(AC-\d+(?:\.\d+)?[^*]*|Then)\*\*\s*(.*)$')


@dataclass
class Finding:
    file: str
    line: int
    kind: str
    text: str
    message: str


# ---------- parsing helpers ----------

def norm_term(s: str) -> str:
    return s.strip().strip('`"\'*').strip().lower()


def section_lines(text: str, name: str | None = None):
    """Yield (lineno, line, exempt, in_table, fence_lang) for each line. `name` is the pack file:
    an Accepted terms section exempts only in world.md, and fenced lines count as data (fence_lang
    set) only in DATA_FENCE_FILES; elsewhere they are yielded as ordinary lines."""
    honor_exempt = name is None or name in EXEMPT_FILES
    data_fences = name is None or name in DATA_FENCE_FILES
    exempt = False
    exempt_level = 0
    fence = None
    for i, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith('```'):
            if fence is None:
                fence = stripped[3:].strip().lower()
                yield i, line, exempt, False, '__open__:' + fence
            else:
                fence = None
            continue
        if fence is not None:
            if data_fences:
                yield i, line, exempt, False, fence
            else:
                yield i, line, exempt, stripped.startswith('|'), None
            continue
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            level = len(m.group(1))
            if exempt and level <= exempt_level:
                exempt = False
            if honor_exempt and EXEMPT_HEADING.search(m.group(2)):
                exempt, exempt_level = True, level
        yield i, line, exempt, stripped.startswith('|'), None


def section_text(text: str, heading_re: str) -> str:
    out, on, level = [], False, 0
    for line in text.splitlines():
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            if on and len(m.group(1)) <= level:
                break
            if re.search(heading_re, m.group(2), re.I):
                on, level = True, len(m.group(1))
                continue
        if on:
            out.append(line)
    return '\n'.join(out)


def table_rows(text: str):
    rows = []
    for line in text.splitlines():
        s = line.strip()
        if not s.startswith('|') or re.match(r'^\|[\s:|-]+\|?$', s):
            continue
        rows.append([c.strip() for c in s.strip('|').split('|')])
    return rows[1:] if rows else []  # drop header


def accepted_terms(world: str) -> set[str]:
    sec = section_text(world, r'accepted terms')
    terms = set()
    for line in sec.splitlines():
        s = line.strip()
        if s.startswith(('-', '*')):
            term = re.split(r'\s+[—–-]\s+|:\s', s.lstrip('-* '), maxsplit=1)[0]
            terms.add(norm_term(term))
        elif s.startswith('|'):
            pass
    for row in table_rows(sec):
        if row:
            terms.add(norm_term(row[0]))
    terms.discard('')
    return terms


def parse_numbers(s: str) -> set[float]:
    """Plausible readings of a number written in Turkish (50.000,00) or English (50,000.00) style."""
    s = s.strip()
    try:
        if ',' in s and '.' in s:
            dec = ',' if s.rfind(',') > s.rfind('.') else '.'
            thou = '.' if dec == ',' else ','
            return {round(float(s.replace(thou, '').replace(dec, '.')), 6)}
        sep = ',' if ',' in s else '.' if '.' in s else None
        if sep is None:
            return {float(s)}
        parts = s.split(sep)
        if len(parts) > 2:
            return {float(''.join(parts))}
        if len(parts[1]) == 3:  # 50.000 or 2,500: thousands or decimals
            return {float(''.join(parts)), round(float(parts[0] + '.' + parts[1]), 6)}
        return {round(float(parts[0] + '.' + parts[1]), 6)}
    except ValueError:
        return set()


def constants(world: str):
    """Return ({name: value_text}, [duplicate findings as (name, v1, v2)])."""
    sec = section_text(world, r'^(?:values|constants)\b')
    seen, dups = {}, []
    for row in table_rows(sec):
        if len(row) < 2:
            continue
        name, value = norm_term(row[0]), row[1].strip()
        if name in seen and seen[name] != value:
            dups.append((name, seen[name], value))
        seen.setdefault(name, value)
    return seen, dups


def constant_values(consts: dict[str, str]):
    nums, times = set(), set()
    for v in consts.values():
        times.update(TIME_RE.findall(v))
        for m in NUMBER_RE.finditer(v):
            nums |= parse_numbers(m.group(1))
    return nums, times


def actors(world: str) -> set[str]:
    """Persona IDs, names, first names and roles, tenant names, and outside systems from world.md."""
    out = set()
    for row in table_rows(section_text(world, r'^personas\b')):
        if len(row) > 0 and row[0]:
            out.add(row[0].lower())
        if len(row) > 1 and row[1]:
            out.add(row[1].lower())
            out.add(row[1].split()[0].lower())
        if len(row) > 3 and row[3]:
            out.add(row[3].lower())
    for row in table_rows(section_text(world, r'^tenants\b')):
        if len(row) > 1 and row[1]:
            out.add(row[1].lower())
    for row in table_rows(section_text(world, r'^outside systems\b')):
        if row and row[0]:
            out.add(row[0].lower())
    return {a.strip('`"* ') for a in out if a.strip('`"* ')}


def has_actor(subject: str, known: set[str]) -> bool:
    if QUANTIFIERS.search(subject):
        return True
    low = subject.lower()
    return any(re.search(r'(?<![\w-])' + re.escape(a) + r'(?:s|es)?(?![\w-])', low) for a in known)


# ---------- checks ----------

def actor_findings(name: str, text: str, known: set[str]) -> list[Finding]:
    """Requirement and Then lines must read: <declared actor> <observation verb> <outcome>."""
    out = []
    for lineno, line, exempt, in_table, fence in section_lines(text, name):
        if exempt or in_table or fence is not None:
            continue
        m = REQ_LINE.match(line)
        if not m:
            continue
        label, sentence = m.group(1), m.group(2)
        sentence = re.sub(r'^\(P[0-3]\)\s*', '', sentence.strip())
        if re.match(r'(?:when|if|while|where|after|before|once|as soon as)\b', sentence, re.I) and ',' in sentence:
            sentence = sentence.split(',', 1)[1]
        sentence = re.split(r'(?<!\d)\.(?!\d)|;', sentence, maxsplit=1)[0]
        # a persona may carry a verb-like name ("Can"): skip capitalised matches that are actors
        v = next((x for x in OBS_VERBS.finditer(sentence)
                  if not (x.group(0)[0].isupper() and x.group(0).lower() in known)), None)
        label = label.split()[0]
        if not v:
            out.append(Finding(name, lineno, 'actor', sentence.strip()[:80],
                               f'{label}: no observation verb; write "<who> sees / receives / can / cannot <what>"'))
            continue
        subject = sentence[:v.start()]
        if BANNED_SUBJECT.match(subject):
            out.append(Finding(name, lineno, 'actor', subject.strip(),
                               f'{label}: the system is not an actor; name the person or outside system'))
        elif not has_actor(subject, known):
            out.append(Finding(name, lineno, 'actor', subject.strip() or sentence.strip()[:60],
                               f'{label}: subject is not a persona, role, tenant or outside system '
                               'declared in world.md'))
    return out


UNSETTLED = re.compile(r'^\s*$|\bQ-\d+|\bopen\b|\btbd\b|\btodo\b|\?\s*$', re.I)


def constraint_rows(intent: str):
    """(lineno, term, settled) for each Constraints row; settled = it gives the users' reason."""
    rows, on, level = [], False, 0
    for i, line in enumerate(intent.splitlines(), 1):
        m = re.match(r'^(#{1,6})\s+(.*)$', line)
        if m:
            if on and len(m.group(1)) <= level:
                break
            if re.match(r'constraints\b', m.group(2), re.I):
                on, level = True, len(m.group(1))
            continue
        s = line.strip()
        if not on or not s.startswith('|') or re.match(r'^\|[\s:|-]+\|?$', s):
            continue
        cells = [c.strip() for c in s.strip('|').split('|')]
        if cells and cells[0].lower() != 'constraint':
            why = cells[1] if len(cells) > 1 else ''
            rows.append((i, norm_term(cells[0]), not UNSETTLED.search(why)))
    return rows


def constraint_terms(intent: str) -> set[str]:
    return {t for _, t, settled in constraint_rows(intent) if settled and t}


def constraint_findings(name: str, intent: str) -> list[Finding]:
    return [Finding(name, i, 'constraint', t,
                    'a constraint needs the users\' reason; until the PM gives it, it is a solution choice')
            for i, t, settled in constraint_rows(intent) if not settled]


def ui_findings(name: str, text: str, accepted: set[str]) -> list[Finding]:
    """UI nouns, interaction verbs and exact UI copy belong to the UI/UX designer's input."""
    out = []
    for lineno, line, exempt, _in_table, fence in section_lines(text, name):
        if exempt or fence is not None:
            continue
        for m in UI_RE.finditer(line):
            if norm_term(m.group(0)) not in accepted:
                out.append(Finding(name, lineno, 'ui', m.group(0),
                                   'UI or interaction design; say what the person can do or is told. '
                                   'Design from a UI/UX designer goes in design-input.md with its source'))
        if REQ_LINE.match(line) or STORY_LINE.match(line):
            for m in UI_COPY_RE.finditer(line):
                if len(m.group(1).split()) >= 4:
                    out.append(Finding(name, lineno, 'ui-copy', m.group(1),
                                       'exact on-screen wording is UI design; state the meaning, or record '
                                       'the designer\'s wording in design-input.md'))
    return out


def channel_findings(name: str, text: str, constraints: set[str], accepted: set[str]) -> list[Finding]:
    """A channel (email, mobile, PDF ...) is allowed only as a declared constraint of the users' world."""
    out = []
    allowed = constraints | accepted
    skip_section = False
    for lineno, line, exempt, _in_table, fence in section_lines(text, name):
        h = re.match(r'^#{1,6}\s+(.*)$', line)
        if h:
            skip_section = bool(re.match(r'constraints\b|out of scope\b', h.group(1), re.I))
        if exempt or fence is not None or skip_section:
            continue
        line = re.sub(r'\binputs/\S+', ' ', line)  # input file names are test data, not channels
        for m in CHANNEL_RE.finditer(line):
            w = m.group(1).lower()
            base = re.sub(r'(?:es|s)$', '', w) if w not in ('sms',) else w
            if w in allowed or base in allowed or base.replace('-', '') in allowed:
                continue
            out.append(Finding(name, lineno, 'channel', m.group(1),
                               'a channel is a design choice unless the users\' world requires it; ask the PM, '
                               'and if so record it in intent.md Constraints with the reason'))
    return out


def story_findings(name: str, text: str, known: set[str], full_pack: bool) -> list[Finding]:
    out = []
    blocks: list[tuple[str, int, list[str]]] = []
    for lineno, line, exempt, in_table, fence in section_lines(text, name):
        if fence is not None:
            continue
        head = STORY_HEAD.match(line)
        if head:
            blocks.append((head.group(1), lineno, []))
            continue
        if blocks:
            blocks[-1][2].append(line)
        m = STORY_LINE.match(line)
        if not m:
            continue
        shape = STORY_SHAPE.match(m.group(2).strip())
        if not shape:
            out.append(Finding(name, lineno, 'story', m.group(2).strip()[:80],
                               f'{m.group(1)}: write "As a <persona>, I want <goal>, so that <benefit>"'))
        elif not has_actor(shape.group(1), known):
            out.append(Finding(name, lineno, 'story', shape.group(1),
                               f'{m.group(1)}: the persona is not declared in world.md'))
    if full_pack:
        for sid, lineno, lines in blocks:
            body = '\n'.join(lines)
            if not re.search(r'^\s*\*\*AC-\d+', body, re.M):
                out.append(Finding(name, lineno, 'incomplete', sid, 'story has no acceptance criteria'))
            if not re.search(r'^\s*\*\*Done when', body, re.M | re.I):
                out.append(Finding(name, lineno, 'incomplete', sid, 'story has no "Done when" line'))
    return out


def design_findings(name: str, text: str) -> list[Finding]:
    out, cur = [], None
    for lineno, line in enumerate(text.splitlines(), 1):
        m = DESIGN_HEAD.match(line)
        if m:
            if cur and not cur[2]:
                out.append(Finding(name, cur[1], 'design-source', cur[0],
                                   'design input must say it comes from the UI/UX designer '
                                   '("Source: UI/UX designer, <date>, <material>")'))
            cur = [m.group(1), lineno, False]
        elif cur and DESIGN_SOURCE.search(line):
            cur[2] = True
    if cur and not cur[2]:
        out.append(Finding(name, cur[1], 'design-source', cur[0],
                           'design input must say it comes from the UI/UX designer '
                           '("Source: UI/UX designer, <date>, <material>")'))
    return out


def design_outside_items(text: str) -> str:
    """design-input.md with every line inside a D-nn item blanked (line numbers kept)."""
    out, inside = [], False
    for line in text.splitlines():
        if DESIGN_HEAD.match(line):
            inside = True
        elif re.match(r'^#{1,6}\s', line):
            inside = False
        out.append('' if inside else line)
    return '\n'.join(out)


def mechanism_findings(name: str, text: str, accepted: set[str]) -> list[Finding]:
    out = []
    for lineno, line, exempt, _in_table, fence in section_lines(text, name):
        if exempt or fence is not None:
            continue
        for rx, msg in MECHANISMS:
            for m in rx.finditer(line):
                if norm_term(m.group(0)) not in accepted:
                    out.append(Finding(name, lineno, 'mechanism', m.group(0), msg))
    return out


def leak_findings(name: str, text: str, accepted: set[str]) -> tuple[list[Finding], set[str]]:
    findings, candidates = [], set()
    for lineno, line, exempt, _in_table, fence in section_lines(text, name):
        if exempt or line.strip().startswith(MARKER):
            continue
        if fence is not None:
            if fence.startswith('__open__:') and fence.split(':', 1)[1] not in ALLOWED_FENCES:
                findings.append(Finding(name, lineno, 'code-block', line.strip(),
                                        'code block; describe the behaviour in words'))
            continue
        line_nolinks = re.sub(r'\]\([^)]*\)', ']', line)  # ignore markdown link targets
        for kind, rx, msg in SHAPES:
            for m in rx.finditer(line_nolinks):
                token = m.group(1) if kind == 'backticks' else m.group(0)
                if norm_term(token) in accepted:
                    continue
                findings.append(Finding(name, lineno, kind, token, msg))
                for t in re.findall(r'\w+', token):
                    if '_' in t or re.search(r'[a-z][A-Z]', t) or (kind == 'backticks' and len(t) > 2):
                        candidates.add(t)
        for m in TECH_RE.finditer(line_nolinks):
            word = m.group(1)
            if norm_term(word) in accepted:
                continue
            if word.lower() in ('table', 'tables') and any(
                    a <= m.start() and m.end() <= b for a, b in (t.span() for t in TABLE_OK.finditer(line_nolinks))):
                continue
            findings.append(Finding(name, lineno, 'tech-word', word,
                                    'technical vocabulary; say what a person sees or receives'))
    # one finding per (line, token)
    uniq, seen = [], set()
    for f in findings:
        key = (f.line, f.text)
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq, candidates


def number_findings(name: str, text: str, consts: dict[str, str], accepted: set[str]) -> list[Finding]:
    """Numbers in requirement prose must be defined once in world.md's Constants table."""
    nums, times = constant_values(consts)
    out = []
    for lineno, line, exempt, in_table, fence in section_lines(text, name):
        if exempt or in_table or fence is not None or line.lstrip().startswith('#') \
                or line.strip().startswith(MARKER):
            continue
        clean = SKIP_NUMBER_CONTEXT.sub(' ', re.sub(r'\]\([^)]*\)', ']', line))
        for t in TIME_RE.findall(clean):
            if t not in times:
                out.append(Finding(name, lineno, 'constant', t,
                                   'time not in the Values table (world.md); define it once there'))
        clean = TIME_RE.sub(' ', clean)
        for m in NUMBER_RE.finditer(clean):
            raw = m.group(1)
            readings = parse_numbers(raw)
            if not readings or (raw.isdigit() and int(raw) < 10 and not m.group(2)):
                continue
            if readings & nums or norm_term(raw) in accepted:
                continue
            out.append(Finding(name, lineno, 'constant', raw + (m.group(2) or ''),
                               'number not in the Values table (world.md); define it once there '
                               'and refer to it by name'))
    return out


def scenario_findings(text: str) -> list[Finding]:
    out, ids = [], {}
    blocks: list[tuple[str, int, list[str]]] = []
    for i, line in enumerate(text.splitlines(), 1):
        m = SCENARIO_HEAD.match(line)
        if m:
            sid = m.group(1)
            if sid in ids:
                out.append(Finding('scenarios.md', i, 'duplicate-id', sid,
                                   f'scenario ID already used at line {ids[sid]}'))
            ids.setdefault(sid, i)
            blocks.append((sid, i, []))
        elif blocks:
            if re.match(r'^#{1,2}\s', line):
                blocks.append(('', i, []))  # a new top section ends the scenario
            else:
                blocks[-1][2].append(line)
    for sid, i, lines in blocks:
        if not sid:
            continue
        body = '\n'.join(lines)
        for part, rx in (('Given', r'\bGiven\b'), ('When', r'\bWhen\b'), ('Then', r'^\s*(?:[-*+]\s+)?\*\*Then\*\*'),
                         ('Must not', r'\bmust not\b'), ('outcome table', r'^\s*\|')):
            if not re.search(rx, body, re.I | re.M):
                out.append(Finding('scenarios.md', i, 'incomplete', sid, f'scenario has no {part}'))
    return out


def repo_hits(repo: str | None, candidates: set[str], timeout: int = 20) -> set[str]:
    cands = sorted(c for c in candidates if re.fullmatch(r'\w{3,}', c))[:300]
    if not repo or not cands:
        return set()
    cmd = ['git', '-C', repo, 'grep', '-I', '-h', '-o', '-w', '-E', '|'.join(cands), '--'] + SOURCE_GLOBS
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if proc.returncode not in (0, 1):
        raise RuntimeError(f'git grep failed: {proc.stderr.strip()[:200]}')
    return set(proc.stdout.split())


def find_repo(start: str | None, fallback: str | None = None) -> str | None:
    """Git root of `start` (the current directory: the product repo), else of `fallback` (the
    pack's folder). The skill is installed once and used from any project, so Claude may run
    from a folder that is not a repo while the pack sits inside one."""
    for d in (start, fallback):
        if not d or not os.path.isdir(d):
            continue
        proc = subprocess.run(['git', '-C', d, 'rev-parse', '--show-toplevel'],
                              capture_output=True, text=True, timeout=10)
        if proc.returncode == 0:
            return proc.stdout.strip()
    return None


def check_texts(texts: dict[str, str], repo: str | None, full_pack: bool) -> list[Finding]:
    """texts: {'intent.md': ..., 'world.md': ..., ...}; only the given files are checked."""
    world = texts.get('world.md', '')
    accepted = accepted_terms(world)
    consts, dups = constants(world)
    constraints = constraint_terms(texts.get('intent.md', ''))
    known = actors(world)
    findings: list[Finding] = []
    candidates: set[str] = set()
    for name, text in texts.items():
        f, c = leak_findings(name, text, accepted)
        findings += f
        candidates |= c
        if name == DESIGN_FILE:
            findings += design_findings(name, text)
            # UI design is the point of this file, but only inside a D-nn item that names its source.
            # Anything outside the items is unsourced, so it gets the ordinary checks.
            outside = design_outside_items(text)
            findings += mechanism_findings(name, outside, accepted)
            findings += ui_findings(name, outside, accepted)
            continue
        findings += mechanism_findings(name, text, accepted)
        findings += ui_findings(name, text, accepted)
        if name in ('intent.md', 'stories.md', 'scenarios.md'):
            findings += channel_findings(name, text, constraints, accepted)
        if name == 'intent.md':
            findings += constraint_findings(name, text)
        if name in ('stories.md', 'scenarios.md'):
            findings += actor_findings(name, text, known)
        if name == 'stories.md':
            findings += story_findings(name, text, known, full_pack)
        if name in ('intent.md', 'stories.md'):
            findings += number_findings(name, text, consts, accepted)
        if name == 'scenarios.md' and full_pack:
            findings += scenario_findings(text)
    if 'world.md' in texts:
        for n, v1, v2 in dups:
            findings.append(Finding('world.md', 0, 'contradiction', n,
                                    f'constant defined twice with different values: {v1!r} vs {v2!r}'))
    hits = repo_hits(repo, candidates)
    for f in findings:
        if any(t in hits for t in re.findall(r'\w+', f.text)):
            f.message = 'NAMES CODE IN THIS REPO - ' + f.message
    return findings


# ---------- entry points ----------

def run_pack(argv: list[str]) -> int:
    as_json = '--json' in argv
    args = [a for a in argv if a != '--json']
    repo = None
    if '--repo' in args:
        i = args.index('--repo')
        repo = args[i + 1]
        del args[i:i + 2]
    if len(args) != 1 or not os.path.isdir(args[0]):
        print('usage: check_spec.py <pack-dir> [--repo <git-root>] [--json] | --hook', file=sys.stderr)
        return 2
    pack = args[0]
    texts = {}
    for name in PACK_FILES:
        p = os.path.join(pack, name)
        if os.path.exists(p):
            with open(p, encoding='utf-8') as fh:
                texts[name] = fh.read()
    if not texts:
        print(f'no spm pack files ({", ".join(PACK_FILES)}) in {pack}', file=sys.stderr)
        return 2
    repo = repo or find_repo(os.getcwd(), pack)
    findings = check_texts(texts, repo, full_pack=True)
    if as_json:
        print(json.dumps([asdict(f) for f in findings], ensure_ascii=False, indent=2))
    else:
        for f in findings:
            print(f'{f.file}:{f.line} [{f.kind}] {f.text} - {f.message}')
        print(f'{len(findings)} finding(s); repo cross-check: {repo or "not in a git repo"}')
    return 1 if findings else 0


def new_content(tool: str, inp: dict) -> tuple[str, str]:
    """Return (old_text, new_text) of the target file after the tool call."""
    path = inp.get('file_path', '')
    old = ''
    if os.path.exists(path):
        with open(path, encoding='utf-8') as fh:
            old = fh.read()
    if tool == 'Write':
        return old, inp.get('content', '')
    edits = inp.get('edits') or [inp]
    new = old
    for e in edits:
        o, n = e.get('old_string', ''), e.get('new_string', '')
        if o not in new:
            return old, new + '\n' + n  # Edit will fail anyway; still check the new text
        new = new.replace(o, n) if e.get('replace_all') else new.replace(o, n, 1)
    return old, new


# A whole file name only: user_stories.md or hello-world.md is someone else's file.
GUARDED = r'(?<![\w.-])(?:(?:intent|world|stories|scenarios|design-input|decisions)\.md|redteam-\d+\.md)'
BASH_REDIRECT = re.compile(r'>>?\s*["\']?[^\s;|&]*?(?:' + GUARDED + r')')
BASH_WRITE_OPS = re.compile(r'\b(?:tee|mv|cp|rm|truncate|dd|install|rsync|ln)\b|\bsed\b[^|;]*\s-i'
                            r'|\bperl\b[^|;]*\s-\w*i|write_text|\.write\(|open\([^)]*,\s*["\']?(?:w|a|x|r\+)')


def bash_gate(cmd: str) -> int:
    """Pack files are written only with Write/Edit, so the write gate always sees them."""
    if BASH_REDIRECT.search(cmd) or (re.search(GUARDED, cmd) and BASH_WRITE_OPS.search(cmd)):
        return deny('spm: pack files (intent.md, world.md, scenarios.md, decisions.md, redteam-N.md) '
                    'are written only with the Write or Edit tool, so the leak gate checks them. '
                    'Redo this change with Write/Edit.')
    return 0


def pack_hash(pack: str) -> str:
    import hashlib
    h = hashlib.sha256()
    for name in PACK_FILES:
        p = os.path.join(pack, name)
        if os.path.exists(p):
            with open(p, encoding='utf-8') as fh:
                h.update(name.encode() + b'\0' + fh.read().replace('\r\n', '\n').encode() + b'\0')
    return h.hexdigest()[:16]


def run_approve(pack: str) -> int:
    """Final gate: everything clean, both red-team passes ran on this exact pack, every red-team
    finding has a recorded product decision, and product approval is recorded."""
    problems = []
    texts = {}
    for name in PACK_FILES:
        p = os.path.join(pack, name)
        if not os.path.exists(p):
            if name in REQUIRED_FILES:
                problems.append(f'{name} is missing')
            continue
        with open(p, encoding='utf-8') as fh:
            texts[name] = fh.read()
        if MARKER not in texts[name][:400]:
            problems.append(f'{name} has no spm marker on its first line')
    repo = find_repo(os.getcwd(), pack)
    findings = check_texts(texts, repo, full_pack=True) if texts else []
    if findings:
        problems.append(f'{len(findings)} checker finding(s) remain; run: check_spec.py {pack}')
    current = pack_hash(pack)
    rt_ids = []  # (red-team pack hash, finding ID)
    for name in REDTEAM_FILES:
        p = os.path.join(pack, name)
        if not os.path.exists(p):
            problems.append(f'{name} is missing: run that red team pass')
            continue
        with open(p, encoding='utf-8') as fh:
            rt = fh.read()
        m = re.search(r'spm:redteam pack=([0-9a-f]+)', rt)
        if not m or m.group(1) != current:
            problems.append(f'{name}: the red team reviewed an older version of the pack; run it again')
        rt_ids += [(m.group(1) if m else '', i) for i in re.findall(r'\bRT\d+-\d+\b', rt)]
    decided, approval = set(), False
    dp = os.path.join(pack, 'decisions.md')
    if os.path.exists(dp):
        with open(dp, encoding='utf-8') as fh:
            dec = fh.read()
        # Rows are keyed by (pack hash, finding ID): a fresh red-team round restarts at RT1-01,
        # so a decision from an earlier round must not cover a new finding with the same ID.
        # In the current round only "keep" resolves a finding: "rewrite" or "move" changes the
        # pack, which changes its hash and calls for a new red-team round.
        for row in table_rows(dec):
            if len(row) < 5:
                continue
            h, rid, choice = row[0].strip(), row[1].strip(), row[4].strip().lower()
            if choice == 'keep' or (choice in ('rewrite', 'move') and h != current):
                decided.add((h, rid))
            elif choice in ('rewrite', 'move'):
                problems.append(f'{rid}: decided "{choice}", but the pack has not changed since that '
                                'red-team round; make the change and run the red team again, or record "keep"')
        approval = bool(re.search(r'^approved by\s+\S', section_text(dec, r'^approval\b'), re.I | re.M))
    else:
        problems.append('decisions.md is missing')
    for h, rid in sorted(set(rt_ids)):
        if (h, rid) not in decided:
            problems.append(f'{rid} (pack {h}) has no product decision (rewrite / move / keep) in decisions.md')
    if not approval:
        problems.append('no product approval recorded ("## Approval" / "Approved by ..." in decisions.md)')
    for p in problems:
        print('NOT READY: ' + p)
    if not repo:
        print('WARNING: not inside a git repo; the check for names of real code was skipped. '
              'Run this from inside the repo the pack is for.')
    if problems:
        return 1
    print(f'READY: pack {current} is clean, red-teamed twice, every finding decided, approved by product.')
    return 0


def deny(reason: str) -> int:
    print(json.dumps({'hookSpecificOutput': {
        'hookEventName': 'PreToolUse', 'permissionDecision': 'deny',
        'permissionDecisionReason': reason}}))
    return 0


def marked_sibling(path: str) -> bool:
    """True when another pack file in the same folder carries the spm marker. Unreadable counts
    as marked, so an error here keeps the file checked (fail closed)."""
    folder, me = os.path.dirname(path), os.path.basename(path)
    for name in PACK_FILES:
        p = os.path.join(folder, name)
        if name == me or not os.path.exists(p):
            continue
        try:
            with open(p, encoding='utf-8') as fh:
                if MARKER in fh.read(4000)[:400]:
                    return True
        except Exception:  # noqa: BLE001
            return True
    return False


def run_hook() -> int:
    data = json.load(sys.stdin)
    tool = data.get('tool_name', '')
    inp = data.get('tool_input') or {}
    path = inp.get('file_path', '')
    if tool == 'Bash':
        return bash_gate(inp.get('command') or '')
    if tool not in ('Write', 'Edit', 'MultiEdit') or not path.endswith('.md'):
        return 0
    old, new = new_content(tool, inp)
    if MARKER not in old[:400] and MARKER not in new[:400]:
        if os.path.basename(path) not in PACK_FILES:
            return 0  # not an spm file
        if os.path.exists(path) and not marked_sibling(path):
            # An existing, unmarked intent.md / stories.md / ... with no spm pack next to it belongs to
            # some other project (the hook stays on for the whole session, in any repo). A new file
            # with a pack name is still checked, so leaving the marker off does not skip the gate,
            # and --approve requires the marker on every pack file.
            return 0
    # From here on the file is spm-marked: any failure blocks (fail closed).
    try:
        name = os.path.basename(path)
        texts = {name: new}
        for ctx in ('world.md', 'intent.md'):  # context: personas, values, accepted terms, constraints
            cp = os.path.join(os.path.dirname(path), ctx)
            if ctx != name and os.path.exists(cp):
                with open(cp, encoding='utf-8') as fh:
                    texts[ctx] = fh.read()
        repo = find_repo(data.get('cwd') or os.getcwd(), os.path.dirname(path))
        # the other files are context only; report findings for the edited file
        findings = [f for f in check_texts(texts, repo, full_pack=False) if f.file == name]
    except Exception as e:  # noqa: BLE001 - fail closed on anything
        print(f'spm checker failed on an spm file, write blocked: {e}', file=sys.stderr)
        return 2
    if not findings:
        return 0
    lines = [f'line {f.line} [{f.kind}] {f.text} - {f.message}' for f in findings[:40]]
    more = f'\n... and {len(findings) - 40} more' if len(findings) > 40 else ''
    return deny(
        f'spm leak gate: {len(findings)} finding(s) in {name}.\n' + '\n'.join(lines) + more +
        '\nTake these to the PM with AskUserQuestion (at most 4 per call). For each, offer: rewrite as '
        'behaviour (what a person can do, sees or receives) / move it to ideas-for-engineering.md in the '
        'render folder (ask the PM for that folder if you do not have it; never put it in the pack) if it '
        'is the PM\'s how-idea / keep it as a Constraint with the users\' reason, an Accepted term, or UI/UX '
        'designer input in design-input.md. Never reword only to get past this check.')


def main() -> int:
    if len(sys.argv) == 3 and sys.argv[1] in ('--approve', '--pack-hash'):
        if not os.path.isdir(sys.argv[2]):
            print(f'not a folder: {sys.argv[2]}', file=sys.stderr)
            return 2
        if sys.argv[1] == '--pack-hash':
            print(pack_hash(sys.argv[2]))
            return 0
        return run_approve(sys.argv[2])
    if sys.argv[1:] == ['--hook']:
        try:
            return run_hook()
        except Exception as e:  # noqa: BLE001
            print(f'spm hook could not read the tool call, write blocked: {e}', file=sys.stderr)
            return 2
    return run_pack(sys.argv[1:])


if __name__ == '__main__':
    sys.exit(main())
