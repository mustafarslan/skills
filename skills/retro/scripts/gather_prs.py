#!/usr/bin/env python3
"""Collect the team's merged PRs and CI failures in the window, pre-digested for /retro.

  gather_prs.py --since 2026-10-06 --out prs.jsonl [--ci-out ci.json] [--repo OWNER/NAME (default: config repo)]

Per PR it keeps only what a retro needs to judge whether the PR drifted from what it first
set out to do. Drift has many shapes and no fixed wording, so it keeps several independent signals:
how much of the description was rewritten between the first and final version (added/removed
lines), title renames, force-pushes, the commit headlines and how many landed after the first
review (rework), and revert-like commits. It also keeps review thread openers and review states. Whole bodies stay out, so ~250 PRs fit in one analyst's
context. --ci-out counts failed workflow runs per workflow and branch.
"""
from __future__ import annotations

import argparse
import difflib
import json
import re
import subprocess
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402

QUERY = '''
query($q: String!, $after: String) {
  search(query: $q, type: ISSUE, first: 20, after: $after) {
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title url mergedAt baseRefName
      author { login __typename }
      labels(first: 10) { nodes { name } }
      body
      userContentEdits(first: 30) { totalCount nodes { editedAt diff } }
      commits(first: 100) { totalCount nodes { commit { messageHeadline authoredDate } } }
      timelineItems(first: 50, itemTypes: [RENAMED_TITLE_EVENT, HEAD_REF_FORCE_PUSHED_EVENT]) {
        nodes { __typename ... on RenamedTitleEvent { previousTitle currentTitle } }
      }
      reviews(first: 30) { nodes { state submittedAt author { login __typename } } }
      reviewThreads(first: 60) { totalCount nodes {
        isResolved path
        comments(first: 30) { totalCount nodes { body author { login __typename } } }
      } }
    } }
  }
}'''
MAX_LINES = 40
REWORK = re.compile(r'^(revert\b|undo\b|back out\b)|\b(roll(ed)? ?back|rework(ed)?|redo|instead of)\b', re.I)
MAX_COMMENT = 400
CI_LIMIT = 3000


def gh(*args: str) -> str:
    return subprocess.run(['gh', *args], capture_output=True, text=True, check=True).stdout


def is_bot(author: dict | None) -> bool:
    return not author or author.get('__typename') == 'Bot' or author.get('login', '').endswith('[bot]')


def body_drift(first: str, final: str) -> dict:
    a = [l.strip() for l in (first or '').splitlines() if l.strip()]
    b = [l.strip() for l in (final or '').splitlines() if l.strip()]
    added, removed = [], []
    for line in difflib.unified_diff(a, b, lineterm='', n=0):
        if line.startswith('+') and not line.startswith('+++'):
            added.append(line[1:][:300])
        elif line.startswith('-') and not line.startswith('---'):
            removed.append(line[1:][:300])
    return {'added': added[:MAX_LINES], 'removed': removed[:MAX_LINES],
            'added_total': len(added), 'removed_total': len(removed)}


def digest(pr: dict) -> dict:
    edits = sorted(pr['userContentEdits']['nodes'], key=lambda e: e['editedAt'])
    first_body = edits[0]['diff'] if edits else pr['body']
    threads = []
    for t in pr['reviewThreads']['nodes']:
        comments = t['comments']['nodes']
        if not comments:
            continue
        opener = comments[0]
        threads.append({'path': t['path'], 'resolved': t['isResolved'], 'bot': is_bot(opener['author']),
                        'replies': t['comments']['totalCount'] - 1,
                        'opener': ' '.join(opener['body'].split())[:MAX_COMMENT]})
    reviewed = sorted(r['submittedAt'] for r in pr['reviews']['nodes'] if r.get('submittedAt'))
    commits = [c['commit'] for c in pr['commits']['nodes']]
    # Author date, not committer date: a rebase rewrites the committer date of every commit.
    after_review = [c for c in commits if reviewed and c['authoredDate'] > reviewed[0]]
    timeline = pr['timelineItems']['nodes']
    drift = {
        'body': body_drift(first_body, pr['body']),
        'title_renames': [f'{t["previousTitle"]} -> {t["currentTitle"]}'
                          for t in timeline if t['__typename'] == 'RenamedTitleEvent'],
        'force_pushes': sum(1 for t in timeline if t['__typename'] == 'HeadRefForcePushedEvent'),
        'commits': pr['commits']['totalCount'],
        'commits_after_first_review': len(after_review),
        'rework_commits': [c['messageHeadline'][:120] for c in commits if REWORK.search(c['messageHeadline'])][:15],
        'commit_headlines_after_review': [c['messageHeadline'][:120] for c in after_review][:20],
    }
    return {'number': pr['number'], 'title': pr['title'], 'url': pr['url'], 'merged_at': pr['mergedAt'],
            'base': pr['baseRefName'], 'bot_author': is_bot(pr['author']),
            'labels': [l['name'] for l in pr['labels']['nodes']],
            'body_edits': pr['userContentEdits']['totalCount'], 'drift': drift,
            'reviews': dict(Counter(r['state'] for r in pr['reviews']['nodes'])),
            'threads_total': pr['reviewThreads']['totalCount'], 'threads': threads}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--since', required=True)
    ap.add_argument('--out', required=True)
    ap.add_argument('--ci-out')
    ap.add_argument('--repo', help='OWNER/NAME; defaults to the config repo')
    args = ap.parse_args()
    cfg = config.require()
    repo = args.repo or cfg['repo']

    q = f'repo:{repo} is:pr is:merged merged:>={args.since}'
    after, count = None, 0
    with open(args.out, 'w') as out:
        while True:
            call = ['api', 'graphql', '-f', f'query={QUERY}', '-F', f'q={q}']
            if after:
                call += ['-F', f'after={after}']
            page = json.loads(gh(*call))['data']['search']
            for pr in page['nodes']:
                if pr:
                    out.write(json.dumps(digest(pr), ensure_ascii=False) + '\n')
                    count += 1
            if not page['pageInfo']['hasNextPage']:
                break
            after = page['pageInfo']['endCursor']
    print(f'{count} merged PRs since {args.since} -> {args.out}', file=sys.stderr)

    if args.ci_out:
        runs = json.loads(gh('run', 'list', '--repo', repo, '--status', 'failure', '--limit', str(CI_LIMIT),
                             '--created', f'>={args.since}', '--json', 'workflowName,headBranch,event,createdAt'))
        by_workflow = Counter(r['workflowName'] for r in runs)
        # `on_main` = failures on the base branch (config base_branch), whatever it is called.
        on_main = Counter(r['workflowName'] for r in runs if r['headBranch'] == cfg['base_branch'])
        with open(args.ci_out, 'w') as fh:
            # gh stops at 1000 runs whatever --limit says, newest first: if the oldest run returned is
            # still inside the window, older failures are missing.
            oldest = min((r['createdAt'] for r in runs), default=None)
            json.dump({'failed_runs': len(runs), 'oldest_run': oldest,
                       'truncated': bool(oldest) and len(runs) >= 1000 and oldest[:10] > args.since, 'by_workflow': by_workflow.most_common(),
                       'on_main': on_main.most_common()}, fh, indent=2)
        print(f'{len(runs)} failed CI runs -> {args.ci_out}', file=sys.stderr)
    return 0


if __name__ == '__main__':
    sys.exit(main())
