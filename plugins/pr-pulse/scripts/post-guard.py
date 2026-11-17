#!/usr/bin/env python3
"""PreToolUse guard (Bash): in a session that holds a pr-pulse job, outward posting to GitHub is
blocked unless that job has a draft the user added their lines to (status 'ready').

Backs up the "top lines first" rule with something harder than an instruction: workers have
gh pr comment / gh pr review pre-approved, so without this only the prompt would stop them.
Sessions without a pr-pulse job are never touched. Any internal error allows (never breaks a
session), but logs it.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# No hand-over here: this runs before every Bash call, so it stays one short process. It only
# records which pr-pulse folder the session loaded (note_loaded).

POSTING = [
    re.compile(r"\bgh\s+pr\s+(comment|review)\b"),
    re.compile(r"\bgh\s+issue\s+comment\b"),
    # gh api with a write method, or with fields (gh api turns -f/-F/--field/--raw-field into POST)
    re.compile(r"\bgh\s+api\b(?=.*(?:-X|--method)\s*(?:POST|PATCH|PUT))", re.I),
    re.compile(r"\bgh\s+api\b(?!\s+graphql)(?=.*\s(?:-f|-F|--field|--raw-field|--input)\b)"),
]
GRAPHQL_MUTATION = re.compile(r"\bgh\s+api\s+graphql\b(?=.*\bmutation\b)", re.S)
# Mutations that carry no text of the user's: allowed without lines.
SILENT_MUTATIONS = re.compile(r"\b(resolveReviewThread|unresolveReviewThread|requestReviews|"
                              r"markPullRequestReadyForReview)\b")
# Carries no text either, but merges: only a merge job may run it (the /pr-merge skill's queue step).
MERGE_MUTATIONS = {"enqueuePullRequest"}


def text_mutations(cmd):
    """The mutations in a gh api graphql call that are not silent; None if it is not one."""
    if not GRAPHQL_MUTATION.search(cmd):
        return None
    names = re.findall(r"\b([a-z][A-Za-z]+)\s*\(", cmd.split("mutation", 1)[1])
    return [n for n in names if not SILENT_MUTATIONS.match(n)] if names else ["?"]


def is_posting(cmd):
    if GRAPHQL_MUTATION.search(cmd):
        names = re.findall(r"\b([a-z][A-Za-z]+)\s*\(", cmd.split("mutation", 1)[1])
        text_mutations = [n for n in names if not SILENT_MUTATIONS.match(n)]
        return bool(text_mutations) or not names
    return any(p.search(cmd) for p in POSTING)


def decide(con, sid, cmd):
    """None = allow; otherwise the reason to block."""
    if not is_posting(cmd):
        return None
    muts = text_mutations(cmd)
    if muts and set(muts) <= MERGE_MUTATIONS:
        merge = con.execute("SELECT 1 FROM jobs WHERE sid=? AND action='merge' AND status IN "
                            "('claimed','delivered')", (sid,)).fetchone()
        if merge:
            return None   # the merge job's own queue step; any other job is checked below
    # A job waiting for the user's Post on proposed lines guards too (those lines are not theirs
    # yet), and so does a stalled job (its worker may still be running). Other waiting_user jobs
    # leave the session free, as before.
    job = con.execute("SELECT id FROM jobs WHERE sid=? AND (status IN ('claimed','delivered') OR "
                      "(status='waiting_user' AND (note LIKE 'top lines proposed%' OR note LIKE 'stalled%'))) "
                      "ORDER BY updated_at DESC", (sid,)).fetchone()
    if not job:
        return None   # not a pr-pulse job session: the guard stays out of the way
    ready = con.execute("SELECT COUNT(*) FROM outbox WHERE job_id=? AND status='ready'",
                        (job["id"],)).fetchone()[0]
    if ready:
        return None
    return (f"pr-pulse: posting is blocked for job {job['id']} until the user adds their top lines. "
            f"Park the text instead: pr-pulse outbox add --job {job['id']} --kind <review|reply|comment> "
            f"<<'EOF' … EOF, then pr-pulse job wait-user {job['id']}.")


def note_loaded(sid):
    """Remember which pr-pulse folder this session loaded (handed over by current.forward), so
    the service can tell the user which sessions need /reload-plugins. Never fails the hook."""
    loaded = str(Path(__file__).resolve().parent.parent)
    if not sid or not loaded:
        return
    import current
    service = (str(current.HOME.resolve() / "app.versions"), str(current.APP.resolve()))
    if loaded == service[1] or loaded.startswith(service[0] + "/"):
        # the copy pr-pulse gives every worker directly (worker_cmd --settings), not a plugin the
        # session loaded: recording it made the 'run /reload-plugins' notice fire for current
        # sessions ("0.8.0 loaded, installed: 0.8.0", 11-13)
        return
    try:
        import time
        import db
        if db.DB_PATH.exists():
            con = db.connect()
            row = con.execute("SELECT root FROM loaded WHERE sid=?", (sid,)).fetchone()
            if row and row["root"] == loaded:
                return   # nothing new: no write on every Bash call
            con.execute(
                "INSERT INTO loaded(sid, root, seen_at) VALUES(?,?,?) ON CONFLICT(sid) DO UPDATE SET "
                "root=excluded.root, seen_at=excluded.seen_at, notified_at=CASE WHEN loaded.root="
                "excluded.root THEN loaded.notified_at END", (sid, loaded, time.time()))
    except Exception:   # noqa: BLE001
        pass


def main():
    try:
        ev = json.load(sys.stdin)
    except ValueError:
        return 0
    if ev.get("tool_name") != "Bash":
        return 0
    cmd = (ev.get("tool_input") or {}).get("command") or ""
    sid = ev.get("session_id") or ""
    note_loaded(sid)
    if "gh" not in cmd or not sid:
        return 0
    try:
        import db
        if not db.DB_PATH.exists():
            return 0
        reason = decide(db.connect(), sid, cmd)
    except Exception as e:  # never break a session over the guard itself
        print(f"pr-pulse post-guard error (allowed): {e!r}", file=sys.stderr)
        return 0
    if reason:
        print(json.dumps({"hookSpecificOutput": {"hookEventName": "PreToolUse",
                                                 "permissionDecision": "deny",
                                                 "permissionDecisionReason": reason}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
