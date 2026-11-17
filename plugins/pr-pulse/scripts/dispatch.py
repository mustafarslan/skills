"""pr-pulse dispatch: hand queued jobs to a registered idle session or a fresh worker.

Nothing here decides *whether* a PR needs work (that is rules.py); this only decides *who*
does it, delivers it, and recovers jobs whose session went quiet.
"""
import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

import core
import db

PROMPT_FILE = Path(__file__).resolve().parent.parent / "prompts" / "job.md"
CLI = Path(__file__).resolve().parent / "pr-pulse"
GUARD = Path(__file__).resolve().parent / "post-guard.py"
INBOX = db.HOME / "inbox"
WATCH_FRESH = 120          # an inbox watcher touches its .live file every few seconds

SKILL = {"review": "/pr-review", "re-review": "/pr-review", "feedback": "/pr-feedback",
         "merge": "/pr-merge"}

MERGE_CHECK = (
    "Do NOT merge. The head moved after the approval. Run `git fetch origin` and "
    "`git diff <approved>..<head>` (the commits are in 'Why this job'). Write at most 5 lines "
    "for the user: what changed, and whether it changes behaviour or an ADR decision. Park it "
    "with `pr-pulse outbox add --job {id} --kind decision <<'EOF'` … `EOF`, then "
    "`pr-pulse job wait-user {id}`. They answer merge or re-review in /pr-pulse:inbox. If it "
    "comes back to you with re-review, re-request review from the approvers with "
    "`gh pr edit {n} --add-reviewer <login>` (no comment text), then `pr-pulse job done {id}`.")


def inbox_live(sid):
    f = INBOX / f"{sid}.live"
    return f.exists() and time.time() - f.stat().st_mtime < WATCH_FRESH


def busy_sids(con):
    return {r[0] for r in con.execute(
        "SELECT sid FROM jobs WHERE status IN ('claimed','delivered','waiting_user') "
        "AND sid IS NOT NULL").fetchall()}


# A session with a running Monitor (its inbox watcher) shows as "busy" in `claude agents` for as
# long as the watcher runs, even when it is doing nothing (found in the scratch test,
# 2026-11-09). A watcher line never interrupts: the session reads it after its current turn.
# So busy is fine to deliver to; only a session stuck on a prompt (waiting) or gone is not.
READY = ("idle", "busy")


def pick_session(con, slug, sticky=None, pr_url=None):
    """A registered session in this repo with a live inbox watcher and no job, None (no session:
    a worker may take it), or focus.HOLD (wait for the PR's paired session; no worker).

    sticky: the session that already worked on this job (its context is worth keeping).
    pr_url: the job's PR, for session focus (focus.py): a PR opened by a session that has a
    focused PR session goes only there, and a focused session never takes anything else.
    """
    import focus
    taken = busy_sids(con)
    if sticky:
        s = con.execute("SELECT status FROM sessions WHERE sid=?", (sticky,)).fetchone()
        if s and s["status"] in READY and inbox_live(sticky):
            return sticky   # the session that drafted the text posts it, registered or not
    pairs = focus.pairs_for(con, slug, pr_url) if pr_url else []
    if pairs:
        ready = [p["sid"] for p in pairs if p["status"] in READY and inbox_live(p["sid"])
                 and p["sid"] not in taken]
        if ready:
            return ready[0]
        listening = [p for p in pairs if p["status"] != "gone" and inbox_live(p["sid"])]
        if not listening:
            focus_outage(con, pairs, pr_url)
        return focus.HOLD   # busy: wait silently; gone or deaf: held, the user was told
    rows = con.execute(
        "SELECT s.sid, s.status, s.focus, (r.pr_session = s.sid) AS preferred FROM sessions s "
        "LEFT JOIN repos r ON r.slug = s.slug "
        "WHERE s.slug=? AND s.registered=1 AND s.status != 'gone'", (slug,)).fetchall()
    cands = []
    for r in rows:
        if not focus.is_general(r):
            continue   # a focused session takes only its own sessions' PRs
        if r["status"] not in READY or not inbox_live(r["sid"]):
            continue
        if r["sid"] in taken and r["sid"] != sticky:
            continue
        cands.append((r["sid"] == sticky, r["preferred"] or 0, r["sid"]))
    cands.sort(reverse=True)
    return cands[0][2] if cands else None


def focus_outage(con, pairs, pr_url):
    """Tell the user once per outage that a paired PR session is not listening."""
    names = ", ".join(p["name"] or p["sid"][:8] for p in pairs)
    key = "focus_outage:" + ",".join(sorted(p["sid"] for p in pairs))
    if db.get_setting(con, key):
        return
    db.set_setting(con, key, time.time())
    pr = con.execute("SELECT slug, n FROM prs WHERE url=?", (pr_url,)).fetchone()
    ref = f"{pr['slug'].split('/')[-1]}#{pr['n']}" if pr else pr_url
    import focus
    origin = focus.origin_name(con, pr_url) or "its session"
    notify(f"{ref} waits for {names}, which is not listening. In {names}, run /pr-pulse:join "
           f"--for {origin}; or `pr-pulse focus clear {names.split(', ')[0]}` to hand its PRs back.")
    db.event(con, "focus.outage", {"pr": pr_url, "sessions": names})


def focus_listening(con):
    """Clear outage notices for paired sessions that listen again (so a new outage is told)."""
    for r in con.execute("SELECT key FROM settings WHERE key LIKE 'focus_outage:%'").fetchall():
        sids = r["key"].split(":", 1)[1].split(",")
        if any(inbox_live(s) for s in sids):
            con.execute("DELETE FROM settings WHERE key=?", (r["key"],))


MERGE_ASK_TASK = (
    "this repo's rule is merge=ask: before merging, ask {{{{me}}}} with `pr-pulse ask --job {id}` "
    "(question: merge #{n} now?, options Merge / Not yet, a one-line summary of approvals, CI and "
    "anything open). Only on Merge, run `/pr-merge {n}`; otherwise `pr-pulse job done {id}`.")


def repo_rules_text(slug):
    import reporules
    rules_ = reporules.for_repo(db.load_config(), slug).get("repo_rules_text") or []
    if not rules_:
        return ""
    return ("**{{me}}'s rules for " + slug + "** (follow every one, on every step of this job):\n"
            + "\n".join(f"- {r}" for r in rules_) + "\n")


DECISION_DAYS = 14
QUICK_SECONDS = 10   # answered this soon after the banner showed: maybe a stray click


def earlier_decisions(con, pr_url, job_id, now=None, limit=5):
    """The user's answers to questions from OTHER jobs on this PR (newest first): a new job must
    know them, or a new approval re-asks a hold they already decided (#2972 asked 3 times)."""
    if con is None:
        return []
    now = now or time.time()
    return con.execute(
        "SELECT q.id, q.question, q.answer, q.answered_at, q.shown_at, q.answered_via "
        "FROM questions q JOIN jobs j ON j.id = q.job_id "
        "WHERE j.pr_url=? AND q.job_id != ? AND q.status='answered' AND q.kind='question' "
        "AND COALESCE(q.answered_via,'') != 'withdrawn' "
        "AND COALESCE(q.answer,'') != '' AND q.answered_at > ? ORDER BY q.answered_at DESC LIMIT ?",
        (pr_url, job_id, now - DECISION_DAYS * 86400, limit)).fetchall()


def decisions_text(rows):
    if not rows:
        return ""
    def quick(r):
        return (r["answered_via"] == "notification" and r["shown_at"]
                and 0 <= r["answered_at"] - r["shown_at"] < QUICK_SECONDS)
    items = "\n".join(
        f"- {time.strftime('%Y-%m-%d %H:%M', time.localtime(r['answered_at']))}: "
        f"asked \"{r['question']}\", {{{{me}}}} answered \"{r['answer']}\""
        + (f" (answered {int(r['answered_at'] - r['shown_at'])}s after the notification showed: "
           "it may be a stray click, so confirm it with {{me}} before acting on it)" if quick(r) else "")
        for r in rows)
    return ("**{{me}}'s earlier decisions on this PR** (newest first; they still stand):\n" + items + "\n"
            "Do not ask {{me}} again about something decided here. Ask only when what a decision "
            "depended on has changed (a new head, a review asking for changes, a failing check, or "
            "what it waited for has now happened): then say what changed in the summary. When you "
            "act on an earlier decision, name it in your one-line summary.\n")


def render_prompt(job, pr, extra="", con=None):
    tmpl = PROMPT_FILE.read_text()
    slug, n = pr["slug"], pr["n"]
    action = job["action"]
    lines = ""
    if job.get("note", "").startswith("lines-ready"):
        lines = ("{me} has answered. Run `pr-pulse outbox show --job {id}`: post each draft that has "
                 "their lines.")
        if "fill:" in job.get("note", ""):
            lines += (" For each draft marked **fill**, {me} asked you to write the top lines: read "
                      "the top-lines guide (`prompts/top-lines-guide.md` next to the pr-pulse scripts), write "
                      "them, then propose them as one standalone command: `pr-pulse outbox propose <draft id> "
                      "<<'EOF'`, your lines, `EOF`. pr-pulse asks {me} to Post, type their own lines or Drop, "
                      "saves their choice itself, and brings the job back here. Then stop and wait. Never "
                      "run `pr-pulse outbox lines` yourself: only {me}'s answer turns lines into theirs.")
    vals = {
        "id": job["id"], "action": action, "n": n, "slug": slug,
        "task": (MERGE_CHECK.format(id=job["id"], n=n) if action == "merge-check"
                 else MERGE_ASK_TASK.format(id=job["id"], n=n)
                 if action == "merge" and "merge=ask" in (job.get("note") or "")
                 else f"run `{SKILL[action]} {n}`."),
        "url": pr["url"], "title": pr.get("title") or "", "note": job.get("note") or "",
        "extra": extra, "lines_ready": lines.format(id=job["id"], me="{{me}}"),
        "decisions": decisions_text(earlier_decisions(con, job["pr_url"], job["id"])),
        "repo_rules": repo_rules_text(slug),
        "me": core.my_name(db.load_config()),
    }
    out = tmpl
    for k, v in sorted(vals.items(), key=lambda kv: kv[0] == "me"):   # {{me}} last: others contain it
        out = out.replace("{{" + k + "}}", str(v))
    if not shutil.which("pr-pulse"):
        out = out.replace("`pr-pulse ", f"`{CLI} ")
    return out


def deliver_inbox(con, job, sid, dry=False):
    """Append one line to the session's inbox; its Monitor wakes it."""
    pr = con.execute("SELECT * FROM prs WHERE url=?", (job["pr_url"],)).fetchone()
    line = json.dumps({"job": job["id"], "action": job["action"], "pr": job["pr_url"],
                       "ref": f"{pr['slug']}#{pr['n']}" if pr else job["pr_url"],
                       "ts": time.time()})
    if dry:
        core_log(f"DRY deliver job {job['id']} ({job['action']} {job['pr_url']}) to {sid}")
        return True
    if not db.claim(con, job["id"], sid):
        return False
    INBOX.mkdir(parents=True, exist_ok=True)
    with open(INBOX / f"{sid}.jsonl", "a") as f:
        f.write(line + "\n")
    db.set_job(con, job["id"], "delivered")
    db.event(con, "job.delivered", {"id": job["id"], "sid": sid})
    return True


def worker_name(slug, n, action):
    return re.sub(r"[^A-Za-z0-9._-]", "-", f"pr-{slug.replace('/', '-')}-{n}-{action}")


def wt_dir(root):
    """Worker worktrees live in <repo>/.claude/worktrees/, like Claude Code's own: a folder
    inside a trusted repo is trusted, so `claude --bg` starts there without a trust prompt."""
    return Path(root) / ".claude" / "worktrees"


def ensure_ignored(root):
    """Keep <repo>/.claude/worktrees out of `git status`, locally (info/exclude, never committed)."""
    if core.run(["git", "-C", root, "check-ignore", "-q", ".claude/worktrees/x"]) is not None:
        return
    common = (core.run(["git", "-C", root, "rev-parse", "--path-format=absolute",
                        "--git-common-dir"]) or "").strip()
    if not common:
        return
    excl = Path(common) / "info" / "exclude"
    excl.parent.mkdir(parents=True, exist_ok=True)
    with open(excl, "a") as f:
        f.write("\n# pr-pulse worker worktrees\n.claude/worktrees/\n")


def prepare_worktree(root, slug, n):
    """A fresh worktree with the PR checked out. Returns (path, detached_branch or '')."""
    base = wt_dir(root)
    base.mkdir(parents=True, exist_ok=True)
    ensure_ignored(root)
    wt = base / re.sub(r"[^A-Za-z0-9._-]", "-", f"pr-pulse-{slug.replace('/', '--')}-{n}")
    if wt.exists():
        # Re-use only if it is still a registered worktree of this repo.
        if core.run(["git", "-C", str(wt), "rev-parse", "--is-inside-work-tree"]):
            core.run(["gh", "pr", "checkout", str(n), "--force"], cwd=str(wt), timeout=120)
            return str(wt), ""
        shutil.rmtree(wt, ignore_errors=True)
    core.run(["git", "-C", root, "fetch", "--quiet", "origin"], timeout=120)
    head = (core.run(["git", "-C", root, "symbolic-ref", "--short", "refs/remotes/origin/HEAD"])
            or "origin/main").strip()
    if core.run(["git", "-C", root, "worktree", "add", "--detach", str(wt), head], timeout=120) is None:
        return None, ""
    if core.run(["gh", "pr", "checkout", str(n)], cwd=str(wt), timeout=120) is not None:
        return str(wt), ""
    # The branch is checked out elsewhere (e.g. The user's main worktree): use a detached head.
    if core.run(["gh", "pr", "checkout", str(n), "--detach"], cwd=str(wt), timeout=120) is not None:
        br = core.run(["gh", "pr", "view", str(n), "--json", "headRefName", "-q", ".headRefName"],
                      cwd=str(wt)) or ""
        return str(wt), br.strip()
    return None, ""


def worker_cmd(cfg, name, prompt, resume_sid=None):
    """`claude --bg` with the worker allowlist. The list flags take several values, so `-n` comes
    after them and the prompt comes last, where no list can swallow it.

    A resume passes NO flags: a background session keeps its saved options (allowlist, guard),
    and any flag makes `claude --bg --resume` start a copy instead of continuing the session
    (Claude Code says so; found in the scratch test, 2026-11-09)."""
    if resume_sid:
        return ["claude", "--bg", "--resume", resume_sid, prompt]
    args = ["claude", "--bg"]
    allowed = [str(a) for a in (cfg.get("worker_allowed_tools") or [])]
    denied = [str(a) for a in (cfg.get("worker_denied_tools") or [])]
    if allowed:
        args += ["--allowedTools"] + allowed
    if denied:
        args += ["--disallowedTools"] + denied
    # The top-lines posting guard, given to every worker directly so it holds even when the
    # pr-pulse plugin (whose hooks.json also has it) is not installed.
    args += ["--settings", json.dumps({"hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": [
        {"type": "command", "command": f'"{GUARD}"', "timeout": 10}]}]}})]
    args += list(cfg.get("worker_args") or [])
    return args + ["-n", name, prompt]


def spawn_worker(con, job, cfg, dry=False):
    pr = con.execute("SELECT * FROM prs WHERE url=?", (job["pr_url"],)).fetchone()
    repo = con.execute("SELECT path FROM repos WHERE slug=?", (pr["slug"],)).fetchone() if pr else None
    if not pr or not repo:
        db.set_job(con, job["id"], "failed", "PR or repo not known")
        return False
    name = worker_name(pr["slug"], pr["n"], job["action"])
    if dry:
        core_log(f"DRY spawn worker {name} for job {job['id']}")
        return True
    if not db.claim(con, job["id"], f"name:{name}"):
        return False
    import workers
    workers.clear_name(con, name, core.list_sessions() or [])   # a finished worker's leftover
    wt, detached = prepare_worktree(repo["path"], pr["slug"], pr["n"])
    if not wt:
        db.set_job(con, job["id"], "failed", "could not prepare a worktree")
        notify(f"pr-pulse: could not prepare a worktree for {pr['slug']}#{pr['n']}")
        return False
    extra = ("This is a pr-pulse worker in its own worktree. The user is not watching this session: "
             "ask them decisions with `pr-pulse ask` (not in chat), park outward text in the "
             "outbox, and keep your inbox watcher running so their answers and lines reach you.")
    if detached:
        extra += (f" The PR branch is checked out elsewhere, so this worktree is detached: "
                  f"push with `git push origin HEAD:{detached}`.")
    prompt = render_prompt(dict(job), dict(pr), extra, con)
    args = worker_cmd(cfg, name, prompt)
    try:
        p = subprocess.run(args, cwd=wt, capture_output=True, text=True, timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        db.set_job(con, job["id"], "failed", f"spawn failed: {e}")
        return False
    if p.returncode != 0:
        db.set_job(con, job["id"], "failed", f"spawn failed: {(p.stderr or p.stdout)[:200]}")
        return False
    con.execute("UPDATE jobs SET wt=? WHERE id=?", (wt, job["id"]))
    db.set_job(con, job["id"], "delivered", f"worker {name}")
    db.event(con, "worker.spawned", {"job": job["id"], "name": name, "wt": wt})
    return True


def resume_worker(con, job, sid, cfg, dry=False):
    """Bring back the session that drafted the text, so it posts with the user's lines.

    Only once it has gone quiet (exited, or idle with no watcher): a busy session is left
    alone and the job waits for the next tick.
    """
    s = con.execute("SELECT status, cwd, name FROM sessions WHERE sid=?", (sid,)).fetchone()
    if s and s["status"] == "busy":
        return False
    pr = con.execute("SELECT * FROM prs WHERE url=?", (job["pr_url"],)).fetchone()
    if not pr:
        return False
    cwd = job.get("wt") or (s["cwd"] if s else None)
    if not cwd or not os.path.isdir(cwd):
        db.set_job(con, job["id"], "failed", "drafting session's folder is gone")
        notify(f"pr-pulse: could not resume the session for job {job['id']}")
        return False
    if dry:
        core_log(f"DRY resume {sid} for job {job['id']}")
        return True
    if not db.claim(con, job["id"], sid):
        return False
    # `claude --bg --resume <id> "<prompt>"` only delivers the prompt to a stopped session; for a
    # running one it starts a copy that never gets the prompt (found in the scratch test). So
    # stop every live copy of this worker first.
    stop_live_copies(sid, s["name"] if s else None, con)
    prompt = render_prompt(dict(job), dict(pr), "", con)
    try:
        p = subprocess.run(worker_cmd(cfg, None, prompt, resume_sid=sid), cwd=cwd,
                           capture_output=True, text=True, timeout=60)
        ok = p.returncode == 0
    except (OSError, subprocess.SubprocessError):
        ok = False
    if not ok:
        db.set_job(con, job["id"], "failed", "resume failed")
        notify(f"pr-pulse: could not resume the session for job {job['id']}")
        return False
    db.set_job(con, job["id"], "delivered")
    db.event(con, "worker.resumed", {"job": job["id"], "sid": sid})
    return True


def stop_live_copies(sid, name, con=None):
    """Stop the session and its same-named copies, but never another worker that holds a job."""
    import workers
    live = core.list_sessions() or []
    for x in live:
        other = x.get("sessionId") != sid
        if other and con is not None and workers.has_active_job(con, x.get("sessionId", "")):
            continue
        if x.get("sessionId") == sid or (name and x.get("name") == name):
            for ref in (x.get("sessionId", "")[:8], x.get("name")):
                if ref and subprocess.call(["claude", "stop", ref], stdout=subprocess.DEVNULL,
                                           stderr=subprocess.DEVNULL) == 0:
                    break
    for _ in range(20):
        live = core.list_sessions() or []
        if not any(x.get("sessionId") == sid or (name and x.get("name") == name
                                                 and not (con is not None and workers.has_active_job(
                                                     con, x.get("sessionId", ""))))
                   for x in live):
            return True
        time.sleep(0.5)
    return False


def bind_worker_sids(con):
    """Jobs claimed as name:<worker> learn the real session id once `claude agents` lists it, and
    pr-pulse's own workers get their "started by pr-pulse" mark (workers.mark_spawned)."""
    import workers
    workers.mark_spawned(con)
    for j in con.execute("SELECT id, sid FROM jobs WHERE sid LIKE 'name:%' "
                         "AND status IN ('delivered','waiting_user')").fetchall():
        row = con.execute("SELECT sid FROM sessions WHERE name=? AND status!='gone' "
                          "ORDER BY seen_at DESC", (j["sid"][5:],)).fetchone()
        if row:
            con.execute("UPDATE jobs SET sid=? WHERE id=?", (row["sid"], j["id"]))
            con.execute("UPDATE sessions SET spawned=1 WHERE sid=?", (row["sid"],))


def dispatch(con, cfg, dry=False):
    """Fill free pool slots, highest priority first. Returns the number of jobs handed out."""
    free = int(cfg.get("pool_size", 3)) - db.running_count(con)
    handed = 0
    queued = con.execute("SELECT j.*, p.slug FROM jobs j LEFT JOIN prs p ON p.url=j.pr_url "
                         "WHERE j.status='queued' ORDER BY j.priority, j.created_at").fetchall()
    import autoreview
    import focus
    focus_listening(con)
    for job in queued:
        if free <= 0:
            break
        if autoreview.held(con, job, cfg):
            continue   # auto-review off: stays queued, starts when it's on again
        job = dict(job)
        if not job.get("slug"):
            db.set_job(con, job["id"], "failed", "PR not tracked")
            continue
        skill = core.SKILL_FOR.get(job["action"])
        repo = con.execute("SELECT path FROM repos WHERE slug=?", (job["slug"],)).fetchone()
        if skill and not core.skill_source(skill, repo["path"] if repo else None):
            # Neither the user nor the repo has the skill: don't start a session that can't do it.
            if dry:
                core_log(f"DRY skip job {job['id']}: no /{skill} skill for {job['slug']}")
                continue
            db.set_job(con, job["id"], "failed", f"no /{skill} skill (personal, plugin or in the repo)")
            notify(f"pr-pulse: no /{skill} skill for {job['slug']}; job {job['id']} skipped")
            continue
        sticky = job["sid"] if job.get("sid") and not str(job["sid"]).startswith("name:") else None
        if sticky and (job.get("note") or "").startswith("lines-ready"):
            # Only the session that drafted the text posts it: wake it or resume it, never
            # hand the posting to another session.
            s = con.execute("SELECT status FROM sessions WHERE sid=?", (sticky,)).fetchone()
            if s and s["status"] in READY and inbox_live(sticky):
                ok = deliver_inbox(con, job, sticky, dry)
            else:
                ok = resume_worker(con, job, sticky, cfg, dry)
            if ok:
                handed += 1
                free -= 1
            continue
        sid = pick_session(con, job["slug"], sticky, job["pr_url"])
        if sid == focus.HOLD:
            continue   # waits for its paired PR session; takes no slot and starts no worker
        if sid:
            ok = deliver_inbox(con, job, sid, dry)
        elif cfg.get("spawn_workers", True):
            ok = spawn_worker(con, job, cfg, dry)
        else:
            ok = False
        if ok:
            handed += 1
            free -= 1
    return handed


def recover_stale(con, cfg):
    """Delivered jobs with no heartbeat for stale_minutes: re-queue once, then fail."""
    limit = time.time() - 60 * int(cfg.get("stale_minutes", 45))
    stall_limit = time.time() - 60 * int(cfg.get("stall_minutes", 120))
    for j in con.execute("SELECT * FROM jobs WHERE status IN ('claimed','delivered') "
                         "AND COALESCE(heartbeat_at, updated_at) < ?", (limit,)).fetchall():
        if con.execute("SELECT 1 FROM questions WHERE job_id=? AND status IN ('pending','showing')",
                       (j["id"],)).fetchone():
            continue   # waiting for the user's answer to a question, not stale
        sess = con.execute("SELECT status, name, spawned FROM sessions WHERE sid=?", (j["sid"],)).fetchone()
        if sess and sess["status"] in ("busy", "waiting"):
            # busy: still working, a long review is not a stale one. But `claude agents` also
            # says busy for an idle session whose inbox watcher runs, so busy alone can hold a
            # slot forever. Past stall_minutes with no heartbeat, the job is stalled.
            # waiting: stuck on a permission prompt; watch_waiting() tells the user. A second
            # worker on the same PR would only make it worse.
            if (sess["status"] == "busy"
                    and (j["heartbeat_at"] or j["updated_at"]) < stall_limit):
                park_stalled(con, j, sess)
            continue
        if j["attempts"] < 2:
            con.execute("UPDATE jobs SET status='queued', updated_at=?, sid=NULL WHERE id=?",
                        (time.time(), j["id"]))
            db.event(con, "job.requeued", {"id": j["id"], "why": "stale"})
        else:
            db.set_job(con, j["id"], "failed", "stale twice")
            notify(f"pr-pulse: job {j['id']} ({j['action']}) went quiet twice and was dropped")


STALLED = "stalled"


def park_stalled(con, j, sess):
    """A job whose session went quiet but still looks busy: free its slot and tell the user once.
    Never requeue or fail it: it may hold a review the user already approved, and a second
    worker would start over. `pr-pulse job beat` from the session picks it up again."""
    pr = con.execute("SELECT slug, n FROM prs WHERE url=?", (j["pr_url"],)).fetchone()
    ref = f"{pr['slug']}#{pr['n']}" if pr else j["pr_url"]
    import workers
    how = (workers.attach_cmd(j["sid"]) if sess["spawned"] else f"switch to session {sess['name'] or j['sid'][:8]}")
    db.set_job(con, j["id"], "waiting_user", f"{STALLED}: no heartbeat while its session looked busy; {how}")
    db.event(con, "job.stalled", {"id": j["id"], "sid": j["sid"]})
    notify(f"{ref} {j['action']}: its session went quiet; job {j['id']} no longer holds a slot — {how}")


REMIND_WAITING = 2 * 3600


def watch_waiting(con, now=None):
    """Tell the user when a session holding a pr-pulse job waits for input (usually a permission
    prompt nobody is there to approve): at once, then every 2 hours while it keeps waiting.
    Returns the job ids that were announced this time."""
    now = now or time.time()
    told = []
    rows = con.execute(
        "SELECT j.id, j.action, j.sid, s.name, s.spawned, p.slug, p.n FROM jobs j "
        "JOIN sessions s ON s.sid = j.sid LEFT JOIN prs p ON p.url = j.pr_url "
        "WHERE j.status IN ('claimed','delivered') AND s.status = 'waiting'").fetchall()
    waiting_ids = {r["id"] for r in rows}
    for r in rows:
        key = f"waiting_told:{r['id']}"
        last = float(db.get_setting(con, key, "0"))
        if now - last < REMIND_WAITING:
            continue
        db.set_setting(con, key, now)
        import workers
        how = (workers.attach_cmd(r["sid"]) if r["spawned"]
               else f"switch to session {r['name'] or r['sid'][:8]}")
        notify(f"{r['slug']}#{r['n']} {r['action']}: waiting for your approval — {how}")
        db.event(con, "job.waiting_input", {"id": r["id"], "sid": r["sid"]})
        told.append(r["id"])
    # Forget the reminder clock for jobs that are no longer waiting.
    for row in con.execute("SELECT key FROM settings WHERE key LIKE 'waiting_told:%'").fetchall():
        if int(row["key"].split(":", 1)[1]) not in waiting_ids:
            con.execute("DELETE FROM settings WHERE key=?", (row["key"],))
    return told


def cleanup_worktrees(con):
    """Remove pr-pulse worker worktrees whose jobs are finished and that hold no unpushed work."""
    active = {r[0] for r in con.execute(
        "SELECT wt FROM jobs WHERE status IN ('queued','claimed','delivered','waiting_user') "
        "AND wt IS NOT NULL").fetchall()}
    dirs = []
    for r in con.execute("SELECT path FROM repos").fetchall():
        base = wt_dir(r["path"])
        if base.exists():
            dirs += [d for d in base.iterdir() if d.name.startswith("pr-pulse-")]
    for wt in dirs:
        if not wt.is_dir() or str(wt) in active:
            continue
        dirty = core.run(["git", "-C", str(wt), "status", "--porcelain"])
        if dirty is None or dirty.strip():
            continue
        unpushed = core.run(["git", "-C", str(wt), "log", "--oneline", "@{u}..HEAD"])
        if unpushed and unpushed.strip():
            continue
        if core.run(["git", "-C", str(wt), "worktree", "remove", str(wt)]) is not None:
            db.event(con, "worktree.removed", str(wt))


def notify(msg):
    if os.environ.get("PR_PULSE_NO_NOTIFY") == "1":
        return
    if core.use_alerter():
        # alerter shows the pr-pulse logo; detached, so a notification never holds up a tick
        subprocess.Popen(["alerter", "--title", "pr-pulse", "--message", msg, "--group", "pr-pulse-info",
                          "--timeout", "30"] + core.icon_args(), stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return
    safe = msg.replace("\\", "\\\\").replace('"', '\\"')
    core.run(["osascript", "-e", f'display notification "{safe}" with title "pr-pulse"'])


def core_log(msg):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), msg, flush=True)
