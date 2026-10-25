# Draft PR body template (`--draft`)

For teammates who have never seen a retro. They will only read it if it is short, so:
- Brief, friendly and positive, with no chit-chat or filler. Each bullet is one line.
- Questions as headings, short bullets under each. Skip any section that would be empty.
- Counts and PR/issue refs as evidence. **No names** (patterns, not people), no transcript quotes, no
  customer data, no local paths.
- The user's own top lines go first, verbatim (retro's rule for outward text); everything below is yours.
- End with the PR attribution line the session asks for.

```markdown
<user's top lines, verbatim>

## TL;DR
- <one line: what keeps going wrong>
- <one line: what this PR changes so it stops>
- <one line: what we'd like from you, e.g. "a 👍 or a better idea on the two questions below">

## What did we keep running into?
- <pattern> — <count> times in <A> active days (<since> → <today>), e.g. PR #…, #…
- …

## What changes in this PR?
- `<file or skill step>` — <the change in plain words>
- …

## Why this fix, not another note in the docs?
- <it was already written down in <place> and still recurred, so this makes it automatic / moves it to the moment it matters>

## What else did the retro find?
- <one-liners not in this PR, incl. personal-setup changes, each with its count>

## How will we know it worked?
- The next retro (~2 weeks) re-counts each of these; anything that did not drop is escalated or removed.

## Open questions for you
- <only if there are any; one line each>

## Issue tracker
Housekeeping: developer tooling, no issue.
```

Keep the last section only when `issue_tracker` in the config is not `none`; otherwise drop it.
