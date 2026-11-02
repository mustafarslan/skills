# spm — super-project-manager

**Interactive skill: no silent leaks — the PM decides every flagged item.**

A Claude Code skill for writing requirements that engineering can build and test, without
telling engineering how to build them.

## Install

1. Unzip `spm.zip` anywhere.
2. In a terminal, run `sh spm/install.sh`.
3. Start a new Claude Code session.

The installer needs `python3` and `git`. It adds three things under `~/.claude/`: the skill, a
reviewer agent (`spm-red-team`), and a small hook that loads spm when you type "spm". Your
previous `settings.json` is backed up next to it. Run the installer again to update. An update
replaces the installed skill folder, so any edits you made there are lost. To remove spm, run
`sh spm/uninstall.sh`.

## Use

Type `/spm`, or write "spm" anywhere in a request, for example *"spm: approvals by email"*.

spm writes the spec in the agile shape, with you, one section at a time:

1. **Epic:** the problem, why now, the hypothesis, success measures, and constraints of the
   users' world
2. **World:** fictional tenants, people, documents, values and glossary
3. **User stories:** "As a …, I want …, so that …", each with acceptance criteria and a *Done
   when* line
4. **Design input:** only if you bring material from a UI/UX designer
5. **Examples:** dummy data, expected outcomes and *must not* lists for each story
6. Open questions
7. Leak checks
8. Your approval
9. A branded HTML/PDF copy

It asks you whenever something needs a decision: numbers, boundaries, priorities, scope, names.
It never fills those in on its own, and anything you skip becomes an open question. Its
questions are about the problem and the expected behaviour, never about how to build it.

## What the spec says, and what it never says

It says:
- what the problem is;
- what users expect;
- how the product behaves, as people and outside systems see it;
- what done means.

It never says how the product is built or designed: no technology, architecture, data,
screens, layout, clicks, or exact on-screen wording.

There are two exceptions:
- **A constraint of your users' world**, recorded with the reason. For example, "approvers don't
  sign in; they read email every day" is what makes "email" allowed.
- **Material from a UI/UX designer**, which goes in `design-input.md` with the designer named as
  its source.

## What you get

All of it goes in a folder you choose:
- `intent.md`, the epic;
- `world.md`;
- `stories.md`;
- `scenarios.md`;
- `design-input.md`, if you brought designer material;
- `decisions.md`;
- `inputs/`, with raw files shaped the way a customer would send them.

The rendered copy goes to a second folder you choose, outside the repo. Your own ideas about
*how* to build something go in `ideas-for-engineering.md` in that second folder. They are kept
out of the spec and never handed over with it. spm never commits or pushes anything.

## The leak checks

spm checks the spec four ways:
- the writing rules it follows;
- a checker that flags code-like words, technical vocabulary, screen and click words, channels
  not declared as constraints, and names of real code in the repo;
- a guard that stops it saving a spec file that still contains any of these;
- two reviewer passes that try to solve your spec in different ways and report every place where
  the spec had already decided for them.

When something is flagged, you choose what happens to it:
- rewrite it as behaviour;
- move it to `ideas-for-engineering.md`;
- keep it, as a constraint with its reason, a term your customers really use, or designer input.

**What spm promises: no silent leaks. You decide every flagged item.**
- Technical, code and UI wording never reaches a spec file outside designer input. This is
  certain.
- Every flagged item has your decision, recorded in `decisions.md`.
- A solution hidden in plain business words is a judgment call. The two reviewer passes and an
  engineer's review catch it. That is strong, but not certain.

## For engineering

Engineers get `spm-verify.zip`: the checker, its sha256, and a one-page `VERIFY.md`. Before you
promote a pack, run `check_spec.py --approve <pack-folder>` from inside the repo. `READY` means
the record is complete and consistent. It does not prove the red team really ran, because your
session writes those reports. `VERIFY.md` has the prompt an engineer can use to re-run that pass
independently.

## Good to know

- The guard stays on for the rest of the session once spm is loaded. Use a new session for
  anything else.
- A styled copy is optional. If the `design-doc` skill is available, spm asks whether to use it;
  otherwise it asks whether to render plain HTML or skip it.
