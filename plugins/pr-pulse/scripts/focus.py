"""Session focus: a PR session that handles the PRs of one (or a few) development sessions.

    /pr-pulse:join --for contracts        in pr-contracts: only PRs the `contracts` session opened
    /pr-pulse:join                         a general PR session: everything not tied to a pair

Where a PR came from is recorded by the PostToolUse hook for every `gh pr create` (pr_origin:
the opening session's id; the first writer wins). Routing (dispatch.pick_session):

- an own PR whose origin session has a focused PR session goes ONLY there: if that session is
  busy the job waits; if it is gone or has no inbox watcher the job is held and the user is
  told once per outage (re-join it, or drop the pair with `pr-pulse focus clear <name>`);
- an own PR with no pair or no known origin, and every review of someone else's PR, goes to a
  general (unfocused) joined session, else to a background worker as before;
- a focused session never takes anything outside its focus.
Auto-review on/off is checked before any of this, so it still holds reviews whoever would take them.
"""
import json
import time

HOLD = "hold"   # pick_session's answer for "wait for the paired session; don't spawn a worker"


def origin_sid(con, pr_url):
    r = con.execute("SELECT sid FROM pr_origin WHERE url=?", (pr_url,)).fetchone()
    return r["sid"] if r else None


def origin_name(con, pr_url):
    sid = origin_sid(con, pr_url)
    if not sid:
        return None
    r = con.execute("SELECT name FROM sessions WHERE sid=?", (sid,)).fetchone()
    return (r["name"] if r and r["name"] else None) or sid[:8]


def record_origin(con, pr_url, sid, now=None):
    """First writer wins: a later `gh pr ready` or a re-run never moves a PR to another session."""
    if not pr_url or not sid:
        return False
    return con.execute("INSERT OR IGNORE INTO pr_origin(url, sid, at) VALUES(?,?,?)",
                       (pr_url, sid, now or time.time())).rowcount == 1


def focus_of(row):
    try:
        f = json.loads(row["focus"] or "[]")
    except (ValueError, TypeError, IndexError, KeyError):
        return []
    return [str(x) for x in f if str(x).strip()]


def pairs_for(con, slug, pr_url):
    """Registered sessions in this repo focused on the PR's origin session (gone ones included)."""
    name = origin_name(con, pr_url)
    sid = origin_sid(con, pr_url)
    if not name and not sid:
        return []
    out = []
    for r in con.execute("SELECT * FROM sessions WHERE slug=? AND registered=1 AND focus IS NOT NULL",
                         (slug,)).fetchall():
        f = focus_of(r)
        if (name and name in f) or (sid and sid in f):
            out.append(r)
    return out


def is_general(row):
    return not focus_of(row)
