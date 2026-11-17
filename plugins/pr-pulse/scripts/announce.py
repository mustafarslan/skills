"""PR announcements, posted by the daemon.

The PostToolUse hook records every PR a pr-pulse session opens (state 'open'). The session
writes the announcement text and saves it locally with `pr-pulse announce <url>` (state
'queued'); the daemon posts it on its next check. A session never writes to Slack itself, so
Claude Code's auto mode has no outside write to block, and an announcement can no longer be
dropped silently: a PR still 'open' after `announce_nudge_minutes` gets one notification.

Saving text for a PR that is already posted queues an edit of that Slack message (bot token
mode only; a webhook post can't be edited).
"""
import json
import re
import time
import urllib.request

import db

PR_URL = re.compile(r"^https://github\.com/([^/\s]+)/([^/\s]+)/pull/(\d+)$")
STATES = ("open", "queued", "posted", "dropped", "failed")
PASS_KEY = "announce_pass_at"   # stamped by the daemon on every pass
FRESH_SECONDS = 300


def ref(url):
    m = PR_URL.match(url or "")
    return f"{m.group(2)}#{m.group(3)}" if m else url


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render(text, url, title, who):
    """The same message shape post.sh has always used."""
    t = esc((title or "").replace("|", "/"))
    link = f"<{url}|{ref(url)}{': ' + t if t else ''}>"
    return esc(text.rstrip()) + "\n" + link + (f" · {esc(who)}" if who else "")


def already_announced(con, url):
    return bool(con.execute("SELECT 1 FROM announced WHERE url=?", (url,)).fetchone())


def record_open(con, url, sid="", title=""):
    """The hook saw this PR opened. Never re-opens one that was posted or dropped."""
    if not PR_URL.match(url) or already_announced(con, url):
        return False
    cur = con.execute("INSERT OR IGNORE INTO announcements(url, opened_at, sid, title, state, updated_at) "
                      "VALUES(?,?,?,?, 'open', ?)", (url, time.time(), sid or "", title or "", time.time()))
    return cur.rowcount == 1


def save(con, url, text, title=""):
    """Queue the text: a post, or an edit when this PR's message is already up.
    Returns 'queued', 'edit-queued', 'cannot-edit' or 'bad-url'."""
    if not PR_URL.match(url):
        return "bad-url"
    now = time.time()
    row = con.execute("SELECT * FROM announcements WHERE url=?", (url,)).fetchone()
    if row and row["state"] == "posted" or (not row and already_announced(con, url)):
        if not row or not row["ts"]:
            return "cannot-edit"   # posted by post.sh or a webhook: no message id to edit
        con.execute("UPDATE announcements SET edit_text=?, error=NULL, updated_at=? WHERE url=?",
                    (text, now, url))
        return "edit-queued"
    con.execute("INSERT INTO announcements(url, opened_at, title, text, state, updated_at) "
                "VALUES(?,?,?,?, 'queued', ?) ON CONFLICT(url) DO UPDATE SET text=excluded.text, "
                "state='queued', error=NULL, updated_at=excluded.updated_at, "
                "title=CASE WHEN excluded.title<>'' THEN excluded.title ELSE announcements.title END",
                (url, now, title or "", text, now))
    return "queued"


def daemon_fresh(con, now=None):
    """Is a daemon that knows how to post announcements running? An old daemon never stamps."""
    try:
        at = float(db.get_setting(con, PASS_KEY, "0") or 0)
    except ValueError:
        at = 0
    return db.get_setting(con, "stopped", "0") != "1" and (now or time.time()) - at < FRESH_SECONDS


def retry(con, url):
    """Queue a failed (or nudged) PR's saved text again, unchanged."""
    return con.execute("UPDATE announcements SET state='queued', error=NULL, updated_at=? WHERE url=? "
                       "AND state IN ('failed','open') AND COALESCE(text,'')<>''",
                       (time.time(), url)).rowcount == 1


def drop(con, url):
    return con.execute("UPDATE announcements SET state='dropped', updated_at=? WHERE url=? AND state "
                       "IN ('open','queued','failed')", (time.time(), url)).rowcount == 1


def waiting(con):
    """PRs opened with no announcement yet, whose post failed, or saved but still not posted."""
    return con.execute("SELECT * FROM announcements WHERE state IN ('open','failed') OR (state='queued' "
                       "AND updated_at < ?) ORDER BY opened_at", (time.time() - FRESH_SECONDS,)).fetchall()


def mark_posted(con, url, ts="", channel="", posted_as="bot"):
    """Called for every successful post (daemon or post.sh)."""
    now = time.time()
    con.execute("INSERT OR IGNORE INTO announced(url, at) VALUES(?, ?)",
                (url, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(now))))
    con.execute("UPDATE announcements SET state='posted', ts=COALESCE(NULLIF(?, ''), ts), "
                "channel=COALESCE(NULLIF(?, ''), channel), posted_as=?, error=NULL, updated_at=? WHERE url=?",
                (ts, channel, posted_as, now, url))
    # the hook's cached gh metadata for this PR (post.sh removes it the same way)
    try:
        (db.HOME / "pending" / (re.sub(r"[^A-Za-z0-9]", "_", url) + ".json")).unlink()
    except OSError:
        pass


# ---- the daemon side ---------------------------------------------------------------------

def _webhook_post(hook, text):
    body = json.dumps({"text": text, "unfurl_links": False, "unfurl_media": False}).encode()
    req = urllib.request.Request(hook, data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=10) as r:
        if r.status != 200:
            raise RuntimeError(f"webhook answered {r.status}")


def run(con, cfg, *, channel, token_ok, webhook, who, label="#pr-review", notify=None, slack=None,
        now=None, as_="bot"):
    """One daemon pass: post queued texts, apply queued edits, nudge PRs left unannounced.
    as_ "user" posts as the person (their user token) and never falls back to the bot or the
    webhook: a missing or refused user token fails the post loudly instead.
    Returns {"posted": n, "edited": n, "failed": n, "nudged": n}."""
    import slack as slack_mod
    slack = slack or slack_mod
    now = now or time.time()
    db.set_setting(con, PASS_KEY, now)
    out = {"posted": 0, "edited": 0, "failed": 0, "nudged": 0}
    if as_ == "user":
        token_ok, webhook = True, ""
    can_token = bool(token_ok and channel)
    for r in con.execute("SELECT * FROM announcements WHERE state='queued' ORDER BY updated_at").fetchall():
        if already_announced(con, r["url"]):   # posted another way meanwhile (post.sh)
            con.execute("UPDATE announcements SET state='posted', updated_at=? WHERE url=?", (now, r["url"]))
            continue
        # Posted as the person, the message is already theirs: no "· name" suffix.
        msg = render(r["text"] or "", r["url"], r["title"], "" if as_ == "user" else who)
        try:
            if can_token:
                ts = slack.post(channel, msg, as_=as_)
                mark_posted(con, r["url"], ts, channel, as_)
            elif webhook:
                _webhook_post(webhook, msg)
                mark_posted(con, r["url"])
            else:
                raise RuntimeError("Slack is not set up for announcements (run /pr-pulse:init)")
            out["posted"] += 1
            db.event(con, "announce.posted", {"pr": r["url"]})
        except Exception as e:   # noqa: BLE001 - any failure is recorded and shown, never retried blind
            con.execute("UPDATE announcements SET state='failed', error=?, updated_at=? WHERE url=?",
                        (str(e)[:300], now, r["url"]))
            out["failed"] += 1
            db.event(con, "announce.failed", {"pr": r["url"], "error": str(e)[:300]})
            if notify:
                notify(f"{ref(r['url'])} was not announced in {label}: {str(e)[:120]}. "
                       f"/pr-pulse:inbox to retry.")
    for r in con.execute("SELECT * FROM announcements WHERE state='posted' AND edit_text IS NOT NULL "
                         "AND ts IS NOT NULL").fetchall():
        # The edit keeps the message's own shape and identity: a bot post keeps its "· name"
        # suffix and is edited by the bot, even after post_as changed to user.
        mine = (r["posted_as"] or "bot") == "user"
        msg = render(r["edit_text"], r["url"], r["title"], "" if mine else who)
        try:
            slack.update(r["channel"] or channel, r["ts"], msg, as_="user" if mine else "bot")
            con.execute("UPDATE announcements SET text=edit_text, edit_text=NULL, error=NULL, updated_at=? "
                        "WHERE url=?", (now, r["url"]))
            out["edited"] += 1
            db.event(con, "announce.edited", {"pr": r["url"]})
        except Exception as e:   # noqa: BLE001
            con.execute("UPDATE announcements SET edit_text=NULL, error=?, updated_at=? WHERE url=?",
                        (f"edit failed: {str(e)[:280]}", now, r["url"]))
            out["failed"] += 1
            if notify:
                notify(f"The {ref(r['url'])} announcement was not edited: {str(e)[:120]}.")
    grace = float(cfg.get("announce_nudge_minutes", 10)) * 60
    for r in con.execute("SELECT * FROM announcements WHERE state='open' AND nudged_at IS NULL "
                         "AND opened_at < ?", (now - grace,)).fetchall():   # queued ones post above
        if already_announced(con, r["url"]):
            con.execute("UPDATE announcements SET state='posted', updated_at=? WHERE url=?", (now, r["url"]))
            continue
        con.execute("UPDATE announcements SET nudged_at=? WHERE url=?", (now, r["url"]))
        out["nudged"] += 1
        db.event(con, "announce.nudged", {"pr": r["url"]})
        if notify:
            notify(f"{ref(r['url'])} was opened but not announced in {label}. /pr-pulse:inbox to announce it.")
    return out
