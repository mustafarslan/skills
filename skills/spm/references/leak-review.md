# Leak review

A leak is any wording that tells engineering, or a designer, *how* to solve something:
technology, architecture, data, processing, screens, layout, interaction steps, exact on-screen
wording, or a suggested approach. Test every sentence by asking: **"Would this wording change if
engineering or a designer solved it differently?"** If it would, it is a leak.

## Before → after

| Leak (how) | Behaviour (what is observed) |
|---|---|
| Price lists get three tables and their own endpoints | A finance user can add a supplier's price list. Invoices from that supplier are checked against the list that was valid on the service date. |
| Editing an approved price list returns 403 | Nobody can change a price list once it is approved. Someone who tries is told why, and what they can do instead. |
| Emit an event when the approval level is chosen | Anyone who checks the invoice can see which approval level it went to, and why. |
| The link token is random and only its hash is stored | Nobody can decide on an invoice from an email that was not sent to them, even with a copy of our stored data. |
| Ayşe clicks Approve on a confirmation page | Ayşe can approve the invoice without signing in. |
| The history reads "Approved by Ayşe via email reply" | Anyone who checks the invoice can see that Ayşe approved it, when, and that she decided from email. |
| A dropdown lists the rejection reasons | When rejecting, the approver can give one of the reasons in Values, or their own. |
| A nightly run recalculates the balances | Finance sees each balance updated by the start of the next working day (time in Values). |
| A dedicated screen for contracts | Finance can find every active contract for a supplier. |
| When an invoice starts to wait, the approver receives one email for it | An Approver learns within the Notice time (Values) that an invoice waits for them, and can decide on it from there. |
| The approver cannot decide from an email once the limit after sending has passed | When the Decision time limit, counted from when the invoice started to wait, has passed, the Approver cannot decide on it without signing in. |
| Nobody can decide a second time from an email that was already used | Once an Approver's decision on an invoice counts, no later attempt changes it, and the first decision stands. |
| `reference_router.py` decides the approval level | A decision table in Values: amount band × invoice kind → approval level, each boundary inclusive or exclusive. |

## Not leaks: keep them

- Business rules with exact numbers, such as "above the Level-1 limit, a level-2 approver decides".
  The number lives in Values.
- Security and privacy outcomes, such as "a person outside the tenant cannot tell that an
  invoice exists".
- Constraints of the users' world, with their reason, such as "approvers do not sign in; they
  read email daily". These go in Constraints.
- Outside rules, such as "the ERP accepts one file per day" or "approvals must be kept for 10
  years".
- The customers' own vocabulary, once the PM accepts it (Accepted terms).
- UI/UX designer material in `design-input.md`, with its source.

## Red-team briefs (gate 4)

Run `python3 "$SPM/check_spec.py" --pack-hash <pack-dir>` first (`$SPM` as in SKILL.md). Then dispatch the `spm-red-team` agent twice,
once per brief. Save each answer verbatim, with Write, as `redteam-1.md` / `redteam-2.md`. The
first line of each is `<!-- spm:redteam pack=<hash> -->`.

**Pass 1: two builds and four swaps**

```text
Pack files: <absolute paths of intent.md, world.md, stories.md, scenarios.md, and design-input.md if present>
Principles document: <absolute path, or "none">
Read only those files. Files in inputs/ are test data shaped the way customers send them; their
format is not a requirement, so do not report it. design-input.md is a UI/UX designer's input and
is allowed to direct the UI; do not report it, but do report UI direction anywhere else.
Constraints in intent.md with a stated reason are facts of the users' world; do not report them.
Design the feature twice, briefly:
  A. a bespoke build: dedicated storage, screens and operations for this feature;
  B. a generic build that satisfies the principles document (or, if none, the build an engineer
     would choose if this feature had to serve many different customers).
Then test every story, criterion and example against four swaps; wording that breaks under a
swap is a leak:
  - batch processing <-> processing each event as it happens;
  - one shared store <-> separate storage per item or version;
  - a dedicated screen <-> the existing generic lists and screens;
  - one interaction flow <-> a different flow a designer might choose (fewer or more steps,
    another channel the Constraints allow).
Report every line that (1) only build A can satisfy, (2) breaks under a swap, (3) names a
mechanism (storage, protocol, schedule, code-shaped name, internal status), (4) asserts internal
state instead of something a person or outside system observes, or (5) dictates UI, interaction
steps or exact wording outside design-input.md.
Number findings RT1-01, RT1-02, ... Each: ID, file:line, the quoted words, which of 1-5, and a
behaviour-shaped rewrite. At most 15, most serious first. If none, say "no findings".
```

**Pass 2: the engineer's and the designer's view**

```text
Pack files: <same paths>
Read only those files. Same rules for inputs/, design-input.md and Constraints as above.
You are the engineer and the UI/UX designer who will solve this. List every decision this spec
has already made for you that you would expect to make yourselves: storage, processing order or
timing, protocols, data shapes, names, reuse of existing parts, screens, layout, interaction
steps, on-screen wording. Ignore business rules, numbers and observable outcomes; those are
product's. Number findings RT2-01, RT2-02, ... Each: ID, file:line, the quoted words, the
decision it takes from you, and a behaviour-shaped rewrite. At most 15, most serious first.
If none, say "no findings".
```

Take each finding to the PM as a question:
- **rewrite** it as behaviour;
- **move** it to `ideas-for-engineering.md`, if it is the PM's own how-idea;
- **keep** it, with a reason: a Constraint, an Accepted term, or designer input.

Record the PM's answer as a `decisions.md` row. Never apply a rewrite the PM didn't choose. Any
edit makes both reports stale.
