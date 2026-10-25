#!/usr/bin/env python3
"""Pick the retro window as N *active* days back from today, skipping days with no activity.

  window.py --days 14 [--repo OWNER/NAME (default: config repo)] [--projects-root DIR]

A day is active when it has at least one session turn by the user in a checkout of the configured
repo (config.py), or a PR opened or merged in that repo (anyone's). Quiet days (weekends, holidays) do not use up the count, so
--days 14 after an idle weekend reaches two days further back. Prints JSON:
  {"since": "YYYY-MM-DD", "today": …, "active_days": N, "calendar_days": M, "skipped": [dates]}
The issue tracker is not consulted (no CLI); sessions and PRs already mark every working day.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import config  # noqa: E402
from extract_sessions import main_repo_files, scan_file  # noqa: E402

LOOKBACK_FACTOR = 4  # Look this many times further back than N, so long holidays still fit.


def local_date(ts: str) -> dt.date:
    return dt.datetime.fromisoformat(ts.replace('Z', '+00:00')).astimezone().date()


def pick_since(active: set, today: dt.date, n: int, horizon: dt.date) -> dict:
    """Walk back from today; stop at the day that makes n active days."""
    day, count, skipped = today, 0, []
    while day >= horizon:
        if day in active:
            count += 1
            if count == n:
                break
        else:
            skipped.append(day.isoformat())
        day -= dt.timedelta(days=1)
    day = max(day, horizon)
    return {'since': day.isoformat(), 'today': today.isoformat(), 'active_days': count,
            'calendar_days': (today - day).days + 1, 'skipped': skipped}


def session_days(projects_root: str, horizon: dt.date) -> set:
    since = dt.datetime.combine(horizon, dt.time(), tzinfo=dt.timezone.utc)
    rows: list = []
    for f in main_repo_files(projects_root, since):
        scan_file(f, since, rows.append, [])
    return {local_date(r['ts']) for r in rows if r.get('ts')}


def pr_days(repo: str, horizon: dt.date) -> set:
    out = subprocess.run(['gh', 'pr', 'list', '--repo', repo, '--state', 'all', '--limit', '3000',
                          '--search', f'updated:>={horizon.isoformat()}', '--json', 'createdAt,mergedAt'],
                         capture_output=True, text=True, check=True).stdout
    days = set()
    for pr in json.loads(out):
        for key in ('createdAt', 'mergedAt'):
            if pr.get(key):
                days.add(local_date(pr[key]))
    return days


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--days', type=int, required=True)
    ap.add_argument('--repo', help='OWNER/NAME; defaults to the config repo')
    ap.add_argument('--projects-root', default=str(Path.home() / '.claude' / 'projects'))
    args = ap.parse_args()
    cfg = config.require()
    today = dt.date.today()
    horizon = today - dt.timedelta(days=args.days * LOOKBACK_FACTOR)
    active = session_days(args.projects_root, horizon) | pr_days(args.repo or cfg['repo'], horizon)
    print(json.dumps(pick_since(active, today, args.days, horizon)))
    return 0


if __name__ == '__main__':
    sys.exit(main())
