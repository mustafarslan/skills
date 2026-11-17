"""Auto-review on/off: whether pr-pulse reviews other people's PRs by itself.

Off holds review and re-review jobs at dispatch. Slack and GitHub are still read and every
request is still queued, so no teammate's request is lost; nothing new starts until it is on
again. Your own PRs (feedback, merge) carry on, and so does a review whose top lines you
already gave (only its post is left). `off` also stops the background sessions pr-pulse
started for reviews (their conversations are kept), because those are what load the Mac.
"""
import json
import subprocess
import time

import core
import db

KEY = "auto_review"
REVIEWS = ("review", "re-review")


def is_on(con):
    return db.get_setting(con, KEY, "1") != "0"


def held(con, job, cfg=None):
    """Is this queued job held by auto-review off (everywhere, or by its repo's rule)?"""
    if job["action"] not in REVIEWS or (job["note"] or "").startswith("lines-ready"):
        return False
    if not is_on(con):
        return True
    if cfg is not None and job["slug"]:
        import reporules
        return reporules.for_repo(cfg, job["slug"]).get("auto_review") == "off"
    return False


def counts(con):
    held_n = con.execute("SELECT COUNT(*) FROM jobs WHERE status='queued' AND action IN ('review','re-review') "
                         "AND COALESCE(note,'') NOT LIKE 'lines-ready%'").fetchone()[0]
    running = con.execute("SELECT j.id, j.pr_url, s.name, s.spawned FROM jobs j LEFT JOIN sessions s ON "
                          "s.sid=j.sid WHERE j.status IN ('claimed','delivered') AND j.action IN "
                          "('review','re-review')").fetchall()
    return held_n, running


def _stop(sid, name):
    for ref in ((sid or "")[:8], name):
        if ref and subprocess.call(["claude", "stop", ref], stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL) == 0:
            return True
    return False


def turn_off(con, stop_workers=True, stopper=None):
    """Returns the lines to show the user."""
    stopper = stopper or _stop
    db.set_setting(con, KEY, "0")
    db.event(con, "auto_review.off", {"stop_workers": stop_workers})
    out = ["Auto-review is OFF: pr-pulse starts no reviews of other people's PRs. Requests from "
           "Slack and GitHub are still queued, so none is lost. Your own PRs (feedback, merge) "
           "carry on."]
    _, running = counts(con)
    stopped, left = [], []
    for r in running:
        if stop_workers and r["spawned"]:
            sid = con.execute("SELECT sid FROM jobs WHERE id=?", (r["id"],)).fetchone()["sid"]
            if stopper(sid, r["name"]):
                con.execute("UPDATE jobs SET status='queued', sid=NULL, updated_at=?, note='requeued: "
                            "auto-review off' WHERE id=? AND status IN ('claimed','delivered')",
                            (time.time(), r["id"]))
                stopped.append(r["name"])
                continue
        left.append(r)
    # Idle review workers that only wait on you (a draft, a question) also hold memory.
    if stop_workers:
        for s in con.execute("SELECT DISTINCT s.sid, s.name FROM jobs j JOIN sessions s ON s.sid=j.sid "
                             "WHERE j.status='waiting_user' AND j.action IN ('review','re-review') "
                             "AND s.spawned=1 AND s.status!='gone'").fetchall():
            if stopper(s["sid"], s["name"]):
                stopped.append(s["name"])   # the job stays waiting; your answer resumes it
    if stopped:
        out.append(f"Stopped {len(stopped)} background review session(s): {', '.join(stopped)}. "
                   "Conversations are kept; their reviews are held and restart when it's on again.")
    for r in left:
        where = f"session {r['name']}" if r["name"] else "a session"
        out.append(f"Still running: a review of {r['pr_url']} in {where} (not started by pr-pulse, so "
                   "it was left alone).")
    held_n, _ = counts(con)
    out.append(f"Reviews held: {held_n}. Turn it back on with /pr-pulse:auto-review on.")
    return out


def turn_on(con, pr_state=None):
    """Turn it on; held reviews of PRs that closed or merged meanwhile are cancelled."""
    def gh_state(url):
        o = core.run(["gh", "pr", "view", url, "--json", "state"])
        try:
            return json.loads(o).get("state", "") if o else ""
        except ValueError:
            return ""
    pr_state = pr_state or gh_state
    db.set_setting(con, KEY, "1")
    db.event(con, "auto_review.on", {})
    cancelled = 0
    for j in con.execute("SELECT id, pr_url FROM jobs WHERE status='queued' AND action IN "
                         "('review','re-review')").fetchall():
        st = pr_state(j["pr_url"])
        if st in ("CLOSED", "MERGED"):
            db.set_job(con, j["id"], "cancelled", f"PR {st.lower()} while auto-review was off")
            cancelled += 1
    held_n, _ = counts(con)
    return [f"Auto-review is ON: pr-pulse reviews shared and requested PRs again. "
            f"Reviews waiting to start: {held_n}"
            + (f"; {cancelled} dropped because their PR closed or merged meanwhile." if cancelled else ".")]


def status_line(con):
    if is_on(con):
        return "auto-review: on"
    held_n, running = counts(con)
    return f"auto-review: OFF · {held_n} review(s) held · {len(running)} still running"
