"""pr-pulse rules: pure functions, no I/O. Every decision the daemon makes lives here, so the
tests can prove each gate both rejects and accepts.
"""
import re

# Job priorities: lower runs first.
PRIO = {"feedback": 0, "feedback-bots": 0, "merge": 0, "merge-check": 0, "re-review": 1, "review-requested": 2, "pool": 3}

DEFAULT_IGNORE = ("linear", "github-actions", "vercel", "netlify", "codecov", "sonarcloud")

PR_URL_RE = re.compile(r"https://github\.com/([^/\s|>]+)/([^/\s|>]+)/pull/(\d+)")
MENTION_RE = re.compile(r"<@([A-Z0-9]+)(?:\|[^>]*)?>")


def _login(x):
    return ((x or {}).get("author") or {}).get("login") or ""


DEFAULT_REVIEW_BOTS = ("coderabbitai", "claude", "copilot-pull-request-reviewer", "copilot",
                       "chatgpt-codex-connector", "codex")


def _base(login):
    return (login or "").lower().replace("[bot]", "")


def _ignored(login, me, ignore):
    return login == me or _base(login) in ignore


def is_review_bot(login, bots=DEFAULT_REVIEW_BOTS):
    return _base(login) in bots or (login or "").lower().endswith("[bot]")


def activity(pr, me, ignore=DEFAULT_IGNORE, bots=DEFAULT_REVIEW_BOTS):
    """Split review activity by who wrote it (never me, never ignored bots like linear).

    Returns dict:
      human_reviews  — reviews by people that say something (an approval with an empty body
                       is not something to address)
      human_comments — PR comments by people
      human_any      — True once any person reviewed or commented, approvals included
      bots           — reviews + comments by review bots (CodeRabbit, Claude, Copilot, …)
    """
    out = {"human_reviews": 0, "human_comments": 0, "human_any": False, "bots": 0}
    for r in pr.get("reviews") or []:
        who = _login(r)
        if _ignored(who, me, ignore):
            continue
        if is_review_bot(who, bots):
            out["bots"] += 1
            continue
        out["human_any"] = True
        if not (r.get("state") == "APPROVED" and not (r.get("body") or "").strip()):
            out["human_reviews"] += 1
    for c in pr.get("comments") or []:
        who = _login(c)
        if _ignored(who, me, ignore):
            continue
        if is_review_bot(who, bots):
            out["bots"] += 1
        else:
            out["human_any"] = True
            out["human_comments"] += 1
    return out


def others_activity(pr, me, ignore=DEFAULT_IGNORE, bots=DEFAULT_REVIEW_BOTS):
    """(human reviews that say something, human comments)."""
    a = activity(pr, me, ignore, bots)
    return a["human_reviews"], a["human_comments"]


def approved_sha(pr, me, bots=DEFAULT_REVIEW_BOTS):
    """Commit of the newest APPROVED review by a person other than me, or ''."""
    best = ""
    for r in sorted(pr.get("reviews") or [], key=lambda r: r.get("submittedAt") or ""):
        if r.get("state") == "APPROVED" and _login(r) != me and not is_review_bot(_login(r), bots):
            best = (r.get("commit") or {}).get("oid") or best
    return best


def standing_changes_requested(pr, me, bots=DEFAULT_REVIEW_BOTS):
    """People whose latest review is CHANGES_REQUESTED (review bots don't block merges)."""
    latest = {}
    for r in sorted(pr.get("reviews") or [], key=lambda r: r.get("submittedAt") or ""):
        who = _login(r)
        if who and who != me and not is_review_bot(who, bots) and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            latest[who] = r.get("state")
    return sorted(w for w, s in latest.items() if s == "CHANGES_REQUESTED")


def own_pr_action(pr, row, me, cfg, has_active_job, pending_drafts, ignore=DEFAULT_IGNORE):
    """Decide the next job for one of my open PRs.

    Review bots (CodeRabbit, Claude, …) never start a round alone before a person has
    reviewed: their comments wait and are handled in the same /pr-feedback round as the first
    human review (the user's rule, 2026-11-09). After a person has reviewed, new bot activity
    may start extra rounds, capped by bot_rounds; those never put the PR on hold.

    pr   — fresh `gh pr list --json` object
    row  — the stored prs row as a dict (None the first time we see the PR)
    Returns (action | None, note, seen) where seen = (human reviews, human comments, bots) to
    store, or None to leave the stored counters alone.
    """
    bots = tuple(cfg.get("review_bots") or DEFAULT_REVIEW_BOTS)
    a = activity(pr, me, ignore, bots)
    now = (a["human_reviews"], a["human_comments"], a["bots"])
    if row is None:
        # First sight: remember where we are; never act on history we did not watch.
        return None, "first seen", now
    if pr.get("isDraft") or pr.get("state") != "OPEN":
        return None, "draft or not open", None
    if has_active_job:
        return None, "a job is already active", None
    if row.get("hold"):
        # The round cap handed this PR to the user: nothing automatic, merges included,
        # until they run `pr-pulse pr release <url>`.
        return None, "on hold for the user", now
    new_rv = a["human_reviews"] - (row.get("reviews_seen") or 0)
    new_cm = a["human_comments"] - (row.get("comments_seen") or 0)
    new_bots = a["bots"] - (row.get("bots_seen") or 0)
    if new_rv > 0 or new_cm > 0:
        if (row.get("feedback_rounds") or 0) >= int(cfg.get("feedback_rounds", 2)):
            return "ask", (f"new review activity, but {row.get('feedback_rounds')} automatic "
                           "feedback rounds already ran — on hold for you (pr-pulse pr release "
                           "<url> to hand it back)"), now
        note = f"{max(new_rv, 0)} new review(s), {max(new_cm, 0)} new comment(s) from people"
        if new_bots > 0:
            note += f", plus {new_bots} from review bots — handle them all in this round"
        return "feedback", note, now
    if new_bots > 0:
        if not a["human_any"]:
            # Leave bots_seen alone: these wait for the first human review.
            return None, f"{new_bots} review-bot comment(s) waiting for a human review", \
                (a["human_reviews"], a["human_comments"], row.get("bots_seen") or 0)
        if (row.get("bot_rounds") or 0) < int(cfg.get("bot_rounds", 2)):
            return "feedback-bots", (f"{new_bots} new review-bot comment(s) after a human review; "
                                     "handle them"), now
        # Bot-only round cap reached: don't hold the PR, just stop chasing the bots.
        now = (a["human_reviews"], a["human_comments"], a["bots"])
    action, why = merge_gate(pr, me, pending_drafts, row.get("merge_ok_sha") or "", bots)
    return action, why, now


def merge_gate(pr, me, pending_drafts, merge_ok_sha="", bots=DEFAULT_REVIEW_BOTS):
    """(action, reason): "merge", "merge-check", or None (not ready).

    Every condition must hold; the /pr-merge skill still checks branch protection on top.
    Head == the approved commit -> "merge". Head moved after the approval (thread replies, a
    rebase) -> "merge-check": a session compares approved..head and asks the user in the inbox;
    they decide. Once they say merge, merge_ok_sha == head -> "merge".
    """
    if pr.get("isDraft"):
        return None, "draft"
    if pr.get("reviewDecision") != "APPROVED":
        return None, f"not approved ({pr.get('reviewDecision') or 'no decision'})"
    cr = standing_changes_requested(pr, me, bots)
    if cr:
        return None, "changes requested by " + ", ".join(cr)
    from core import ci_state  # local import keeps rules importable without core's deps
    ci = ci_state(pr.get("statusCheckRollup"))
    if ci != "green":
        return None, f"CI {ci}"
    if pending_drafts:
        return None, f"{pending_drafts} draft(s) still waiting for your lines"
    a_sha, head = approved_sha(pr, me, bots), pr.get("headRefOid") or ""
    if not a_sha:
        return None, "no approving review found"
    if a_sha != head:
        if merge_ok_sha and merge_ok_sha == head:
            return "merge", f"the user OK'd merging at {head[:9]} after the approval at {a_sha[:9]}"
        return "merge-check", (f"approved at {a_sha[:9]}, head now {head[:9]}: compare "
                               f"{a_sha[:9]}..{head[:9]} and ask the user")
    return "merge", f"approved at head {head[:9]}, CI green"


# ---- reviews for others -----------------------------------------------------------------

def review_skip_reason(pr, me, mapped_slugs, slug):
    """Why a PR from the pool or review-requested list should not be reviewed now ('' = go)."""
    if slug not in mapped_slugs:
        return "repo not mapped"
    if _login(pr) == me:
        return "own PR"
    if pr.get("state") != "OPEN":
        return "closed or merged"
    if pr.get("isDraft"):
        return "draft"
    if pr.get("reviewDecision") == "APPROVED":
        return "already approved"
    head = pr.get("headRefOid") or ""
    for r in pr.get("reviews") or []:
        if _login(r) == me and (r.get("commit") or {}).get("oid") == head and head:
            return "already reviewed at head"
    return ""


def pushed_after_changes_requested(pr, me):
    """The sha of my standing CHANGES_REQUESTED review when the author has answered it, else ''.

    "Standing" is my latest review that sets a state (APPROVED, CHANGES_REQUESTED or
    DISMISSED); a COMMENTED review after it, such as a reply in a thread, leaves it standing.
    "Answered" needs both a head past that review and a reply from the author after it (a
    review-thread reply or a PR comment): a rebase or a merge from main moves the head too, and
    must not start a review on its own.
    """
    head = pr.get("headRefOid") or ""
    standing = None
    for r in sorted(pr.get("reviews") or [], key=lambda r: r.get("submittedAt") or ""):
        if _login(r) == me and r.get("state") in ("APPROVED", "CHANGES_REQUESTED", "DISMISSED"):
            standing = r
    if not standing or standing.get("state") != "CHANGES_REQUESTED" or not head:
        return ""
    sha = (standing.get("commit") or {}).get("oid") or ""
    if not sha or sha == head:
        return ""
    since, author = standing.get("submittedAt") or "", _login(pr)
    replied = any(_login(r) == author and (r.get("submittedAt") or "") > since
                  for r in pr.get("reviews") or []) or \
        any(_login(c) == author and (c.get("createdAt") or "") > since
            for c in pr.get("comments") or [])
    return sha if replied else ""


def last_reviewed_sha(pr, me):
    sha = ""
    for r in sorted(pr.get("reviews") or [], key=lambda r: r.get("submittedAt") or ""):
        if _login(r) == me:
            sha = (r.get("commit") or {}).get("oid") or sha
    return sha


# ---- Slack ---------------------------------------------------------------------------------

def classify_slack(msg, my_slack_id, bot_user_id, bot_id=""):
    """Classify one channel message.

    Returns ("ignore", reason) | ("pool", [urls]) | ("re-review", [urls]).
    Shares are untagged; a tag of me on a PR means "please re-review".
    """
    user = msg.get("user") or ""
    if (bot_user_id and user == bot_user_id) or (bot_id and msg.get("bot_id") == bot_id):
        return "ignore", "own bot"
    if msg.get("subtype") in ("channel_join", "channel_leave", "message_deleted", "message_changed"):
        return "ignore", "subtype"
    text = msg.get("text") or ""
    urls = pr_urls(text)
    if not urls:
        return "ignore", "no PR link"
    if my_slack_id and user == my_slack_id:
        return "ignore", "my own share"
    mentions = set(MENTION_RE.findall(text))
    if my_slack_id and my_slack_id in mentions:
        return "re-review", urls
    return "pool", urls


def pr_urls(text):
    """The GitHub PR links in a Slack message, normalised, in order, without repeats."""
    urls = []
    for m in PR_URL_RE.finditer(text or ""):
        u = f"https://github.com/{m.group(1)}/{m.group(2)}/pull/{m.group(3)}"
        if u not in urls:
            urls.append(u)
    return urls


def classify_reply(msg, parent, my_slack_id, bot_user_id, bot_id=""):
    """Classify one reply inside a thread. A reply that tags me asks me to look again at the PR
    the thread is about, even though the link is only in the parent (an author answering a
    review: "@me fixed both, please re-review").

    Returns ("ignore", reason) | ("re-review", [urls])."""
    user = msg.get("user") or ""
    if (bot_user_id and user == bot_user_id) or (bot_id and msg.get("bot_id") == bot_id):
        return "ignore", "own bot"
    if msg.get("subtype") in ("channel_join", "channel_leave", "message_deleted", "message_changed"):
        return "ignore", "subtype"
    if not my_slack_id or user == my_slack_id:
        return "ignore", "my own reply"
    if my_slack_id not in set(MENTION_RE.findall(msg.get("text") or "")):
        return "ignore", "not tagged"
    urls = pr_urls(msg.get("text")) or pr_urls(parent.get("text"))
    if not urls:
        return "ignore", "no PR link in the reply or its thread"
    return "re-review", urls


def verdict_for(state, inline_comments):
    """Slack verdict text for a posted GitHub review, or None for states we don't announce."""
    if state == "APPROVED":
        return "lgtm with comments" if inline_comments > 0 else "approved"
    if state == "CHANGES_REQUESTED":
        return "request changes"
    if state == "COMMENTED":
        return "comments added"
    return None


VERDICT_EMOJI = {
    "approved": "white_check_mark",          # ✅
    "lgtm with comments": "white_check_mark",
    "request changes": "warning",            # ⚠️
    "comments added": "speech_balloon",      # 💬
}
REREVIEW_EMOJI = "recycle"                   # ♻️ a re-review is under way


def verdict_emoji(verdict):
    """The Slack reaction for a verdict (verdict_style "emoji"), or None."""
    return VERDICT_EMOJI.get(verdict or "")


def verdict_text(my_name, verdict, slack_author_id, pr_url, ref, lines=""):
    """The thread reply: verdict, author tag, link, then the reviewer's own top lines (the words
    they approved for the review), so the thread shows what they said. No name (posted as the
    reviewer themselves): "Review: approved …"."""
    tag = f" <@{slack_author_id}>" if slack_author_id else ""
    who = f"{my_name}'s review" if my_name else "Review"
    text = f"{who}: {verdict}{tag} · <{pr_url}|{ref}>"
    lines = " ".join((lines or "").split())
    return f"{text}\n> {lines}" if lines else text


def sharer_matches(github_login, gh_name, slack_profile):
    """Is the Slack sharer plausibly the GitHub author? Conservative: exact-ish name hits only."""
    if not slack_profile:
        return False
    names = {(slack_profile.get(k) or "").strip().lower()
             for k in ("display_name", "real_name", "display_name_normalized", "real_name_normalized")}
    names.discard("")
    login = (github_login or "").lower()
    full = (gh_name or "").strip().lower()
    if (login and login in names) or (full and full in names):
        return True
    # The sharer of a PR is almost always its author: a first-name match is enough here
    # (GitHub "Jane Doering" vs Slack "Jane").
    first = full.split()[0] if full else ""
    return bool(first) and any(n.split()[0] == first for n in names if n)


# ---- question summaries ------------------------------------------------------------------
# A notification shows the findings behind a decision, so a "critical" in a test file or a doc
# reads differently from one in production code. Scope is about what the change can break,
# not the file type: migrations, infra and deploy workflows count as production (agy's point).

PROD_SCOPES = ("runtime", "migration", "infra")
SCOPE_LABEL = {"runtime": "", "migration": "migration", "infra": "infra", "tests": "test",
               "docs": "docs", "ci": "ci", "tooling": "tooling"}
SEVERITY_ALIASES = {
    "critical": "critical", "blocker": "critical", "high": "critical", "must": "critical",
    "improvement": "improvement", "major": "improvement", "medium": "improvement",
    "should": "improvement", "suggestion": "improvement",
    "nit": "nit", "minor": "nit", "low": "nit", "style": "nit", "optional": "nit",
}
SEVERITY_ORDER = ("critical", "improvement", "nit")

_MIGRATION = re.compile(r"(^|/)(migrations?|alembic|flyway|liquibase)(/|$)|(^|/)prisma/migrations/|"
                        r"\.sql$|(^|/)db/migrate/", re.I)
_INFRA = re.compile(r"\.tf$|\.tfvars$|(^|/)(terraform|infra|k8s|kubernetes|helm|charts|deploy|"
                    r"deployment)(/|$)|(^|/)Dockerfile|docker-compose[^/]*\.ya?ml$|"
                    r"(^|/)\.github/workflows/[^/]*(deploy|release|publish|prod)[^/]*\.ya?ml$", re.I)
_TESTS = re.compile(r"(^|/)(tests?|__tests__|spec|specs|testdata|fixtures|e2e)(/|$)|"
                    r"(^|/)test_[^/]+$|_test\.[a-z]+$|\.(test|spec)\.[a-z]+$|Tests?\.[a-z]+$", re.I)
_DOCS = re.compile(r"\.(md|mdx|rst|txt|adoc)$|(^|/)(docs?|documentation)(/|$)|(^|/)README", re.I)
_CI = re.compile(r"(^|/)\.github/|(^|/)\.gitlab-ci|(^|/)\.circleci/|(^|/)Jenkinsfile", re.I)
_TOOLING = re.compile(r"(^|/)\.(eslintrc|prettierrc|editorconfig|husky|vscode)|(^|/)(eslint|prettier|"
                      r"ruff|mypy|tsconfig|jest|vitest)[^/]*\.(json|js|cjs|mjs|ts|toml|ya?ml)$", re.I)


def infer_scope(path):
    p = (path or "").split(":")[0]
    if not p:
        return "runtime"
    for scope, rx in (("migration", _MIGRATION), ("infra", _INFRA), ("tests", _TESTS),
                      ("docs", _DOCS), ("ci", _CI), ("tooling", _TOOLING)):
        if rx.search(p):
            return scope
    return "runtime"


def effective_scope(stated, path):
    """A session may raise a finding's risk, never lower it below what the path shows.

    - The path looks like production (runtime, migration, infra): production, whatever the
      session says; it can't relabel src/ as "tests" (side-agent finding).
    - The path looks non-production (tests, docs, ci, tooling): the session may raise it to
      production (a fixture that defines a prod contract), or name another non-prod scope.
    - No path: the session's scope, else runtime.
    """
    inferred = infer_scope(path)
    stated = (stated or "").strip().lower()
    if stated not in SCOPE_LABEL:
        stated = ""
    if not (path or "").strip():
        return stated or "runtime"
    if inferred in PROD_SCOPES:
        return inferred if inferred != "runtime" or stated not in ("migration", "infra") else stated
    if stated in PROD_SCOPES:
        return stated
    return inferred


def normalize_findings(raw):
    out = []
    for f in raw or []:
        sev = SEVERITY_ALIASES.get(str(f.get("severity", "")).strip().lower(), "improvement")
        path = str(f.get("path") or "").strip()
        out.append({"severity": sev, "path": path, "what": str(f.get("what") or "").strip(),
                    "scope": effective_scope(f.get("scope"), path)})
    # production first, then by severity
    out.sort(key=lambda f: (SEVERITY_ORDER.index(f["severity"]), f["scope"] not in PROD_SCOPES))
    return out


def _plural(n, word):
    return f"{n} {word}{'' if n == 1 else 's'}"


def counts_line(findings):
    """'1 critical (test) · 2 improvements · 3 nits' — scope noted when not all production."""
    parts = []
    for sev in SEVERITY_ORDER:
        fs = [f for f in findings if f["severity"] == sev]
        if not fs:
            continue
        word = {"critical": "critical", "improvement": "improvement", "nit": "nit"}[sev]
        label = f"{len(fs)} {word}" if sev == "critical" else _plural(len(fs), word)
        non_prod = sorted({SCOPE_LABEL[f["scope"]] for f in fs if f["scope"] not in PROD_SCOPES})
        prod = [f for f in fs if f["scope"] in PROD_SCOPES]
        special = sorted({SCOPE_LABEL[f["scope"]] for f in prod if SCOPE_LABEL[f["scope"]]})
        if sev in ("critical", "improvement") and (non_prod or special):
            if not prod:
                label += f" ({', '.join(non_prod)} only)" if len(non_prod) > 1 else f" ({non_prod[0]})"
            else:
                tags = special + [f"{sum(1 for f in fs if SCOPE_LABEL[f['scope']] == s)} {s}" for s in non_prod]
                label += f" ({', '.join(tags)})"
        parts.append(label)
    return " · ".join(parts) if parts else "no findings"


def top_line(findings, summary, limit=110):
    """The single most decision-relevant sentence: the worst production finding, else the worst
    finding, else the session's summary."""
    if findings:
        f = findings[0]
        loc = f" ({f['path']})" if f["path"] else ""
        text = f"{f['what']}{loc}" if f["what"] else summary
    else:
        text = summary
    text = " ".join((text or "").split())
    return text if len(text) <= limit else text[:limit - 1].rstrip() + "…"


def notification_message(question, summary, findings):
    """Three short lines: severity counts, the top finding (or summary), the question."""
    lines = []
    if findings:
        lines.append(counts_line(findings))
    top = top_line(findings, summary)
    if top:
        lines.append(top)
    lines.append(" ".join(question.split()))
    return "\n".join(lines)


def details_text(summary, findings, limit=8):
    """The expanded view: every finding on its own line, worst and production first."""
    lines = [" ".join(summary.split())] if summary else []
    for f in findings[:limit]:
        scope = SCOPE_LABEL[f["scope"]] or "runtime"
        where = f" {f['path']}" if f["path"] else ""
        lines.append(f"{f['severity']} · {scope}{where} — {f['what']}")
    if len(findings) > limit:
        lines.append(f"+{len(findings) - limit} more in the session")
    return "\n".join(lines) if lines else "No findings recorded for this question."
