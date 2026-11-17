"""Drafts waiting for the user's top lines: the one place their rules live, shared by the CLI,
/pr-pulse:inbox and notifications.

A parked draft also becomes a notification ("draft question"): Fill it for me / Type my own
lines… / Drop it (merge decisions: Merge / Re-review). Fill it for me sends the job back to
the drafting session, which writes the lines and proposes them (`outbox propose`). The user
confirms with Post, and pr-pulse itself saves them: a session never marks its own lines as
the user's (Claude Code's auto mode refuses that, and rightly).
"""
import json
import re
import time

import db
import questions

FILL = "Fill it for me"
DROP = "Drop it"
POST = "Post"
MERGE, REREVIEW = "Merge", "Re-review"


def requeue_if_lines_ready(con, job_id):
    """When every draft of a waiting job is decided, send the job back to its session."""
    counts = dict(con.execute("SELECT status, COUNT(*) FROM outbox WHERE job_id=? GROUP BY status",
                              (job_id,)).fetchall())
    if counts.get("pending"):
        return False
    if con.execute("SELECT 1 FROM questions q JOIN outbox o ON o.id = q.draft_id WHERE o.job_id=? "
                   "AND q.status IN ('pending','showing')", (job_id,)).fetchone():
        return False   # a proposal is still waiting for the user's Post
    job = con.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
    if not job or job["status"] != "waiting_user":
        return False
    ready, fill = counts.get("ready", 0), counts.get("fill", 0)
    if ready == 0 and fill == 0:
        db.set_job(con, job_id, "done", "all drafts dropped")
        return True
    note = f"lines-ready: {ready} draft(s) to post"
    if fill:
        note += f"; fill: {fill} draft(s) for you to write the top lines"
    con.execute("UPDATE jobs SET status='queued', priority=0, note=?, updated_at=? WHERE id=?",
                (note, time.time(), job_id))
    db.event(con, "job.lines_ready", {"id": job_id, "fill": fill})
    return True


def close_question(con, draft_id):
    """The draft was handled (inbox, notification or session): its notification goes away."""
    q = con.execute("SELECT id, status FROM questions WHERE draft_id=? AND status IN ('pending','showing')",
                    (draft_id,)).fetchone()
    if not q:
        return
    con.execute("UPDATE questions SET status='answered', answered_at=? WHERE id=?", (time.time(), q["id"]))
    if q["status"] == "showing":
        questions.clear_screen(q["id"])


def set_lines(con, draft_id, lines, filled=False):
    con.execute("UPDATE outbox SET lines=?, status='ready' WHERE id=?", (lines.strip(), draft_id))
    db.event(con, "outbox.lines", {"draft": draft_id, "by": "claude (fill it for me)" if filled else "user"})
    close_question(con, draft_id)
    return requeue_if_lines_ready(con, _job(con, draft_id))


def request_fill(con, draft_id):
    con.execute("UPDATE outbox SET status='fill' WHERE id=?", (draft_id,))
    db.event(con, "outbox.fill_requested", {"draft": draft_id})
    close_question(con, draft_id)
    return requeue_if_lines_ready(con, _job(con, draft_id))


def propose(con, draft_id, lines):
    """The drafting session wrote the top lines the user asked it to fill in. Store them as a
    proposal (the draft stays 'fill'), ask the user to confirm, and park the job: it holds no
    slot while it waits. Returns the question id."""
    row = con.execute("SELECT * FROM outbox WHERE id=?", (draft_id,)).fetchone()
    close_question(con, draft_id)   # a second proposal replaces the first
    con.execute("UPDATE outbox SET lines=? WHERE id=?", (lines.strip(), draft_id))
    job = con.execute("SELECT sid FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
    _, _, details = summarize(row["draft"])
    qid = questions.add(con, row["job_id"], job["sid"] if job else None,
                        f"Post this {row['kind']} with these top lines?", [POST, DROP], True,
                        " ".join(lines.split()))
    con.execute("UPDATE questions SET kind='draft', draft_id=?, details=? WHERE id=?",
                (draft_id, f"{lines.strip()}\n—\n{details}", qid))
    db.set_job(con, row["job_id"], "waiting_user", f"top lines proposed for draft {draft_id}; waiting for Post")
    db.event(con, "outbox.proposed", {"draft": draft_id, "question": qid})
    return qid


def drop(con, draft_id):
    con.execute("UPDATE outbox SET status='dropped' WHERE id=?", (draft_id,))
    close_question(con, draft_id)
    return requeue_if_lines_ready(con, _job(con, draft_id))


def decide(con, draft_id, choice):
    """A merge decision: 'merge' or 're-review'."""
    row = con.execute("SELECT * FROM outbox WHERE id=?", (draft_id,)).fetchone()
    job = con.execute("SELECT * FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
    con.execute("UPDATE outbox SET status='posted', lines=?, posted_at=? WHERE id=?",
                (choice, time.time(), draft_id))
    close_question(con, draft_id)
    if choice == "merge":
        con.execute("UPDATE prs SET merge_ok_sha=? WHERE url=?", (job["head_sha"], job["pr_url"]))
        db.set_job(con, job["id"], "done", f"the user: merge at {(job['head_sha'] or '')[:9]}")
        db.event(con, "merge.ok", {"pr": job["pr_url"], "sha": job["head_sha"]})
    else:
        con.execute("UPDATE jobs SET status='queued', priority=0, note=?, updated_at=? WHERE id=?",
                    ("lines-ready: the user wants a re-review — re-request review from the approvers",
                     time.time(), job["id"]))


def _job(con, draft_id):
    return con.execute("SELECT job_id FROM outbox WHERE id=?", (draft_id,)).fetchone()["job_id"]


# ---- drafts as notifications ----------------------------------------------------------

_SEV = {"critical": "critical", "blocker": "critical", "improvement": "improvement",
        "suggestion": "improvement", "nit": "nit", "nits": "nit", "minor": "nit"}


def plain(line):
    """One markdown line as plain text: code spans keep every character (a metric name such as
    `*_reviewer_validated_count` stays whole); elsewhere heading, quote and emphasis marks go."""
    parts = re.split(r"(`[^`]*`)", line)
    out = []
    for i, part in enumerate(parts):
        if i % 2:
            out.append(part[1:-1])
        else:
            part = re.sub(r"^\s*[#>]+\s*", "", part) if i == 0 else part
            out.append(re.sub(r"(?<![\w*])[*_]{1,3}(?=\S)|(?<=\S)[*_]{1,3}(?![\w*])", "", part))
    return "".join(out).strip()


def summarize(draft):
    """(summary line, synthetic findings for the counts line, first lines for the details banner)."""
    lines = [l.rstrip() for l in draft.splitlines()]
    first = next((l for l in lines if l.strip()), "")
    summary = plain(first)
    findings, sev = [], None
    for l in lines:
        h = re.match(r"\s*#{2,4}\s*([A-Za-z]+)", l)
        if h:
            sev = _SEV.get(h.group(1).lower())
            continue
        if sev and re.match(r"\s*(?:[-*]|\d+\.)\s+\S", l):
            findings.append({"severity": sev, "path": "", "what": "", "scope": "runtime"})
    details = "\n".join(l for l in lines if l.strip())
    body = details.splitlines()
    details = "\n".join(body[:10]) + (f"\n… {len(body) - 10} more lines in the session" if len(body) > 10 else "")
    return summary, findings, details


def ask_for(con, draft_id):
    """Create the notification question for a parked draft (once)."""
    row = con.execute("SELECT * FROM outbox WHERE id=?", (draft_id,)).fetchone()
    if not row or row["status"] != "pending":
        return None
    if con.execute("SELECT 1 FROM questions WHERE draft_id=?", (draft_id,)).fetchone():
        return None
    job = con.execute("SELECT sid FROM jobs WHERE id=?", (row["job_id"],)).fetchone()
    summary, findings, details = summarize(row["draft"])
    if row["kind"] == "decision":
        question, options, allow_text = "Merge this exact head, or re-request review?", [MERGE, REREVIEW], False
    else:
        question, options, allow_text = f"Your top lines for this {row['kind']}?", [FILL, DROP], True
    qid = questions.add(con, row["job_id"], job["sid"] if job else None, question, options, allow_text,
                        summary, findings)
    con.execute("UPDATE questions SET kind='draft', draft_id=?, details=? WHERE id=?", (draft_id, details, qid))
    return qid


def apply_answer(con, q, text):
    """A draft question was answered (notification, or `pr-pulse answer`)."""
    did = q["draft_id"]
    row = con.execute("SELECT kind, status, lines FROM outbox WHERE id=?", (did,)).fetchone()
    if not row or row["status"] not in ("pending", "fill"):
        return "already"
    if row["status"] == "fill":
        # Confirming a proposal: only the user's Post turns the session's lines into theirs.
        if text == POST and (row["lines"] or "").strip():
            set_lines(con, did, row["lines"], filled=True)
        elif text == DROP:
            drop(con, did)
        else:
            set_lines(con, did, text)   # they typed their own lines instead
        return "ok"
    if row["kind"] == "decision":
        decide(con, did, "merge" if text == MERGE else "re-review")
    elif text == FILL:
        request_fill(con, did)
    elif text == DROP:
        drop(con, did)
    else:
        set_lines(con, did, text)   # their own words, verbatim
    return "ok"
