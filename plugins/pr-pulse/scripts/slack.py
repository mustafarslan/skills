"""Minimal Slack Web API client (stdlib urllib). Tokens come only from the environment
(PR_PULSE_SLACK_BOT_TOKEN, PR_PULSE_SLACK_USER_TOKEN) and are never printed or logged.

Two identities: "bot" (the shared pr-pulse app; it reads channels and, by default, posts) and
"user" (the person running pr-pulse, with their own user token; config post_as "user" makes
posts and reactions come from them). Reading always uses the bot.
"""
import json
import os
import urllib.parse
import urllib.request

API = "https://slack.com/api/"


class SlackError(Exception):
    pass


# Scopes step 5 adds on top of the announce manifest (posting + listing channels).
READ_SCOPES = ("channels:history", "groups:history", "users:read", "users:read.email")


TOKEN_ENV = {"bot": "PR_PULSE_SLACK_BOT_TOKEN", "user": "PR_PULSE_SLACK_USER_TOKEN"}
USER_SCOPES = ("chat:write", "reactions:write")


def token(as_="bot"):
    return os.environ.get(TOKEN_ENV[as_], "")


def poster(cfg):
    """Who posts and reacts: "user" when config post_as is "user", else "bot"."""
    return "user" if (cfg or {}).get("post_as") == "user" else "bot"


def user_identity():
    """{user, user_id, team, scopes} for the user token — never the token itself."""
    b = call("auth.test", as_="user")
    return {"user": b.get("user", ""), "user_id": b.get("user_id", ""), "team": b.get("team", ""),
            "scopes": sorted(s.strip() for s in b.get("_scopes", "").split(",") if s.strip())}


def identity():
    """{team, bot, bot_user, scopes} for the token — never the token itself."""
    b = call("auth.test")
    return {"team": b.get("team", ""), "bot": b.get("user", ""), "bot_user": b.get("user_id", ""),
            "bot_id": b.get("bot_id", ""),
            "scopes": sorted(s.strip() for s in b.get("_scopes", "").split(",") if s.strip())}


def channels():
    """Channels the bot can see: [{id, name, private, member}]."""
    out, cursor = [], ""
    while True:
        params = {"types": "public_channel,private_channel", "exclude_archived": "true", "limit": 200}
        if cursor:
            params["cursor"] = cursor
        b = call("conversations.list", params)
        for c in b.get("channels") or []:
            out.append({"id": c["id"], "name": c.get("name", ""), "private": bool(c.get("is_private")),
                        "member": bool(c.get("is_member"))})
        cursor = (b.get("response_metadata") or {}).get("next_cursor") or ""
        if not cursor:
            return out


def call(method, params=None, post=False, as_="bot"):
    tok = token(as_)
    if not tok:
        raise SlackError(f"{TOKEN_ENV[as_]} is not set")
    headers = {"Authorization": f"Bearer {tok}"}
    if post:
        data = json.dumps(params or {}).encode()
        headers["Content-Type"] = "application/json; charset=utf-8"
        req = urllib.request.Request(API + method, data=data, headers=headers)
    else:
        q = urllib.parse.urlencode(params or {})
        req = urllib.request.Request(f"{API}{method}?{q}", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            body = json.loads(r.read().decode())
            body["_scopes"] = r.headers.get("x-oauth-scopes", "")
    except Exception as e:  # network, HTTP 429, bad JSON
        raise SlackError(f"{method}: {type(e).__name__}") from None
    if not body.get("ok"):
        raise SlackError(f"{method}: {body.get('error', 'unknown error')}")
    return body


def whoami():
    """(bot user id, bot id) for the token, so the ingest can skip our own posts."""
    b = call("auth.test")
    return b.get("user_id", ""), b.get("bot_id", "")


def history(channel, oldest):
    """Messages newer than `oldest` (a Slack ts string), oldest first, at most 200."""
    b = call("conversations.history", {"channel": channel, "oldest": oldest or "0",
                                       "limit": 200, "inclusive": "false"})
    return list(reversed(b.get("messages") or []))


def recent_threads(channel, since):
    """Top-level messages since `since` (a Slack ts string) that have replies, oldest first, at
    most 200. Each carries `latest_reply`, so one call tells which threads moved. History never
    returns the replies themselves: a reply in a thread is only visible through `replies`."""
    b = call("conversations.history", {"channel": channel, "oldest": since, "limit": 200})
    return [m for m in reversed(b.get("messages") or []) if m.get("reply_count")]


def replies(channel, ts, oldest):
    """Replies in the thread under `ts` newer than `oldest`, oldest first, without the parent
    (Slack always returns the parent first, whatever `oldest` says)."""
    b = call("conversations.replies", {"channel": channel, "ts": ts, "oldest": oldest,
                                       "inclusive": "false", "limit": 200})
    return [m for m in b.get("messages") or [] if m.get("ts") != ts]


_IS_BOT = {}


def is_bot_user(user_id):
    """users.info is_bot, cached. Unknown (the lookup failed) counts as a bot: never mistake a
    bot's post for a person's share."""
    if user_id not in _IS_BOT:
        try:
            u = call("users.info", {"user": user_id}).get("user") or {}
            _IS_BOT[user_id] = bool(u.get("is_bot")) or u.get("id") == "USLACKBOT"
        except SlackError:
            return True
    return _IS_BOT[user_id]


def from_a_bot(msg):
    """Was this message written by a bot, not a person? A person posting through an app with their
    own user token (pr-pulse post_as "user") also gets a bot_id, app_id and bot_profile; only the
    `user` tells them apart: a bot user for a bot, the person for a person."""
    if not msg.get("bot_id"):
        return False
    user = msg.get("user") or ""
    return not user or is_bot_user(user)


def find_share(channels, pr_url, skip_users=(), days=30):
    """The newest message in these channels that shared this PR (not from skip_users), as
    (channel, ts, user), or None. Reads at most ~1000 messages per channel."""
    import time as _t
    best = None
    oldest = f"{_t.time() - days * 86400:.0f}"
    for ch in channels:
        cursor = ""
        for _ in range(5):
            params = {"channel": ch, "limit": 200, "oldest": oldest}
            if cursor:
                params["cursor"] = cursor
            try:
                b = call("conversations.history", params)
            except SlackError:
                break
            for m in b.get("messages") or []:
                if m.get("user") in skip_users or from_a_bot(m):
                    continue
                if pr_url in (m.get("text") or "") and (best is None or float(m["ts"]) > float(best[1])):
                    best = (ch, m["ts"], m.get("user"))
            cursor = (b.get("response_metadata") or {}).get("next_cursor") or ""
            if not cursor:
                break
    return best


def message_exists(channel, ts):
    """False when the message at ts is gone (deleted), True when it is there. Slack posts a reply to a
    deleted parent at the channel root without an error, so callers check first. Raises SlackError on
    any other failure."""
    try:
        b = call("conversations.replies", {"channel": channel, "ts": ts, "limit": 1})
    except SlackError as e:
        if str(e).endswith(("thread_not_found", "message_not_found")):
            return False
        raise
    return bool(b.get("messages"))


def lookup_by_email(email):
    try:
        return call("users.lookupByEmail", {"email": email}).get("user", {}).get("id", "")
    except SlackError:
        return ""


def profile(user_id):
    try:
        return call("users.info", {"user": user_id}).get("user", {}).get("profile", {})
    except SlackError:
        return {}


REACT_SCOPE = "reactions:write"


def react(channel, ts, name, as_="bot"):
    """Add an emoji reaction (name without colons). True when this call added it; False when it
    was already there, so a reaction the person added by hand is never recorded as ours (and
    never taken off later)."""
    try:
        call("reactions.add", {"channel": channel, "timestamp": ts, "name": name}, post=True, as_=as_)
    except SlackError as e:
        if str(e).endswith("already_reacted"):
            return False
        raise
    return True


def unreact(channel, ts, name, as_="bot"):
    """Remove a reaction made by as_. Already gone counts as done."""
    try:
        call("reactions.remove", {"channel": channel, "timestamp": ts, "name": name}, post=True, as_=as_)
    except SlackError as e:
        if not str(e).endswith("no_reaction"):
            raise


def post(channel, text, thread_ts=None, as_="bot"):
    params = {"channel": channel, "text": text, "unfurl_links": False, "unfurl_media": False}
    if thread_ts:
        params["thread_ts"] = thread_ts
    return call("chat.postMessage", params, post=True, as_=as_).get("ts", "")


def update(channel, ts, text, as_="bot"):
    """Edit a message. Slack only lets the identity that posted it edit it, so pass the one stored
    with the message, not the current post_as."""
    call("chat.update", {"channel": channel, "ts": ts, "text": text}, post=True, as_=as_)
