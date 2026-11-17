#!/usr/bin/env python3
"""pr-pulsed: the pr-pulse daemon. Runs under launchd (see `pr-pulse daemon install`).

    pr-pulsed.py            loop forever, one tick every tick_seconds
    pr-pulsed.py --once     one tick, then exit
    pr-pulsed.py --dry-run  decide and log, but deliver, spawn and post nothing

Each tick: sync sessions -> own PRs (feedback / merge) -> PRs that request my review ->
Slack (shared-PR pool, re-review tags) -> pool pull -> review verdicts -> dispatch.
While paused it keeps watching and queueing, and hands nothing out.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import announce  # noqa: E402
import core      # noqa: E402
import current   # noqa: E402
import db        # noqa: E402
import dispatch  # noqa: E402
import rules     # noqa: E402
import questions  # noqa: E402
import slack     # noqa: E402
import waiting   # noqa: E402
import subprocess  # noqa: E402

ENV_FILE = Path.home() / ".config" / "pr-pulse" / "env"


def load_env_file():
    """launchd does not read ~/.zshrc: take our secrets from ~/.config/pr-pulse/env."""
    import envfile
    envfile.load_into_environ()


def log(msg):
    print(time.strftime("%Y-%m-%dT%H:%M:%S"), msg, flush=True)


def my_login(con):
    login = db.get_setting(con, "gh_login")
    if not login:
        login = (core.run(["gh", "api", "user", "-q", ".login"]) or "").strip()
        if login:
            db.set_setting(con, "gh_login", login)
    return login


def pr_ref(pr_url):
    m = rules.PR_URL_RE.search(pr_url)
    return (f"{m.group(1)}/{m.group(2)}", int(m.group(3))) if m else (None, None)


def view_pr(url):
    out = core.run(["gh", "pr", "view", url, "--json", core.PR_FIELDS], timeout=45)
    try:
        return json.loads(out) if out else None
    except ValueError:
        return None


# ---- own PRs --------------------------------------------------------------------------

MERGE_ASK = "repo rule merge=ask"


def own_prs(con, cfg, me):
    import reporules
    base_cfg = cfg
    for repo in con.execute("SELECT slug FROM repos").fetchall():
        slug = repo["slug"]
        cfg = reporules.for_repo(base_cfg, slug)        # this repo's PR rules on top of the global ones
        ignore = tuple(cfg.get("ignore_authors") or rules.DEFAULT_IGNORE)
        prs = core.own_open_prs(slug)
        if prs is None:
            log(f"gh failed for {slug}; skipped this tick")
            continue
        open_urls = set()
        for pr in prs:
            url = pr["url"]
            open_urls.add(url)
            row = con.execute("SELECT * FROM prs WHERE url=?", (url,)).fetchone()
            row = dict(row) if row else None
            old, new = core.upsert_pr(con, slug, pr, "own")
            changes = core.describe_change(old, new)
            if changes:
                db.event(con, "pr.change", {"pr": url, "changes": changes})
                log(f"{slug}#{pr['number']}: {', '.join(changes)}")
            active = con.execute("SELECT 1 FROM jobs WHERE pr_url=? AND status IN "
                                 "('queued','claimed','delivered','waiting_user')", (url,)).fetchone()
            drafts = con.execute("SELECT COUNT(*) FROM outbox WHERE pr_url=? AND status='pending'",
                                 (url,)).fetchone()[0]
            action, note, seen = rules.own_pr_action(pr, row, me, cfg, bool(active), drafts, ignore)
            if seen is not None:
                con.execute("UPDATE prs SET reviews_seen=?, comments_seen=?, bots_seen=? WHERE url=?",
                            (seen[0], seen[1], seen[2], url))
            if action in ("feedback", "feedback-bots"):
                if db.enqueue(con, url, "feedback", rules.PRIO["feedback"], note, pr.get("headRefOid")):
                    col = "feedback_rounds" if action == "feedback" else "bot_rounds"
                    con.execute(f"UPDATE prs SET {col}={col}+1 WHERE url=?", (url,))
                    log(f"queued feedback for {slug}#{pr['number']}: {note}")
            elif action in ("merge", "merge-check") and cfg.get("merge") == "never":
                pass   # repo rule merge=never: pr-pulse never starts a merge here
            elif action in ("merge", "merge-check"):
                if cfg.get("merge") == "ask" and action == "merge":
                    note = f"{MERGE_ASK}: {note}"
                if db.enqueue(con, url, action, rules.PRIO[action], note, pr.get("headRefOid"),
                              once_per_head=True):
                    log(f"queued {action} for {slug}#{pr['number']}: {note}")
            elif action == "ask":
                con.execute("UPDATE prs SET hold=1 WHERE url=?", (url,))
                db.event(con, "pr.ask", {"pr": url, "why": note})
                dispatch.notify(f"{slug}#{pr['number']}: {note}")
        for row in con.execute("SELECT url FROM prs WHERE slug=? AND kind='own' AND state='OPEN'",
                               (slug,)).fetchall():
            if row["url"] not in open_urls:
                con.execute("UPDATE prs SET state='CLOSED_OR_MERGED', updated_at=? WHERE url=?",
                            (time.time(), row["url"]))
                db.event(con, "pr.closed", {"pr": row["url"]})


# ---- reviews for others ---------------------------------------------------------------

def queue_review(con, me, mapped, url, action, note, prio, pr=None, same_head_ok=False):
    """Check a teammate's PR live and queue a review job. Returns '' when queued, else why not.

    *pr* skips the live read when the caller just made it. *same_head_ok* queues a re-review
    even when the user already reviewed this head: GitHub's "Re-request review" asks for
    another look at the same commits (the author may have only replied), and GitHub drops the
    request once the user reviews, so it cannot loop.
    """
    slug, n = pr_ref(url)
    if con.execute("SELECT 1 FROM jobs WHERE pr_url=? AND action IN ('review','re-review') "
                   "AND status IN ('queued','claimed','delivered','waiting_user')", (url,)).fetchone():
        return "a review of it is already running"
    pr = pr or view_pr(url)
    if not pr:
        return "gh failed"
    why = rules.review_skip_reason(pr, me, mapped, slug)
    if action == "re-review" and why == "already approved":
        why = ""   # a re-review request after I approved is still a request
    if action == "re-review" and same_head_ok and why == "already reviewed at head":
        why = ""
    if why:
        return why
    core.upsert_pr(con, slug, pr, "review")
    if action == "re-review":
        since = rules.last_reviewed_sha(pr, me)
        note = f"{note}; the user last reviewed at {since[:9] or '(never)'}, head {pr['headRefOid'][:9]}"
    jid = db.enqueue(con, url, action, prio, note, pr.get("headRefOid"), once_per_head=True)
    return "" if jid else "already queued or done at this head"


def review_requested(con, me, mapped):
    out = core.run(["gh", "search", "prs", "user-review-requested:@me", "--state", "open",
                    "--json", "url", "--limit", "50"], timeout=45)
    try:
        items = json.loads(out) if out else []
    except ValueError:
        items = []
    for it in items:
        url = it.get("url") or ""
        slug, _ = pr_ref(url)
        if slug not in mapped:
            continue
        if con.execute("SELECT 1 FROM jobs WHERE pr_url=? AND action IN ('review','re-review') "
                       "AND status IN ('queued','claimed','delivered','waiting_user')", (url,)).fetchone():
            continue
        pr = view_pr(url)
        if not pr:
            continue
        if rules.last_reviewed_sha(pr, me):
            # Requested again after the user reviewed: GitHub's "Re-request review".
            why = queue_review(con, me, mapped, url, "re-review", "GitHub re-requested your review",
                               rules.PRIO["re-review"], pr=pr, same_head_ok=True)
            kind = "re-review (re-requested)"
        else:
            why = queue_review(con, me, mapped, url, "review", "GitHub requested your review",
                               rules.PRIO["review-requested"], pr=pr)
            kind = "review (requested)"
        if not why:
            log(f"queued {kind} for {url}")


def pushed_since_changes(con, cfg, me, mapped, now=None):
    """Re-review a PR whose author pushed and replied after the user's standing
    CHANGES_REQUESTED review (a push alone, such as a rebase, is not enough).

    The author may never press "Re-request review" or tag the user in Slack. Runs every
    ``rereview_poll_seconds``, not every tick: it reads each candidate PR live.
    """
    now = time.time() if now is None else now
    last = float(db.get_setting(con, "pushed_since_changes_at", "0") or 0)
    if now - last < int(cfg.get("rereview_poll_seconds", 300)):
        return
    db.set_setting(con, "pushed_since_changes_at", str(now))
    out = core.run(["gh", "search", "prs", "reviewed-by:@me", "review:changes_requested",
                    "--state", "open", "--json", "url", "--limit", "50"], timeout=45)
    try:
        items = json.loads(out) if out else []
    except ValueError:
        items = []
    for it in items:
        url = it.get("url") or ""
        slug, _ = pr_ref(url)
        if slug not in mapped:
            continue
        if con.execute("SELECT 1 FROM jobs WHERE pr_url=? AND action IN ('review','re-review') "
                       "AND status IN ('queued','claimed','delivered','waiting_user')", (url,)).fetchone():
            continue
        pr = view_pr(url)
        if not pr:
            continue
        since = rules.pushed_after_changes_requested(pr, me)
        if not since:
            continue
        why = queue_review(con, me, mapped, url, "re-review",
                           f"new commits and a reply after your requested changes at {since[:9]}",
                           rules.PRIO["re-review"], pr=pr)
        if not why:
            log(f"queued re-review (pushed after changes requested) for {url}")


# ---- Slack ----------------------------------------------------------------------------

def slack_error_hint(e):
    """A short reason with what to do, for a notification."""
    msg = str(e)
    if "not_in_channel" in msg:
        return "you are not in that channel: join it in Slack"
    if any(k in msg for k in ("invalid_auth", "token_revoked", "account_inactive", "is not set")):
        return f"{msg}: run /pr-pulse:init slack"
    return msg


def user_token_ready(con, cfg):
    """post_as "user": is the user token there? If not, notify once a day and post nothing:
    falling back to the bot would post under the wrong name."""
    if slack.poster(cfg) != "user" or slack.token("user"):
        return True
    last = float(db.get_setting(con, "user_token_missing_told", 0) or 0)
    if time.time() - last > 86400:
        db.set_setting(con, "user_token_missing_told", time.time())
        dispatch.notify("pr-pulse posts as you (post_as user), but your Slack user token is missing. "
                        "Nothing is posted until you run /pr-pulse:init slack.")
    log("post_as user without PR_PULSE_SLACK_USER_TOKEN: posts held")
    return False


def slack_ingest(con, cfg, me, mapped):
    channels = cfg.get("watch_channels") or []
    if not channels or not slack.token():
        return
    my_sid = cfg.get("slack_user_id") or ""
    bot_user = db.get_setting(con, "slack_bot_user")
    bot_id = db.get_setting(con, "slack_bot_id", "")
    if not bot_user:
        try:
            bot_user, bot_id = slack.whoami()
        except slack.SlackError as e:
            log(f"slack auth failed: {e}")
            return
        db.set_setting(con, "slack_bot_user", bot_user)
        db.set_setting(con, "slack_bot_id", bot_id)
    for ch in channels:
        key = f"slack_oldest:{ch}"
        oldest = db.get_setting(con, key)
        if oldest is None:
            # First run: start from now, never flood the queue with the channel's history.
            db.set_setting(con, key, f"{time.time():.6f}")
            continue
        try:
            msgs = slack.history(ch, oldest)
        except slack.SlackError as e:
            slack_trouble(con, ch, e)
            continue
        slack_ok(con, ch)
        for m in msgs:
            ts = m.get("ts") or ""
            if not ts:
                continue
            seen = con.execute("INSERT OR IGNORE INTO slack_seen(channel, ts) VALUES(?, ?)", (ch, ts))
            db.set_setting(con, key, ts)
            if seen.rowcount == 0:
                continue
            kind, payload = rules.classify_slack(m, my_sid, bot_user, bot_id)
            if kind == "ignore":
                continue
            for url in payload:
                if kind == "pool":
                    con.execute("INSERT OR IGNORE INTO review_pool(pr_url, channel, ts, sharer, shared_at) "
                                "VALUES(?,?,?,?,?)", (url, ch, ts, m.get("user"), float(ts)))
                    log(f"pool + {url}")
                else:
                    slack_rereview(con, me, mapped, url, ch, ts, m.get("user"), "tagged for a re-review in Slack",
                                   tag=(ts, m.get("user")))
        try:
            slack_threads(con, me, mapped, ch, my_sid, bot_user, bot_id)
        except slack.SlackError as e:
            slack_trouble(con, ch, e)


def slack_rereview(con, me, mapped, url, ch, ts, user, why_text, tag=None):
    """A tag of me on a PR (in the channel or in its thread): queue a re-review, unless it's mine.
    tag = (ts, user) of the message that tagged me: with verdict_style "emoji" it gets ♻️ when its
    author is the PR's author."""
    if con.execute("SELECT 1 FROM prs WHERE url=? AND kind='own'", (url,)).fetchone():
        db.event(con, "slack.tag_on_own_pr", {"pr": url, "ts": ts})
        return
    # Keep the share thread so the verdict lands next to the request.
    con.execute("INSERT INTO review_pool(pr_url, channel, ts, sharer, shared_at, status) "
                "VALUES(?,?,?,?,?, 'pulled') ON CONFLICT(pr_url) DO UPDATE SET "
                "status='pulled'", (url, ch, ts, user, float(ts)))
    why = queue_review(con, me, mapped, url, "re-review", why_text, rules.PRIO["re-review"])
    log(f"re-review {url}: {'queued' if not why else why}")
    if not why and tag:
        mark_rereview(con, db.load_config(), url, ch, tag[0], tag[1])


def is_pr_author(con, cfg, url, slack_user):
    """Whether a Slack user is the PR's author: the one who shared it, or the author's account."""
    if not slack_user:
        return False
    share = con.execute("SELECT sharer FROM review_pool WHERE pr_url=?", (url,)).fetchone()
    pr = con.execute("SELECT author FROM prs WHERE url=?", (url,)).fetchone()
    author_sid = resolve_slack_author(con, cfg, pr["author"] if pr else "", share["sharer"] if share else "")
    return slack_user == author_sid or (bool(share) and slack_user == share["sharer"] and not author_sid)


def mark_rereview(con, cfg, url, ch, ts, user):
    """verdict_style "emoji": ♻️ on the author's own re-review request, until the verdict replaces it.
    Nothing on anyone else's message."""
    if cfg.get("verdict_style") != "emoji" or not is_pr_author(con, cfg, url, user):
        return
    as_ = slack.poster(cfg)
    if not user_token_ready(con, cfg):
        return
    try:
        added = slack.react(ch, ts, rules.REREVIEW_EMOJI, as_=as_)
    except slack.SlackError as e:
        db.event(con, "reaction.failed", {"pr": url, "error": str(e)})
        return
    # As the user, one already there was put by hand: never ours to take off. The shared bot's
    # "already there" is still the bot's own (another reviewer's pr-pulse put it), as before.
    if added or as_ == "bot":
        con.execute("INSERT OR REPLACE INTO reactions(pr_url, channel, ts, kind, emoji, at, posted_as) "
                    "VALUES(?,?,?, 'rereview', ?, ?, ?)", (url, ch, ts, rules.REREVIEW_EMOJI, time.time(), as_))


def set_reaction(con, url, ch, ts, kind, emoji, as_="bot"):
    """Put emoji on a message, replacing only the reaction pr-pulse itself added there before.
    A reaction is removed by the identity that added it (bot or user). As the user, one that was
    already there (the person put it by hand) is left alone and never recorded as ours."""
    old = con.execute("SELECT emoji, posted_as FROM reactions WHERE channel=? AND ts=?", (ch, ts)).fetchone()
    if old and old["emoji"] == emoji and (old["posted_as"] or "bot") == as_:
        return
    added = slack.react(ch, ts, emoji, as_=as_)
    if old:
        slack.unreact(ch, ts, old["emoji"], as_=old["posted_as"] or "bot")
    if added or as_ == "bot":   # the shared bot's "already there" is still the bot's, as before
        con.execute("INSERT OR REPLACE INTO reactions(pr_url, channel, ts, kind, emoji, at, posted_as) "
                    "VALUES(?,?,?,?,?,?,?)", (url, ch, ts, kind, emoji, time.time(), as_))
    else:
        con.execute("DELETE FROM reactions WHERE channel=? AND ts=?", (ch, ts))


def current_share(con, cfg, url, share):
    """The share row, or the PR's reposted share message when the stored one was deleted, or None.
    A reply to a deleted message lands at the channel root, so a stale ts must never be posted to."""
    try:
        if slack.message_exists(share["channel"], share["ts"]):
            return share
    except slack.SlackError as e:
        # Could not check (network, rate limit): keep the stored message, as before this check.
        db.event(con, "verdict.share_unchecked", {"pr": url, "error": str(e)})
        return share
    found = slack.find_share(cfg.get("watch_channels") or [cfg.get("verdict_channel")],
                             url, skip_users=(db.get_setting(con, "slack_bot_user", ""), cfg.get("slack_user_id") or ""))
    if not found or (found[0], found[1]) == (share["channel"], share["ts"]):
        db.event(con, "verdict.share_deleted", {"pr": url, "ts": share["ts"]})
        log(f"share message for {url} was deleted and no repost was found")
        return None
    con.execute("UPDATE review_pool SET channel=?, ts=?, sharer=?, shared_at=? WHERE pr_url=?",
                (found[0], found[1], found[2], float(found[1]), url))
    db.event(con, "verdict.share_moved", {"pr": url, "from": share["ts"], "to": found[1]})
    log(f"share message for {url} was reposted: {share['ts']} -> {found[1]}")
    return con.execute("SELECT channel, ts, sharer FROM review_pool WHERE pr_url=?", (url,)).fetchone()


def react_verdict(con, url, share, verdict, as_="bot"):
    """verdict_style "emoji": the verdict's emoji on the author's share message and on any of their
    re-review requests still showing ♻️. Raises SlackError (e.g. missing reactions:write)."""
    emoji = rules.verdict_emoji(verdict)
    set_reaction(con, url, share["channel"], share["ts"], "share", emoji, as_)
    for r in con.execute("SELECT channel, ts FROM reactions WHERE pr_url=? AND kind='rereview' AND emoji=?",
                         (url, rules.REREVIEW_EMOJI)).fetchall():
        set_reaction(con, url, r["channel"], r["ts"], "rereview", emoji, as_)


STALE_REREVIEW_HOURS = 24


def clear_stale_rereviews(con):
    """A ♻️ must never stick: take it off when the PR closed, the re-review failed, or a day passed
    with no verdict."""
    for r in con.execute("SELECT x.pr_url, x.channel, x.ts, x.at, x.posted_as, p.state FROM reactions x LEFT JOIN prs p "
                         "ON p.url=x.pr_url WHERE x.kind='rereview' AND x.emoji=?", (rules.REREVIEW_EMOJI,)).fetchall():
        job = con.execute("SELECT status FROM jobs WHERE pr_url=? AND action IN ('review','re-review') "
                          "ORDER BY id DESC LIMIT 1", (r["pr_url"],)).fetchone()
        closed = r["state"] not in (None, "OPEN")
        failed = bool(job) and job["status"] == "failed"
        old = time.time() - r["at"] > STALE_REREVIEW_HOURS * 3600
        if not (closed or failed or old):
            continue
        try:
            slack.unreact(r["channel"], r["ts"], rules.REREVIEW_EMOJI, as_=r["posted_as"] or "bot")
        except slack.SlackError as e:
            db.event(con, "reaction.failed", {"pr": r["pr_url"], "error": str(e)})
            continue
        con.execute("DELETE FROM reactions WHERE channel=? AND ts=?", (r["channel"], r["ts"]))


THREAD_DAYS = 7          # threads whose parent is older than this are no longer watched
THREAD_CALLS = 20        # at most this many thread reads per channel per tick (Slack rate limits)


def slack_threads(con, me, mapped, ch, my_sid, bot_user, bot_id):
    """Replies inside threads. Channel history never contains them, so an author who answers a
    review in its thread ("@me fixed both, please re-review") was never heard. One history call
    finds the threads that moved since we last looked (`latest_reply`); only those are read."""
    now = time.time()
    start_key = f"slack_threads_from:{ch}"
    start = db.get_setting(con, start_key)
    if start is None:
        # First run: only replies from now on, never a flood of old tags.
        db.set_setting(con, start_key, f"{now:.6f}")
        return
    since = f"{max(float(start), now - THREAD_DAYS * 86400):.6f}"
    # Forget threads that left the window.
    con.execute("DELETE FROM settings WHERE key LIKE ? AND CAST(substr(key, ?) AS REAL) < ?",
                (f"slack_thread:{ch}:%", len(f"slack_thread:{ch}:") + 1, now - THREAD_DAYS * 86400))
    calls = 0
    for parent in slack.recent_threads(ch, f"{now - THREAD_DAYS * 86400:.6f}"):
        pts, latest = parent.get("ts") or "", parent.get("latest_reply") or ""
        if not pts or not latest:
            continue
        key = f"slack_thread:{ch}:{pts}"
        last = db.get_setting(con, key) or since
        if float(latest) <= float(last):
            continue                      # no new reply since we last read this thread
        if calls >= THREAD_CALLS:
            break                         # the rest waits for the next tick
        calls += 1
        for r in slack.replies(ch, pts, last):
            rts = r.get("ts") or ""
            if not rts:
                continue
            db.set_setting(con, key, rts)
            if con.execute("INSERT OR IGNORE INTO slack_seen(channel, ts) VALUES(?, ?)", (ch, rts)).rowcount == 0:
                continue
            kind, payload = rules.classify_reply(r, parent, my_sid, bot_user, bot_id)
            if kind != "re-review":
                continue
            for url in payload:
                slack_rereview(con, me, mapped, url, ch, pts, parent.get("user"),
                               "tagged for a re-review in a Slack thread", tag=(rts, r.get("user")))
        if float(db.get_setting(con, key) or 0) < float(latest):
            db.set_setting(con, key, latest)


SLACK_FIXES = {
    "channel_not_found": "the bot isn't in that channel (a reinstall removes it): send /invite @prpulse there",
    "not_in_channel": "the bot isn't in that channel: send /invite @prpulse there",
    "invalid_auth": "Slack rejected the token: run pr-pulse secret set bot-token --from-clipboard",
    "token_revoked": "the token was revoked: run pr-pulse secret set bot-token --from-clipboard",
    "missing_scope": "the app lacks a reading permission: run /pr-pulse:init slack",
}


def slack_trouble(con, ch, err):
    """Log every failure; tell the user once per channel and kind of failure, not every tick."""
    log(f"slack {ch} failed: {err}")
    code = str(err).rsplit(": ", 1)[-1]
    fix = SLACK_FIXES.get(code)
    if not fix or db.get_setting(con, f"slack_err:{ch}") == code:
        return                            # a network blip or an error already reported
    db.set_setting(con, f"slack_err:{ch}", code)
    db.event(con, "slack.read_failed", {"channel": ch, "error": code})
    dispatch.notify(f"pr-pulse can't read Slack channel {ch} ({code}): {fix}")


def slack_ok(con, ch):
    if db.get_setting(con, f"slack_err:{ch}"):
        con.execute("DELETE FROM settings WHERE key=?", (f"slack_err:{ch}",))
        log(f"slack {ch} readable again")


def pool_pull(con, cfg, me, mapped):
    """When slots are free, move at most pool_pull shared PRs from the pool into review jobs."""
    import autoreview
    if not autoreview.is_on(con):
        return   # held reviews take no slot, so pulling now would drain the pool into the queue
    import reporules
    import focus
    queued = con.execute("SELECT j.pr_url, p.slug FROM jobs j LEFT JOIN prs p ON p.url=j.pr_url "
                         "WHERE j.status='queued'").fetchall()
    # a job waiting for its paired PR session holds no slot, so it must not starve the pool
    waiting = sum(1 for j in queued if j["slug"] and focus.pairs_for(con, j["slug"], j["pr_url"]))
    free = int(cfg.get("pool_size", 3)) - db.running_count(con) - (len(queued) - waiting)
    if free <= 0:
        return
    want = min(free, int(cfg.get("pool_pull", 1)))
    now = time.time()
    for row in con.execute("SELECT * FROM review_pool WHERE status='pool' AND "
                           "(last_check IS NULL OR last_check < ?) ORDER BY shared_at",
                           (now - 1800,)).fetchall():
        if want <= 0:
            break
        m = rules.PR_URL_RE.search(row["pr_url"])
        if m and reporules.for_repo(cfg, f"{m.group(1)}/{m.group(2)}").get("auto_review") == "off":
            continue   # repo rule auto_review=off: stays in the pool
        why = queue_review(con, me, mapped, row["pr_url"], "review", "shared in Slack, untagged",
                           rules.PRIO["pool"])
        if not why:
            con.execute("UPDATE review_pool SET status='pulled', last_check=?, skip_reason=NULL "
                        "WHERE pr_url=?", (now, row["pr_url"]))
            log(f"pulled {row['pr_url']} from the pool")
            want -= 1
        elif why in ("closed or merged", "own PR", "already reviewed at head"):
            con.execute("UPDATE review_pool SET status='gone', last_check=?, skip_reason=? "
                        "WHERE pr_url=?", (now, why, row["pr_url"]))
        else:   # draft, approved, unmapped, gh hiccup: look again later
            con.execute("UPDATE review_pool SET last_check=?, skip_reason=? WHERE pr_url=?",
                        (now, why, row["pr_url"]))


def resolve_slack_author(con, cfg, login, sharer):
    m = (cfg.get("github_to_slack") or {}).get(login)
    if m:
        return m
    user = core.run(["gh", "api", f"users/{login}", "-q", "[.email // \"\", .name // \"\"] | @tsv"]) or ""
    email, _, name = user.strip().partition("\t")
    if email:
        sid = slack.lookup_by_email(email)
        if sid:
            return sid
    if sharer and rules.sharer_matches(login, name, slack.profile(sharer)):
        return sharer
    return ""


def repo_rules_problems(con, cfg):
    """A bad repo_rules entry is logged every tick and notified once per distinct problem."""
    import hashlib
    import reporules
    _, errors = reporules.validate(cfg.get("repo_rules"))
    for e in errors:
        log(e)
        key = "repo_rules_told:" + hashlib.sha1(e.encode()).hexdigest()[:12]
        if not db.get_setting(con, key):
            db.set_setting(con, key, time.time())
            dispatch.notify(f"pr-pulse: {e}. Fix it with /pr-pulse:rules.")


def post_announcements(con, cfg):
    """Post the announcements sessions saved, apply edits, nudge PRs left unannounced."""
    # post_as user without a user token: each post fails loudly ("…USER_TOKEN is not set", retry
    # from /pr-pulse:inbox) and is never sent as the bot. The pass still runs, so the daemon stays
    # "fresh" for `pr-pulse announce` and the unannounced nudges keep working.
    as_ = slack.poster(cfg)
    out = announce.run(con, cfg, channel=cfg.get("announce_channel") or "", token_ok=bool(slack.token()),
                       webhook=os.environ.get("PR_PULSE_SLACK_WEBHOOK_URL", ""), who=core.my_name(cfg),
                       label=os.environ.get("PR_PULSE_CHANNEL_LABEL", "#pr-review"), notify=dispatch.notify,
                       as_=as_)
    if any(out.values()):
        log(f"announcements: {out}")


def post_verdicts(con, cfg, me):
    """After a review job finished, post one verdict per new GitHub review of mine."""
    if not slack.token():   # finding the share thread reads the channel: always the bot
        return
    as_ = slack.poster(cfg)
    if as_ == "user" and not user_token_ready(con, cfg):
        return   # before any verdict is recorded, so none is lost while the token is missing
    if cfg.get("verdict_style") == "emoji":
        clear_stale_rereviews(con)
    for j in con.execute("SELECT pr_url, MIN(created_at) AS since FROM jobs WHERE action IN "
                         "('review','re-review') AND status='done' AND updated_at > ? GROUP BY pr_url",
                         (time.time() - 86400,)).fetchall():
        url = j["pr_url"]
        slug, n = pr_ref(url)
        since = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(j["since"]))
        # Only reviews submitted after the job started: an older review is never announced.
        out = core.run(["gh", "api", f"repos/{slug}/pulls/{n}/reviews", "-q",
                        f'[.[] | select(.user.login=="{me}" and .submitted_at >= "{since}") | {{id, state}}]'])
        try:
            reviews = json.loads(out) if out else []
        except ValueError:
            continue
        if not reviews:
            continue
        last = reviews[-1]   # one verdict for the newest review of this round
        rid = str(last["id"])
        if con.execute("SELECT 1 FROM verdicts WHERE pr_url=? AND review_id=?", (url, rid)).fetchone():
            continue
        inline = core.run(["gh", "api", f"repos/{slug}/pulls/{n}/reviews/{rid}/comments", "-q", "length"])
        verdict = rules.verdict_for(last["state"], int((inline or "0").strip() or 0))
        con.execute("INSERT INTO verdicts(pr_url, review_id, verdict) VALUES(?,?,?)", (url, rid, verdict))
        if not verdict:
            continue
        pr = con.execute("SELECT author FROM prs WHERE url=?", (url,)).fetchone()
        share = con.execute("SELECT channel, ts, sharer FROM review_pool WHERE pr_url=?", (url,)).fetchone()
        if not share:
            # Reviews from GitHub requests have no pool row: find the PR's share message.
            found = slack.find_share(cfg.get("watch_channels") or [cfg.get("verdict_channel")],
                                     url, skip_users=(db.get_setting(con, "slack_bot_user", ""), cfg.get("slack_user_id") or ""))
            if found:
                con.execute("INSERT OR IGNORE INTO review_pool(pr_url, channel, ts, sharer, shared_at, status) "
                            "VALUES(?,?,?,?,?, 'gone')", (url, found[0], found[1], found[2], float(found[1])))
                share = con.execute("SELECT channel, ts, sharer FROM review_pool WHERE pr_url=?", (url,)).fetchone()
        if share:
            share = current_share(con, cfg, url, share)
        if not share:
            # Only ever a reply under the PR's own message; never a stray top-level post.
            db.event(con, "verdict.no_thread", {"pr": url, "verdict": verdict})
            log(f"verdict for {url} not posted: no share message for it in the watched channels")
            continue
        author_sid = resolve_slack_author(con, cfg, pr["author"] if pr else "", share["sharer"])
        if not author_sid:
            db.event(con, "verdict.no_author_tag", {"pr": url})
        lines = con.execute("SELECT o.lines FROM outbox o JOIN jobs j ON j.id=o.job_id WHERE o.pr_url=? "
                            "AND o.kind='review' AND o.status='posted' AND j.action IN ('review','re-review') "
                            "ORDER BY o.posted_at DESC LIMIT 1", (url,)).fetchone()
        text = rules.verdict_text("" if as_ == "user" else core.my_name(cfg), verdict, author_sid, url, f"{slug}#{n}",
                                  lines["lines"] if lines else "")
        channel, thread = share["channel"], share["ts"]
        if cfg.get("verdict_style") == "emoji":
            try:
                react_verdict(con, url, share, verdict, as_)
                con.execute("UPDATE verdicts SET posted_at=? WHERE pr_url=? AND review_id=?",
                            (time.time(), url, rid))
                log(f"verdict reacted for {url}: {verdict}")
                continue
            except slack.SlackError as e:
                # Never lose a verdict: without reactions:write (or any failure) reply as before.
                db.event(con, "reaction.failed", {"pr": url, "error": str(e)})
                log(f"verdict emoji for {url} failed ({e}); replying instead")
        try:
            slack.post(channel, text, thread, as_=as_)
            con.execute("UPDATE verdicts SET posted_at=? WHERE pr_url=? AND review_id=?",
                        (time.time(), url, rid))
            log(f"verdict posted for {url}: {verdict}")
        except slack.SlackError as e:
            db.event(con, "verdict.failed", {"pr": url, "error": str(e)})
            dispatch.notify(f"pr-pulse: your {verdict} verdict on {slug}#{n} was not posted in Slack "
                            f"({slack_error_hint(e)}).")


# ---- drafts ---------------------------------------------------------------------------

def show_questions(con, dry=False):
    """One question on screen at a time, in a separate asker process."""
    questions.expire_finished(con)
    # An asker that died leaves a question 'showing': free it after 20 minutes.
    con.execute("UPDATE questions SET status='pending' WHERE status='showing' AND shown_at < ?",
                (time.time() - 1200,))
    q = questions.next_to_show(con)
    if not q or dry or not questions.claim_for_showing(con, q["id"]):
        return
    asker = Path(__file__).resolve().parent / "pr-pulse-asker.py"
    subprocess.Popen([sys.executable, str(asker), str(q["id"])], stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
    log(f"asking the user question {q['id']} (job {q['job_id']})")


def notify_drafts(con):
    """One alert for drafts that have no notification of their own (e.g. put off with Later)."""
    n = con.execute("SELECT COUNT(*) FROM outbox o WHERE o.status='pending' AND NOT EXISTS "
                    "(SELECT 1 FROM questions q WHERE q.draft_id=o.id AND q.status IN ('pending','showing'))"
                    ).fetchone()[0]
    last = int(db.get_setting(con, "drafts_notified", "0"))
    if n > last:
        dispatch.notify(f"{n} draft(s) waiting for your lines: run /pr-pulse:inbox")
    db.set_setting(con, "drafts_notified", n)


# ---- tick -----------------------------------------------------------------------------

def tick(con, cfg, dry=False):
    sessions = core.list_sessions()
    if sessions is None:
        log("claude agents --json failed; sessions left as they were")
    else:
        core.sync_sessions(con, sessions)
        dispatch.bind_worker_sids(con)
        if not dry:
            waiting.watch(con, sessions, cfg)   # any session waiting for the user, not only jobs
    if not dry:
        current.stale_sessions(con, notify=dispatch.notify)
        repo_rules_problems(con, cfg)
        post_announcements(con, cfg)   # needs Slack, not gh
    me = my_login(con)
    if not me:
        log("gh is not logged in; nothing to do")
        return
    mapped = {r["slug"] for r in con.execute("SELECT slug FROM repos").fetchall()}
    own_prs(con, cfg, me)
    if cfg.get("review_requested", True):
        review_requested(con, me, mapped)
    if cfg.get("rereview_on_push", True):
        pushed_since_changes(con, cfg, me, mapped)
    slack_ingest(con, cfg, me, mapped)
    pool_pull(con, cfg, me, mapped)
    if not dry:
        post_verdicts(con, cfg, me)
    notify_drafts(con)
    show_questions(con, dry)
    if not dry:
        pruned = db.prune_if_due(con, cfg)
        if pruned and any(pruned.values()):
            log("pruned history older than %s days: %s" % (
                cfg.get("retention_days", 30), {k: v for k, v in pruned.items() if v}))
    db.set_setting(con, "last_tick", time.time())
    if db.get_setting(con, "paused", "0") == "1":
        return
    if not dry:
        dispatch.recover_stale(con, cfg)
        import workers
        gone = workers.reap_idle(con, cfg)
        if gone:
            log(f"stopped {len(gone)} finished worker(s): {', '.join(gone)}")
    n = dispatch.dispatch(con, cfg, dry)
    if n:
        log(f"handed out {n} job(s)")
    if not dry:
        dispatch.cleanup_worktrees(con)


def self_update(start_fp, argv, verify=False, execv=os.execv, notify=None):
    """Keep the service on the installed plugin by content, the same version or not: copy it
    over the service's copy when they differ, then restart on the new code. verify re-reads the
    copy instead of trusting its stamp (every 10th tick), so a damaged copy heals. A failure
    keeps the old code running and tells the user. Returns 'restart', 'same' or 'failed'."""
    notify = notify or dispatch.notify
    try:
        v = current.ensure_app(verify=verify)
        if v:
            log(f"installed pr-pulse changed; service copy updated to {v}")
        if current.app_fingerprint() != start_fp:
            log("restarting on the updated copy")
            execv(sys.executable, [sys.executable, str(current.APP / "scripts" / "pr-pulsed.py")] + list(argv))
            return "restart"
        return "same"
    except Exception as e:   # noqa: BLE001 - keep running the old code rather than stop
        log(f"self-update failed, still running the old copy: {e!r}")
        notify(f"pr-pulse could not update its background service: {str(e)[:120]}")
        return "failed"


def main(argv):
    load_env_file()
    once = "--once" in argv
    dry = "--dry-run" in argv or os.environ.get("PR_PULSE_DRY_RUN") == "1"
    cfg = db.load_config()
    con = db.connect()
    log(f"pr-pulsed started (once={once}, dry_run={dry}, db={db.DB_PATH})")
    me_file = Path(__file__).resolve()
    start_fp = current.app_fingerprint() if me_file.parent.parent == current.APP.resolve() else ""
    if start_fp:
        db.set_setting(con, "daemon_fingerprint", start_fp)
    ticks = 0
    while True:
        if db.get_setting(con, "stopped", "0") == "1" and not once:
            log("pr-pulse is stopped (pr-pulse start brings it back); exiting")
            return 0
        try:
            tick(con, cfg, dry)
        except Exception as e:  # a bad tick must never kill the daemon
            log(f"tick failed: {e!r}")
            try:
                db.event(con, "tick.error", repr(e))
            except Exception:
                pass
        if once:
            return 0
        if start_fp and not dry:
            ticks += 1
            self_update(start_fp, argv, verify=ticks % 10 == 0)
        time.sleep(max(15, int(cfg["tick_seconds"])))
        cfg = db.load_config()   # pick up config edits without a restart


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
