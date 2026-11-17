---
description: Show everything pr-pulse is waiting on the user for, in one batch — questions sessions asked them (that they put off or missed in the notification), drafts waiting for their own top lines (review comments, replies, merge decisions) — collect their answers and lines, or write the lines for them when they pick "Fill it for me", and send each job back to its session. Use when the user says "/pr-pulse:inbox", "what's waiting for me", or after a "drafts waiting" notification.
allowed-tools: Bash(${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse *), Read, AskUserQuestion
---

# pr-pulse inbox

Sessions pr-pulse starts never post outward text themselves. They park drafts here. the user
adds their own top lines to each one, or asks you to fill them in for them. Only then does the
session post: their lines first, the draft quoted below.

1. Run `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse questions`,
   `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse outbox list` and
   `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse announce list`. If none has anything waiting, say so
   in one line and stop.

   **Questions come first.** Sessions ask them while they work, and each one is blocking a
   job. Ask each with AskUserQuestion: the question text, its options (at most 4; if there
   are more, list them in the question and let them type in Other), and Other for a typed
   answer. Then pass their answer on verbatim:
   `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse answer <question id> <their answer>`. Skip any
   question marked "on screen now"; they may be answering it in the notification.
2. Show the drafts grouped by PR, in a compact form. For each one give the draft id, the kind,
   where it goes, and the draft text. Shorten long drafts to their first lines, and say so.
3. Ask with **AskUserQuestion**: one question per draft, at most 4 per call (make more calls
   for more drafts). Put the PR and a short quote of the draft in the question text.
   - A normal draft (kind review, reply or comment) gets these options:
     - **Fill it for me**: "I write your top lines for you: friendly, positive, brief, no chitchat"
     - **Drop it**: "Nothing is posted for this draft"

     The built-in "Other" box is where they type their own lines. Say so in the question:
     "(type your own top lines in Other)".
   - A draft with **proposed top lines** (status `fill`: the session wrote them after a "Fill it
     for me") gets these options, with the proposed lines quoted in the question:
     - **Post**: "Post with these top lines"
     - **Drop it**: "Nothing is posted for this draft"
   - A merge decision (kind `decision`) gets these options:
     - **Merge**: "Merge this exact head"
     - **Re-review**: "Re-request review from the approvers, and don't merge"
4. Act on each answer:
   - **Their own lines** (Other): pass them on exactly as written:
     `printf '%s' "<their lines verbatim>" | ${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse outbox lines <id>`
   - **Fill it for me**:
     1. Read `${CLAUDE_PLUGIN_ROOT}/prompts/top-lines-guide.md`.
     2. Read the full draft: `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse outbox show --job <job id>`.
     3. Write the lines by following the guide.
     4. Save them: `printf '%s' "<the lines>" | ${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse outbox lines <id> --filled`
   - **Post** (proposed lines): save the proposed lines exactly as shown, as theirs:
     `printf '%s' "<the proposed lines>" | ${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse outbox lines <id> --filled`
   - **Drop it**: `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse outbox drop <id>`
   - **Merge** or **Re-review**: `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse outbox decide <id> merge`
     or `… decide <id> re-review`
5. **PRs not announced yet** (from `announce list`): one AskUserQuestion per PR, with the PR
   and its title in the question:
   - **Write and post it**: "I write a 1–3 sentence announcement; pr-pulse posts it"
   - **Skip**: "This PR is not announced"

   A PR whose post **failed** already has its text: offer **Retry** ("Post the saved text
   again": `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse announce retry <url>`) and **Skip** instead.
   If saving prints "NOT POSTED YET", tell them what it says to run.

   For **Write and post it**: read `${CLAUDE_PLUGIN_ROOT}/prompts/summary-guide.md` and the PR
   (`gh pr view <url> --json title,body`), write the text, then save it:
   `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse announce <url> <<'PR_PULSE_EOF'` … `PR_PULSE_EOF`.
   Text they typed in Other is saved exactly as written. For **Skip**:
   `${CLAUDE_PLUGIN_ROOT}/scripts/pr-pulse announce drop <url>`.
6. Reply with one line per draft saying what happens next. For every "Fill it for me", quote
   the lines you wrote so they see exactly what goes out in their name. Drafts that weren't
   answered stay waiting; say how many.

Never change lines they typed themselves. Never post anything from here: the job's own session
posts on its next turn, and the pr-pulse service posts saved announcements.
