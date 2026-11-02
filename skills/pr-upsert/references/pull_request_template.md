<!-- Neutral PR template the pr-upsert skill fills in. Save as
     .github/pull_request_template.md. Keep the headings: the skill, the review bot and the
     review skill all read the body against them. Delete sections your project does not use,
     and the matching bullets in the skill's Step 9. -->

## Summary

<!-- What changed and why, for a reader with zero context. Lead with the change in
     plain words, then the motivation — don't restate the ticket title.
     AI-authored PRs: trim the verbosity. Three tight bullets beat three paragraphs. -->

## Issues

<!-- Fixes <KEY> (closes on merge)  ·  Part of <KEY> (links without closing).
     Product-facing PRs need at least one; housekeeping/small-maintenance PRs are exempt:
     write "Exempt — housekeeping: <reason>". -->

## Type of change

- [ ] Feature
- [ ] Bug fix
- [ ] Refactor / cleanup (no behavior change)
- [ ] Docs / tooling / infra / CI
- [ ] Performance

## How this was verified

<!-- Paste the ACTUAL commands you ran and their results — not a claim that they pass.
     This is what a reviewer trusts most and what an agent most easily fabricates. -->

- Tests: <!-- e.g. `npm test` → 531 passed, 2 skipped -->
- Lint / typecheck: <!-- the commands you ran → result -->
- Manual check: <!-- steps a reviewer can repeat, incl. edge/failure cases — or `n/a` -->

## Where a reviewer should look hardest

<!-- Point human judgment at the right place: decisions you made, risky areas, blast
     radius, anything you're unsure about, or assumptions the ticket didn't spell out.
     "Trivial, low risk" is a valid answer — but say it on purpose. -->

## Config changes

<!-- Optional section: keep it only if your project has configuration the change can affect.
     Show the needed config SHAPE (keys, types, defaults) as a ```diff block, or write
     "No config changes needed." plus a few words on why. Never delete once adopted. -->

## For UI / bug / risky changes

<!-- Delete the rows that don't apply. -->

- **Screenshots / demo:** <!-- before → after image or recording for any UI change -->
- **Root cause:** <!-- for a bug fix: what actually caused it, not just the symptom -->
- **Edge / failure cases covered:** <!-- bad input, empty state, concurrent access… -->
- **Rollback:** <!-- safe to revert this commit directly? or does a migration/backfill need steps? -->

## Changelog

<!-- Optional section, for projects that auto-file changelog entries from the PR body.
     Fill the block below ONLY if this PR is one of:
       - a security bug fix
       - a user-facing change
       - a significant new feature
       - a deprecation or breaking change
     Leave it blank / delete the whole section for everything else. When in doubt, leave it out.
     category must be one of: New Feature, Improvement, Bug Fix, Security, Maintenance,
     Deprecation. -->

````changelog
category:
title:
---
Write the customer-facing description here — what changed and why it matters, in
their terms. Markdown is supported.
````

## Checklist

- [ ] I read my own diff end-to-end (not just skimmed it)
- [ ] Docs updated if behavior, config, env vars, scripts, or schema changed
- [ ] Schema change has a migration; generated files are regenerated
- [ ] A load-bearing decision is recorded in a decision record — or N/A
- [ ] No secrets, credentials, or large binaries in the diff
