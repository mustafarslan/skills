How to write the pr-pulse announcement

Readers: teammates skimming #pr-review to decide what to review next.

- 1 to 3 sentences, under 60 words in total.
- Friendly, positive and plain. Confident, never salesy.
- Say what changed and why it matters: the effect for users, the risk it removes, or what it unblocks.
- Mention anything a reviewer must know up front, such as a migration, a feature flag or a breaking change.
- No greetings or sign-offs ("Hey team", "Hi all", "Thanks!"), no chitchat, and don't open with "This PR".
- No emoji, or at most one when it carries meaning.
- No jargon dumps: no file lists, function names, diff stats or strings of ticket ids. One ticket id is fine.
- Don't add the link or the title. pr-pulse appends "<url|repo#N: title>" on its own line.
- Slack mrkdwn is fine for one *bold* phrase or a `code` term. No headings, no bullet lists.

Example announcement text:
Contract exports now follow org-level access rules, so people only see contracts from orgs they belong to. No migration needed, and existing exports keep working.
