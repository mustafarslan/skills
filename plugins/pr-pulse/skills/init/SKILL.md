---
description: Set up pr-pulse with the user, step by step - start the daemon, map repos, then (if they want) connect Slack for PR announcements and, optionally, for picking up shared PRs and posting review verdicts. Use when the user says "/pr-pulse:init", "set up pr-pulse", "connect pr-pulse to Slack", or right after installing the plugin. Safe to re-run; it only offers what is missing.
argument-hint: "[slack]"
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse *), Bash(brew install vjeantet/tap/alerter), Bash(open https://api.slack.com/*), Bash(git config --get *), Read, AskUserQuestion
---

# pr-pulse init

You set pr-pulse up **together with the user**. Be friendly, positive, concise and brief, with
no chitchat. Say each step in plain words, do the parts you can do yourself, and hand over
only what needs their hands: a browser click or a Slack login.

`P` below means `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse`.

## 0. Where are we?

Run `P doctor --json`. Then open with one line, such as "Let's get pr-pulse running; I'll do
most of it." Skip every step that is already done, and say so in a few words ("Daemon:
already running ✓").

If `gh_logged_in` is false, say: GitHub CLI isn't logged in; run `! gh auth login`, then
`/pr-pulse:init` again. Stop there.

If `$ARGUMENTS` is `slack`, jump to step 4.

## 2. Daemon and helpers (automatic)

- `step2_daemon` false and `stopped` true: run `P start`.
- `step2_daemon` false otherwise: run `P daemon install`.
- `alerter` false: run `P deps --install`. alerter lets the user answer pr-pulse questions
  straight from a notification; without it, a small macOS dialog is used instead.

Report it in one line.

**Updates.** If `autoupdate` is false and `marketplace` is set, ask once with AskUserQuestion:
"Keep pr-pulse up to date automatically? Claude Code then installs new versions of every plugin
from the <marketplace> marketplace within ~10 minutes of starting a session; open sessions pick
them up with /reload-plugins."
- **Turn it on (Recommended):** run `P autoupdate on` and report its first line.
- **Not now:** say they can run `pr-pulse autoupdate on` any time.

## 3. Repos (automatic, with one question)

If `step3_map` is false, follow the `/pr-pulse:map` flow:
1. Run `P map`.
2. Use one AskUserQuestion to pick the PR session per repo.
3. Run `P map set …` for each pick.

If the current session sits in a mapped repo and isn't joined, ask once whether this session
should take PR work. If yes, follow `/pr-pulse:join`.

## 4. Slack announcements (ask first)

Explain in at most two sentences what it does: "pr-pulse can post a short, friendly note in
#pr-review whenever you open a PR. It takes about 3 minutes: we create a small Slack app
together." Then AskUserQuestion:
- **Set it up now (Recommended):** "I'll open Slack in your browser and guide each click"
- **Later:** "You can run /pr-pulse:init slack any time"

If the answer is Later, go to the summary.

**The team's shared app.** If `team_app` in `P doctor --json` is not empty and `bot_token_set` is
false, ask first:
- **Use the team's pr-pulse app (Recommended):** "One shared bot for everyone; you only copy
  its token"
- **Create my own app:** "A separate Slack app just for you (steps 4a–4f)"

For the team app, do only these steps:
1. **Token.** Show `team_app.token_source` as the instruction (for example: "In your password manager, open
   **pr-pulse Slack bot token** and copy it. Don't paste it here; just tell me when it's
   copied"). Then run `P secret set bot-token --from-clipboard`, and read back the workspace and
   bot it prints. If it says Slack refused the token, the item may be outdated: ask them to tell
   the app's owner.
2. **Channel.** Announcements go to the team channel (`team_app.channel_names` gives its name)
   with no setup. The bot is already in it. Skip 4a–4e.
3. Go to 4f, then step 5. In step 5, skip 5a, because the team app already has the reading
   permissions (`P slack whoami` lists `channels:history`), and offer `team_app.watch_channels`
   as the default answer in 5b. 5c and 5d run as written.

**Already started earlier?** If `bot_token_set` is false but the user may have created the app
before (for example, init stopped at admin approval), ask first: "Did you already create the
pr-pulse app in Slack?"
- **Yes:** run `open "https://api.slack.com/apps"`, have them click **pr-pulse**, and continue
  at 4b.
- **No:** start at 4a.

If `bot_token_set` is true but `token_ok` is false, the token was revoked or mistyped: go
straight to 4c.

Guide it in small steps. Each step is one short numbered list of clicks, then one
AskUserQuestion with these options:
- **Done**
- **Stuck:** I'll help

The user types the details of a problem in Other. Never move on without a Done.

**4a. Create the app.**
1. Get the link with `P slack manifest-url announce`, then run `open "<that url>"`.
2. Tell them: "A Slack page opened with the app already filled in (name pr-pulse; it can post
   and see the channel list). Pick your workspace → **Next** → **Next** → **Create**."
3. Not logged in? They log in in that tab first. The page didn't fill itself in? Run
   `P slack manifest announce --copy`. Then: **Create New App** → **From a manifest** → pick
   the workspace → select all in the box and paste → **Next** → **Create**.

**4b. Install it.**
1. Tell them: "On the app page: **Install to Workspace** → **Allow**."
2. If they see **Request to Install**, the workspace needs an admin's approval. Say: "Your
   Slack needs an admin to approve new apps. Send the request; once it's approved, run
   `/pr-pulse:init slack` and we continue right here." Then go to the summary.

**4c. Hand over the token without showing it to anyone.**
1. Tell them: "Left menu → **OAuth & Permissions** → **Bot User OAuth Token** (starts with
   xoxb-) → **Copy**. Don't paste it here; just tell me when it's copied."
2. Then run `P secret set bot-token --from-clipboard`. It checks the token, saves it privately,
   clears the clipboard, and prints only the workspace and bot name. Read those back.
3. If it fails, act on its message:
   - wrong thing copied → copy again;
   - empty clipboard or a clipboard manager in the way → `open -e ~/.config/pr-pulse/env` and
     have them add the line `export PR_PULSE_SLACK_BOT_TOKEN='…'` themselves.
4. If the user pastes the token into the chat anyway, don't repeat it. Say it is now in this
   conversation's history, and recommend: OAuth & Permissions → **Revoke All OAuth Tokens** →
   reinstall → copy the new one.

**4d. Pick the channel.**
1. Ask whether announcements should go to a **private** channel. If so, first: "In that channel,
   type `/invite @pr-pulse` and send it." Slack only shows the bot private channels it has
   been invited to. Public channels need no invite.
2. Run `P slack channels`.
3. AskUserQuestion: "Where should announcements go?" Offer up to 3 likely channels, those whose
   name has pr or review first, plus Other.
4. Save the pick with `P config set announce_channel <id>`.

**4e. Test it (ask first).** AskUserQuestion: "Send one test message ('pr-pulse is connected…')
to #<name>?"
- **Send it:** run `P slack test-post <id>`.
- **Skip:** move on.

**4f. Which repos announce automatically.** If repos are mapped, use one AskUserQuestion
(multiSelect) listing them. For each pick, run `P map set <slug> --announce`. Other repos still
announce from any session with `/pr-pulse:on`.

Close step 4 with one positive line.

## 5. Optional: reading the review channel

Explain in at most three short sentences, in a friendly tone, for example: "One more optional
piece. pr-pulse can also read your PR review channel. When teammates share a PR, it picks it
up for review 1–2 at a time; when someone tags you for a re-review, it starts that; and after
your review it replies in the thread, like 'approved @author'. Want to turn it on?"

AskUserQuestion:
- **Turn it on:** "About 2 minutes: we add reading permissions to the same app"
- **Not now:** "Run /pr-pulse:init slack later"

If Not now, go to the summary.

**5a. Add the reading permissions.**
1. Run `P slack manifest full --copy`, then run `open "https://api.slack.com/apps"`.
2. Tell them: "Click **pr-pulse** → left menu **App Manifest** → select all in the editor →
   paste (the new manifest is on your clipboard) → **Save Changes**. A yellow banner asks you
   to reinstall: **Reinstall to Workspace** → **Allow**."
3. If they see **Request to Install** instead, an admin must approve the new permissions. Say
   so, and tell them to run `/pr-pulse:init slack` once it is approved. Announcements keep
   working meanwhile. Go to the summary.
4. After a reinstall, always take the token again. Slack may issue a new one: "Left menu →
   **OAuth & Permissions** → **Bot User OAuth Token** → **Copy**", then run
   `P secret set bot-token --from-clipboard`.
5. Run `P slack whoami` and check that `scopes` includes `channels:history`. If not, the save or
   the reinstall didn't go through; repeat steps 2 and 4.

If `P doctor --json` shows a token but `slack.can_read` is false on a rerun, start 5 at 5a.

**5b. Channels to watch.**
1. Run `P slack channels`.
2. AskUserQuestion (multiSelect): "Which channels do teammates share PRs in?"
3. Save the picks:
   - `P config set watch_channels '["C…","C…"]'`
   - `P config set verdict_channel <first pick>` (verdicts reply in the share's thread; this
     channel is only the fallback)

**5c. Invite the bot.**
1. For each picked channel the list shows as "bot not invited": "In #<name>, type
   `/invite @pr-pulse` and send it."
2. Then run `P slack check <id>` for each. Fix any channel it names before going on.

**5d. Who you are on Slack.**
1. Take the email from `git config --get user.email`, then run `P slack whois <email>`.
2. If that fails (a personal or noreply git email), AskUserQuestion: "Which email do you use on
   Slack?" They type it in Other, or paste their member ID (Slack profile → ⋯ → **Copy member
   ID**).
3. Save the result with `P config set slack_user_id <U…>`.
4. Take the first name from `git config --get user.name`. Confirm it in the summary, then run
   `P config set my_name "<first name>"`. It's used in "<name>'s review: approved".

Teammates' GitHub logins are matched to Slack automatically by email. Mention, in one line,
that `github_to_slack` in config.json can pin someone whose email differs.

## 6. Optional: post as yourself

Only when Slack is set up (step 4 done) and `post_as` in `P doctor --json` is not `user`.
Explain in at most two sentences: "pr-pulse posts as the shared pr-pulse bot right now. It can
post your announcements, verdict replies and reactions as you instead; it takes a small personal
Slack app that can only write as you, never read." Then AskUserQuestion:
- **Post as me:** "About 2 minutes: a personal app, one token"
- **Keep the bot:** "Run /pr-pulse:init slack later"

Mention in the same breath: once posts come from them, teammates' pr-pulse picks their
announcements up as PR shares for review.

If `user_token_set` is true but `slack_user` has an `error`, the token was revoked: go to 6c.

**6a. Create the personal app.**
1. Get the link with `P slack manifest-url user`, then run `open "<that url>"`.
2. Tell them: "A Slack page opened with **pr-pulse (me)** filled in (it can post and react as
   you, nothing else). Pick the workspace → **Next** → **Next** → **Create**."
3. Page didn't fill in? `P slack manifest user --copy`, then **Create New App** → **From a
   manifest** → paste → **Create**.

**6b. Install it.** "**Install to Workspace** → **Allow**." **Request to Install** means an
admin must approve: say so, and to run `/pr-pulse:init slack` once approved. Go to the summary.

**6c. Hand over the token.**
1. "Left menu → **OAuth & Permissions** → **User OAuth Token** (starts with xoxp-) → **Copy**.
   Don't paste it here; just tell me when it's copied."
2. Run `P secret set user-token --from-clipboard`. It checks the token is theirs, saves it,
   clears the clipboard and turns `post_as` to `user`. Read back the `@name` it prints.
3. If it says the token belongs to someone else, they copied another person's token or
   `slack_user_id` is wrong: show its message and stop there.

**6d. Test it (ask first).** AskUserQuestion: "Post one test message as you in #<announce
channel> ('pr-pulse now posts as me')?"
- **Send it:** `P slack test-post <announce_channel id> --as-me`. If it says they are not in
  the channel, they join it in Slack and retry. If it says the post doesn't look like theirs,
  run `P config set post_as bot` and tell them to report it.
- **Skip:** move on.

Back to the bot any time: `pr-pulse config set post_as bot`.

## Summary

Run `P doctor` and show its lines. Add at most three lines: what's on, what's left (with
the exact command), and "`/pr-pulse:help` any time". End positively, in one sentence.

## Rules

- **Secrets never go through the chat.** Never ask for a token or URL, and never echo one.
  Only `secret set --from-clipboard` handles them.
- **Nothing is posted to Slack without the user's yes** (the test message in 4e is asked first).
- **Opening a page is fine; clicking in it is the user's.** Never type passwords, never log in
  for them, never approve OAuth screens for them.
- **If anything fails, say what happened in one line and give the next action.** Never pretend a
  step worked: check with `P doctor --json` or `P slack whoami`.
