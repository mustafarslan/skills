#!/usr/bin/env python3
"""pr-pulse-asker.py <question id> — show one question as a macOS notification and record the
answer. Started by the daemon, one at a time, so a notification left open never blocks a tick.

alerter (brew install vjeantet/tap/alerter): a banner whose Answer menu holds the options, "Type
an answer…" (a second banner with a reply box), "Details…" and "Open session". Everything goes
through that menu: macOS doesn't pass a click on the banner itself on to alerter, so a click there
did nothing and left the question on screen. "Details…" is the menu's first item, so a stray
keystroke that picks it never answers. Without alerter: the built-in macOS dialog, with no
default button, so a stray Enter can't answer for you.
The message is three short lines built by code (rules.notification_message): the findings by
severity with their scope ("1 critical (test) · 2 improvements"), the top finding or the
session's summary, then the question. "Details…" shows every finding on its own line, with
"Open session" and "Back" to the summary to answer. Only "Open session" brings the session to
the front.
"Later", closing it or no answer within 5 minutes: the banner goes, so it never holds up the
next question; the question stays pending, is listed in /pr-pulse:inbox, and comes back in an
hour.
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import core        # noqa: E402
import db          # noqa: E402
import questions   # noqa: E402

TIMEOUT = 300
INBOX = db.HOME / "inbox"
OPEN = object()   # the user clicked through to the session
TRAIL = []        # each banner interaction, logged with the outcome (summary/details/back/open)


def run(args, timeout):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return p.stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def _alert(base, extra):
    out = run(base + extra, TIMEOUT + 30)
    try:
        r = json.loads(out or "{}")
    except ValueError:
        return None, ""
    kind, val = r.get("activationType"), (r.get("activationValue") or "").strip()
    TRAIL.append(f"{'details' if 'Back' in base else 'summary'}:{kind}")
    return kind, val


def via_alerter(title, subtitle, q, options, allow_text, details="", type_label=None):
    """The summary banner; its Answer menu holds the options plus Details… and Open session.
    Details shows every finding, with Open session and Back to the summary to answer."""
    def base(close):
        return ["alerter", "--title", title, "--subtitle", subtitle, "--close-label", close,
                "--group", "pr-pulse-question", "--json", "--timeout", str(TIMEOUT)] + core.icon_args()

    tl = type_label or questions.TYPE_LABEL
    answers = list(options) + ([tl] if allow_text and options else [])
    # Details… comes first: a keystroke meant for another window can pick the banner's first
    # menu item (seen live 2026-11-11: two test banners "answered" Post 5-10 s after they
    # appeared, while the user typed elsewhere). The first item must never answer.
    menu = [questions.DETAILS_LABEL] + answers + [questions.OPEN_LABEL]
    for _ in range(6):   # summary -> details -> back to summary, a few times at most
        if answers:
            kind, val = _alert(base("Later") + ["--sound", "default"],
                               ["--message", q, "--actions", ",".join(a.replace(",", ";") for a in menu),
                                "--dropdown-label", "Answer"])
        else:
            kind, val = _alert(base("Later") + ["--sound", "default"],
                               ["--message", q, "--reply", "Your answer…"])
        if kind == "replied" and val:
            return val
        if kind == "actionClicked" and val == questions.OPEN_LABEL:
            return OPEN
        if kind == "actionClicked" and val and val != questions.DETAILS_LABEL:
            if val == tl:
                k2, v2 = _alert(base("Later"), ["--message", q, "--reply", "Your answer…"])
                return v2 if k2 == "replied" and v2 else None
            for o in options:   # map back from the comma-safe label
                if o.replace(",", ";") == val:
                    return o
            return val
        if kind not in ("actionClicked", "contentsClicked"):
            return None   # Later, closed, timed out
        # Details… (or a banner click, should macOS ever pass one on): every finding.
        k, v = _alert(base("Back"), ["--message", details or q, "--actions", questions.OPEN_LABEL])
        if k == "actionClicked" and v == questions.OPEN_LABEL:
            return OPEN
        if k == "timeout":
            return None
        # Back (or dismissed): show the summary again so they can answer
    return None


def confirm_drop(title, subtitle):
    """Dropping a draft can't be undone: ask once more."""
    if core.use_alerter():
        out = run(["alerter", "--title", title, "--subtitle", subtitle, "--message",
                   "Drop this draft? Nothing will be posted for it.", "--actions", "Drop it",
                   "--close-label", "Keep it", "--group", "pr-pulse-question", "--json",
                   "--timeout", "120"] + core.icon_args(), 150)
        try:
            r = json.loads(out or "{}")
        except ValueError:
            return False
        return r.get("activationType") == "actionClicked" and r.get("activationValue") == "Drop it"
    out = osa('display dialog "Drop this draft? Nothing will be posted for it." buttons {"Keep it", "Drop it"} '
              'giving up after 120', 150)
    return "button returned:Drop it" in out


def osa(script, timeout):
    return run(["osascript", "-e", script], timeout).strip()


def q_str(s):
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"') + '"'


def via_dialog(title, subtitle, q, options, allow_text, details="", type_label=None):
    prompt = q_str(f"{subtitle}\n\n{q}" + (f"\n\nDetails:\n{details}" if details else ""))
    if options and len(options) <= 1 and not allow_text:
        btns = ", ".join(q_str(o) for o in ["Later", questions.OPEN_LABEL] + list(options))
        out = osa(f"display dialog {prompt} with title {q_str(title)} buttons {{{btns}}} "
                  f"giving up after {TIMEOUT}", TIMEOUT + 30)
        val = out.split("button returned:", 1)[-1].split(",")[0].strip() if "button returned:" in out else ""
        if val == questions.OPEN_LABEL:
            return OPEN
        return val if val and val != "Later" else None
    if options:
        items = list(options) + ([questions.TYPE_LABEL] if allow_text else []) + [questions.OPEN_LABEL]
        lst = ", ".join(q_str(o) for o in items)
        out = osa(f"choose from list {{{lst}}} with title {q_str(title)} with prompt {prompt} "
                  f"OK button name \"Answer\" cancel button name \"Later\"", TIMEOUT + 30)
        if not out or out == "false":
            return None
        if out == questions.OPEN_LABEL:
            return OPEN
        if out != questions.TYPE_LABEL:
            return out
    out = osa(f"display dialog {prompt} with title {q_str(title)} default answer \"\" "
              f"buttons {{\"Later\", \"Send\"}} giving up after {TIMEOUT}", TIMEOUT + 30)
    if "button returned:Send" not in out:
        return None
    return out.split("text returned:", 1)[-1].strip() or None


def main(argv):
    qid = int(argv[0])
    con = db.connect()
    q = con.execute("SELECT q.*, j.action, p.slug, p.n FROM questions q JOIN jobs j ON j.id=q.job_id "
                    "LEFT JOIN prs p ON p.url=j.pr_url WHERE q.id=?", (qid,)).fetchone()
    if not q or q["status"] != "showing":
        return 0
    title = "pr-pulse"
    subtitle = f"{q['slug']}#{q['n']} · {q['action']}"
    options = json.loads(q["options"] or "[]")
    import rules
    message = rules.notification_message(q["question"], q["summary"] or "",
                                         json.loads(q["findings"] or "[]"))
    findings = json.loads(q["findings"] or "[]")
    details = q["details"] or rules.details_text(q["summary"] or "", findings)
    is_draft = q["kind"] == "draft"
    show = via_alerter if core.use_alerter() else via_dialog
    try:
        ans = show(title, subtitle, message, options, bool(q["allow_text"]), details,
                   "Type my own lines…" if is_draft else None)
        if is_draft and ans == "Drop it" and not confirm_drop(title, subtitle):
            ans = None   # kept: back to pending
    except Exception as e:
        db.event(con, "question.ui_error", {"id": qid, "error": repr(e)})
        ans = None
    con = db.connect()   # the UI may have taken minutes; start a fresh connection
    now = con.execute("SELECT status FROM questions WHERE id=?", (qid,)).fetchone()
    if not now or now["status"] != "showing":
        db.event(con, "question.trail", {"id": qid, "trail": TRAIL, "note": "answered elsewhere"})
        return 0   # answered in a session or the inbox meanwhile: ignore this banner's result
    if ans is OPEN:
        import sessionui
        res = sessionui.open_session(q["sid"])
        db.event(con, "question.opened_session", {"id": qid, "result": res, "trail": TRAIL})
        questions.release(con, qid)   # still open: they answer in the session or the next reminder
        return 0
    if ans:
        res = questions.answer(con, qid, ans, "notification" if show is via_alerter else "dialog", INBOX)
        db.event(con, "question.trail", {"id": qid, "trail": TRAIL})
        if res == "expired":
            subprocess.run(["osascript", "-e", 'display notification "That question expired: its job '
                            'already finished." with title "pr-pulse"'], capture_output=True)
    else:
        db.event(con, "question.trail", {"id": qid, "trail": TRAIL})
        questions.release(con, qid)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
