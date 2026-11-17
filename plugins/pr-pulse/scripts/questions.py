"""Questions a pr-pulse job session asks the user, answered from a notification.

A session runs `pr-pulse ask` instead of Claude Code's own question box. The daemon starts the
asker (`pr-pulse-asker.py`) for one question at a time; the answer goes to the session's inbox,
which wakes it. Answers are tied to the question id: a question whose job finished is expired
and its late answer is dropped.
"""
import json
import time

import db

RESHOW_SECONDS = 3600
TYPE_LABEL = "Type an answer…"


OPEN_LABEL = "Open session"
DETAILS_LABEL = "Details…"


def add(con, job_id, sid, question, options, allow_text, summary="", findings=None):
    import rules
    fs = rules.normalize_findings(findings or [])
    cur = con.execute(
        "INSERT INTO questions(job_id, sid, question, options, allow_text, created_at, summary, findings) "
        "VALUES(?,?,?,?,?,?,?,?)", (job_id, sid, question, json.dumps(list(options)), int(allow_text),
                                    time.time(), summary or "", json.dumps(fs)))
    db.event(con, "question.asked", {"id": cur.lastrowid, "job": job_id})
    return cur.lastrowid


def job_active(con, job_id):
    return bool(con.execute("SELECT 1 FROM jobs WHERE id=? AND status IN "
                            "('claimed','delivered','waiting_user')", (job_id,)).fetchone())


def clear_screen(qid=None):
    """Remove the question notification and stop its asker, so an answered (or expired)
    question never stays on screen. Safe to call when nothing is showing."""
    import os
    import shutil
    import subprocess
    try:
        pattern = f"pr-pulse-asker.py {qid}$" if qid else "pr-pulse-asker.py"
        # never stop the asker we may be running in
        for pid in (subprocess.run(["pgrep", "-f", pattern], capture_output=True, text=True,
                                   timeout=5).stdout or "").split():
            if int(pid) != os.getpid():
                subprocess.run(["kill", pid], capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", "alerter .*--group pr-pulse-question"], capture_output=True, timeout=5)
        if shutil.which("alerter"):
            # `alerter --remove` can hang: fire and forget
            subprocess.Popen(["alerter", "--remove", "pr-pulse-question"], stdin=subprocess.DEVNULL,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    except (OSError, subprocess.SubprocessError, ValueError):
        pass   # clearing the screen is best effort; it must never break an answer


def answer(con, qid, text, via, inbox_dir):
    """Record an answer and wake the session. Returns 'ok', 'expired', 'already' or 'unknown'."""
    q = con.execute("SELECT * FROM questions WHERE id=?", (qid,)).fetchone()
    if not q:
        return "unknown"
    if q["status"] in ("answered", "expired"):
        return "already" if q["status"] == "answered" else "expired"
    if not job_active(con, q["job_id"]):
        con.execute("UPDATE questions SET status='expired' WHERE id=?", (qid,))
        return "expired"
    if q["kind"] == "draft":
        import outbox
        # Mark it answered first: then the draft's own clean-up finds no open question and never
        # tries to clear the banner the answer just came from.
        con.execute("UPDATE questions SET status='answered', answer=?, answered_via=?, answered_at=? WHERE id=?",
                    (text, via, time.time(), qid))
        if via != "notification" and q["status"] == "showing":
            clear_screen(qid)
        res = outbox.apply_answer(con, q, text)
        db.event(con, "question.answered", {"id": qid, "via": via, "draft": q["draft_id"]})
        return res
    cur = con.execute("UPDATE questions SET status='answered', answer=?, answered_via=?, answered_at=? "
                      "WHERE id=? AND status IN ('pending','showing')", (text, via, time.time(), qid))
    if cur.rowcount != 1:
        return "already"
    if via != "notification" and q["status"] == "showing":
        clear_screen(qid)   # answered in a session or the inbox while it was on screen
    con.execute("UPDATE jobs SET heartbeat_at=? WHERE id=?", (time.time(), q["job_id"]))
    if q["sid"]:
        inbox_dir.mkdir(parents=True, exist_ok=True)
        with open(inbox_dir / f"{q['sid']}.jsonl", "a") as f:
            f.write(json.dumps({"answer": qid, "job": q["job_id"], "text": text, "ts": time.time()}) + "\n")
    db.event(con, "question.answered", {"id": qid, "via": via})
    return "ok"


def expire_finished(con):
    """Questions of jobs that ended are never shown again (and leave the screen)."""
    if con.execute("SELECT 1 FROM questions WHERE status='showing' AND job_id NOT IN "
                   "(SELECT id FROM jobs WHERE status IN ('claimed','delivered','waiting_user'))").fetchone():
        clear_screen()
    con.execute("UPDATE questions SET status='expired' WHERE status IN ('pending','showing') AND "
                "job_id NOT IN (SELECT id FROM jobs WHERE status IN ('claimed','delivered','waiting_user'))")


def next_to_show(con, now=None):
    """The oldest question due on screen, or None. Only one is ever showing at a time."""
    now = now or time.time()
    if con.execute("SELECT 1 FROM questions WHERE status='showing'").fetchone():
        return None
    return con.execute("SELECT * FROM questions WHERE status='pending' AND "
                       "(shown_at IS NULL OR shown_at < ?) ORDER BY created_at LIMIT 1",
                       (now - RESHOW_SECONDS,)).fetchone()


def claim_for_showing(con, qid):
    return con.execute("UPDATE questions SET status='showing', shown_at=? WHERE id=? AND status='pending'",
                       (time.time(), qid)).rowcount == 1


def release(con, qid):
    """Shown but not answered (Later, closed, timed out): back to pending, shown again later."""
    con.execute("UPDATE questions SET status='pending' WHERE id=? AND status='showing'", (qid,))


def has_open(con, job_id):
    return bool(con.execute("SELECT 1 FROM questions WHERE job_id=? AND status IN ('pending','showing')",
                            (job_id,)).fetchone())
