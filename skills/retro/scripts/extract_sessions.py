#!/usr/bin/env python3
"""Pull the user's own typed turns out of Claude Code transcripts, for /retro.

  extract_sessions.py --days 14 --out turns.jsonl [--sessions-out sessions.jsonl]
  extract_sessions.py --since 2026-10-06 --out turns.jsonl
  extract_sessions.py --days 14 --count PATTERN [PATTERN...]   # efficacy re-count, no output files
  extract_sessions.py --days 14 --count-agents PATTERN [PATTERN...]   # same, over subagent dispatches

Only sessions whose working directory is a checkout of the configured repo (config.py) count,
judged by its git remote, else by a path segment exactly the config's `repo_folder`, so sibling
repos (-infra/-docs) and scratchpad sessions drop out. Sessions that ran /retro itself are
skipped. One row per user-typed turn:
  {session, cwd, branch, ts, text, prev_action: {tool, target}, prev_text}
`prev_action` is the last tool call the agent made before the user spoke, which is what
ties a correction to the skill step or file it was about.
--agent-calls-out writes one row per subagent dispatch (Agent/Task tool):
  {session, ts, subagent_type, description, prompt_head, prompt_chars}
so a retro can see briefs retyped to general-purpose agents (a new-subagent candidate).
--projects-root overrides ~/.claude/projects, for tests.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from state import is_main_repo, repo_folder_match  # noqa: E402

DROP_PREFIXES = ('<task-notification>', '<local-command-stdout>', '<local-command-caveat>',
                 '<local-command-stderr>', 'Caveat:', '<bash-stdout>', '<bash-stderr>',
                 '<bash-input>', 'Another Claude session sent a message', '<agent-message',
                 'This session is being continued from a previous conversation',
                 '<artifact-content-authored-by-others', 'The summarized conversation included')
STRIP_BLOCKS = [
    (re.compile(r'<system-reminder>.*?</system-reminder>', re.S), ''),
    (re.compile(r'<pasted_content[^>]*>.*?</pasted_content[^>]*>', re.S), '[pasted]'),
]
COMMAND = re.compile(r'<command-name>/?([^<]+)</command-name>')
COMMAND_ARGS = re.compile(r'<command-args>(.*?)</command-args>', re.S)
MAX_TEXT = 2000
WANTED = re.compile(r'"type":\s*"(user|assistant|pr-link)"')


_REPO_CACHE: dict = {}


def main_repo_cwd(cwd: str) -> bool:
    """True when cwd is a checkout of the configured repo, whatever the folder is called.

    A live checkout is judged by its git remote, like the reminder hook. A cwd that no longer
    exists (a removed worktree) falls back to a path segment exactly the config's `repo_folder`."""
    if not cwd:
        return False
    if cwd not in _REPO_CACHE:
        _REPO_CACHE[cwd] = is_main_repo(cwd) if Path(cwd).is_dir() else repo_folder_match(cwd)
    return _REPO_CACHE[cwd]


def first_cwd(path: Path, max_lines: int = 400) -> str:
    with path.open(encoding='utf-8', errors='replace') as fh:
        for i, line in enumerate(fh):
            if i >= max_lines:
                break
            if '"cwd"' in line:
                try:
                    cwd = json.loads(line).get('cwd')
                except ValueError as _:
                    continue
                if cwd:
                    return cwd
    return ''


def clean_user_text(content) -> str | None:
    if isinstance(content, list):
        if any(isinstance(c, dict) and c.get('type') == 'tool_result' for c in content):
            return None
        content = '\n'.join(c.get('text', '') for c in content
                            if isinstance(c, dict) and c.get('type') == 'text')
    if not isinstance(content, str):
        return None
    text = content.strip()
    if text.startswith(DROP_PREFIXES):
        return None
    command = COMMAND.search(text)
    if command:
        args = COMMAND_ARGS.search(text)
        return f'/{command.group(1).strip()} {(args.group(1).strip() if args else "")}'.strip()
    for pattern, repl in STRIP_BLOCKS:
        text = pattern.sub(repl, text)
    text = text.strip()
    if text.startswith('[Request interrupted by user'):
        return '[interrupted]'
    return text[:MAX_TEXT] or None


def tool_target(name: str, inp: dict) -> str:
    for key in ('file_path', 'path', 'notebook_path', 'skill', 'url', 'pattern'):
        if inp.get(key):
            return str(inp[key])[:200]
    if inp.get('command'):
        return ' '.join(str(inp['command']).split())[:160]
    if inp.get('subagent_type') or inp.get('description'):
        return f'{inp.get("subagent_type", "")}: {inp.get("description", "")}'[:160]
    if inp.get('questions'):
        return 'AskUserQuestion'
    return ''


def scan_file(path: Path, since: dt.datetime, sink, sessions: list, agent_sink=None) -> int:
    agent_calls = []
    rows, meta = [], {'cwd': None, 'branch': None, 'pr_links': set(), 'ran_retro': False}
    prev_action, prev_text = None, None
    with path.open(encoding='utf-8', errors='replace') as fh:
        for line in fh:
            # Cheap filter first: most lines are tool output, API bookkeeping or attachments.
            if not WANTED.search(line):
                continue
            try:
                rec = json.loads(line)
            except ValueError as _:
                continue
            kind = rec.get('type')
            if kind == 'pr-link':
                meta['pr_links'].add(rec.get('prNumber'))
                continue
            if rec.get('isSidechain'):
                continue
            meta['cwd'] = meta['cwd'] or rec.get('cwd')
            meta['branch'] = rec.get('gitBranch') or meta['branch']
            content = (rec.get('message') or {}).get('content')
            if kind == 'assistant':
                for block in content if isinstance(content, list) else []:
                    if block.get('type') == 'tool_use' and block.get('name') in ('Agent', 'Task'):
                        inp = block.get('input') or {}
                        ts = rec.get('timestamp', '')
                        if not ts or dt.datetime.fromisoformat(ts.replace('Z', '+00:00')) >= since:
                            agent_calls.append({
                                'session': rec.get('sessionId'), 'ts': ts,
                                'subagent_type': inp.get('subagent_type') or 'general-purpose',
                                'description': inp.get('description', ''),
                                'prompt_head': ' '.join(str(inp.get('prompt', '')).split())[:400],
                                'prompt_chars': len(str(inp.get('prompt', '')))})
                    if block.get('type') == 'tool_use':
                        prev_action = {'tool': block.get('name'),
                                       'target': tool_target(block.get('name', ''), block.get('input') or {})}
                    elif block.get('type') == 'text' and block.get('text', '').strip():
                        prev_text = ' '.join(block['text'].split())[:300]
                continue
            if rec.get('isMeta'):
                continue
            text = clean_user_text(content)
            if text is None:
                continue
            if re.match(r'/(?:[\w-]+:)?retro\b', text):  # /retro, or /skills:retro from the plugin
                meta['ran_retro'] = True
            ts = rec.get('timestamp', '')
            if ts and dt.datetime.fromisoformat(ts.replace('Z', '+00:00')) < since:
                continue
            rows.append({'session': rec.get('sessionId'), 'cwd': rec.get('cwd'),
                         'branch': rec.get('gitBranch'), 'ts': ts, 'text': text,
                         'prev_action': prev_action, 'prev_text': prev_text})
    if not main_repo_cwd(meta['cwd'] or '') or meta['ran_retro'] or not rows:
        return 0
    for row in rows:
        sink(row)
    for call in agent_calls if agent_sink else []:
        agent_sink(call)
    sessions.append({'session': rows[0]['session'], 'cwd': meta['cwd'], 'branch': meta['branch'],
                     'first_ts': rows[0]['ts'], 'last_ts': rows[-1]['ts'], 'turns': len(rows),
                     'pr_links': sorted(p for p in meta['pr_links'] if p)})
    return len(rows)


def main_repo_files(projects_root: str, since: dt.datetime) -> list:
    """Transcripts touched since `since` whose session ran in a main-repo checkout.

    Folder names prove nothing (a clone can be called anything), so each transcript's first
    recorded cwd is checked against the git remote; scratchpad sessions are skipped."""
    if not Path(projects_root).is_dir():
        return []  # Fresh install: no transcripts yet.
    return [f for d in Path(projects_root).iterdir()
            if d.is_dir() and not d.name.startswith('-private-')
            for f in d.glob('*.jsonl')
            if f.stat().st_mtime >= since.timestamp() and main_repo_cwd(first_cwd(f))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    window = ap.add_mutually_exclusive_group()
    window.add_argument('--days', type=int, default=14)
    window.add_argument('--since', help='YYYY-MM-DD')
    ap.add_argument('--out')
    ap.add_argument('--sessions-out')
    ap.add_argument('--agent-calls-out')
    ap.add_argument('--count', nargs='+', metavar='REGEX',
                    help='print how many turns (and sessions) match each case-insensitive regex')
    ap.add_argument('--count-agents', nargs='+', metavar='REGEX',
                    help='print how many subagent dispatches match each regex (over type, description, prompt)')
    ap.add_argument('--projects-root', default=str(Path.home() / '.claude' / 'projects'))
    args = ap.parse_args()
    if not args.out and not args.count and not args.count_agents:
        ap.error('give --out, --count or --count-agents')
    config.require()

    since_date = dt.date.fromisoformat(args.since) if args.since else dt.date.today() - dt.timedelta(days=args.days)
    since = dt.datetime.combine(since_date, dt.time(), tzinfo=dt.timezone.utc)
    files = main_repo_files(args.projects_root, since)

    started, collected, sessions = time.time(), [], []
    out = open(args.out, 'w') if args.out else None

    def sink(row: dict) -> None:
        if out:
            out.write(json.dumps(row, ensure_ascii=False) + '\n')
        if args.count:
            collected.append(row)
    agent_out = open(args.agent_calls_out, 'w') if args.agent_calls_out else None
    agent_calls: list = []

    def agent_sink(call: dict) -> None:
        if agent_out:
            agent_out.write(json.dumps(call, ensure_ascii=False) + '\n')
        if args.count_agents:
            agent_calls.append(call)

    want_agents = bool(agent_out or args.count_agents)
    total = sum(scan_file(f, since, sink, sessions, agent_sink if want_agents else None) for f in files)
    if agent_out:
        agent_out.close()
    if out:
        out.close()
    if args.sessions_out:
        Path(args.sessions_out).write_text(''.join(json.dumps(s) + '\n' for s in sessions))
    if args.count:
        for pattern in args.count:
            rx = re.compile(pattern, re.I)
            hits = [r for r in collected if rx.search(r['text'])]
            print(json.dumps({'pattern': pattern, 'turns': len(hits),
                              'sessions': len({r['session'] for r in hits})}))
    for pattern in args.count_agents or []:
        rx = re.compile(pattern, re.I)
        hits = [c for c in agent_calls
                if rx.search(f'{c["subagent_type"]} {c["description"]} {c["prompt_head"]}')]
        print(json.dumps({'agent_pattern': pattern, 'dispatches': len(hits),
                          'sessions': len({c['session'] for c in hits})}))
    print(f'since {since_date}: {len(files)} transcripts scanned, {len(sessions)} main-repo sessions, '
          f'{total} user turns, {time.time() - started:.1f}s', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
