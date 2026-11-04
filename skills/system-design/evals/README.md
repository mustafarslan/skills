# system-design evals

The script tests (`tests/`) check the calculator and the gate. This folder checks the
**behaviour** the standing rules exist to produce, compares the skill with no skill, and catches
regressions when the skill or the model changes.

## Running

`claude plugin eval` needs a plugin with a `plugin.json`, and the repository root is a
marketplace, so build a one-skill plugin first. Runs are real, billed model sessions; each design
case also runs the reviewer subagent (a smoke run cost about $11 for 10 runs on 2026-11-04).

```bash
skills/system-design/evals/make-eval-plugin.sh /tmp/sd-eval     # outside the repo
cd /tmp/sd-eval
claude plugin eval . --tag smoke --runs 1 --allow-tools Write Edit Bash Agent \
  --scaffold --no-publish                                          # per change
claude plugin eval . --allow-tools Write Edit Bash Agent --scaffold --no-publish   # release: 3 runs
```

- `--scaffold` runs each case's `place-files.sh`, which only copies the case's `files/` into the
  run directory.
- The default `--ablation with-without` adds the no-plugin baseline arm. Each run gets a
  temporary home, so a copy in `~/.claude/skills` reaches neither arm.
- `--no-publish` keeps the HTML report local (otherwise it is published to claude.ai).
- `--keep-temp` keeps each run's workspace (sealed read-only) when you need to read the doc it
  wrote. Copy files out; run nothing inside it.
- agy cannot run inside an eval (the temporary home has no verified gate), so the skill reports
  `AGY_FAILED` there; that is expected.

**Cases are generated.** `gen_evals.py` holds every prompt, expected outcome, grader and input
file; edit it, then regenerate (`find evals -mindepth 1 -maxdepth 1 -type d ! -name results
-exec rm -rf {} +` and `python3 -I evals/gen_evals.py evals`, from `skills/system-design/`).

**Graders.** An `llm` grader with `focus: trace` sees only the first and last 12 messages, so it
cannot judge a doc written mid-run. Design prompts therefore name the doc path, and graders
about the doc's content use `focus: { source: file, path: docs/design/<name>.md }`. Process
checks use `tool_used` (ran the calculator, read a reference, no subagent mid-interview) and
`file_exists`.

Results go to `results/<date>/`. Read the failing runs yourself, plus `expense-tool-small-team`
every time: LLM judges favour longer answers, and that case rewards restraint.

## Traceability: every rule has a case, every case has a reason

| Rule / phase | What it claims to fix | Eval case(s) | Gate check |
|---|---|---|---|
| R1 frame first | boxes before scope, non-goals and numeric NFRs | `vague-notification-system`, manual M1 | NFR numbers, non-goals |
| R2 numbers from the script | numbers from the head; guesses unlabelled | `url-shortener-capacity`, `rag-support-assistant`, `chat-storage-hot-partition` | estimation labels inputs and cites the calculator |
| R3 boring by default | over-engineering for small teams and loads | `expense-tool-small-team` | - |
| R4 trade-off rows with real triggers | vague or strawman "change it when" | `url-shortener-capacity`, `chat-storage-hot-partition` | units, word boundaries, `--calc` strawman / already-fired |
| R5 make the decision | options without a choice | `queue-choice-deep-dive` | - |
| R6 push back with numbers | silent compliance with a breaking steer | `ledger-cache-steer`, `ledger-cassandra-steer` | - |
| R7 say what the user sees | "eventual consistency" with no window | `flash-sale-inventory`, `review-seeded-defects` | staleness window |
| R8 name what breaks first | good-day-only designs | `chat-storage-hot-partition`, `url-shortener-capacity` | `--scale` path |
| R9 load references just in time | reading every reference up front | `partition-orders-deep-dive` | - |
| Phase 3 contracts and data | no idempotency keys; keys before access patterns | `order-payment-idempotency` | - |
| Phase 4 build or buy | building commodity components | `webhook-delivery-platform`, `expense-tool-small-team` | - |
| Phase 6 skew and cascades | right on average, wrong on the whale | `chat-storage-hot-partition`, `flash-sale-inventory` | numeric RPO/RTO |
| Phase 7 cross-cutting | tenant isolation and deletion gaps | `b2b-saas-tenant-deletion` | - |
| AI pack | RAG without permissions, sizing or evals | `rag-support-assistant` | - |
| Client pack | offline sync and version skew ignored | `offline-first-field-app` | - |
| Brownfield | big-bang rewrites | `monolith-split-brownfield` | - |
| Review mode | missing real defects, or inventing them | `review-subtle-defects`, `review-seeded-defects` | - |
| ADR immutability | rewriting an accepted ADR | `accepted-adr-superseded` | - |
| Interview mode | no time boxes; reviewer mid-round | `interview-candidate-rate-limiter` | - |

A rule with no case is untested. A case that maps to no rule or phase is probably testing the
model's general knowledge, not this skill.

## Smoke and holdout

- **smoke** (5 cases: `url-shortener-capacity`, `expense-tool-small-team`,
  `chat-storage-hot-partition`, `ledger-cache-steer`, `review-subtle-defects`): run on every
  change. The two subtle cases replaced `ledger-cassandra-steer` and `review-seeded-defects` in
  the smoke set on 2026-11-04, because the model without the skill already passed those; the
  originals stay as regression cases.
- **holdout** (`webhook-delivery-platform`, `offline-first-field-app`,
  `vague-notification-system`, `interview-candidate-rate-limiter`): never edit the skill to make
  one of these pass. Read their failures only to decide whether a general fix is needed, then
  confirm that fix on the other cases first.

**Shipping rule:** no holdout grader that passed 3/3 may drop, and no smoke grader may drop by
more than one run.

## Trigger evals

`trigger-evals.json` holds 18 queries, including near-misses from this repository (`spm`,
`design-doc`, `pr-review`). Two are deliberate judgment calls kept as should-not-trigger:
"write interview questions" (writing questions, not designing) and "explain consistent hashing"
(knowledge the model has without the skill). Run them with skill-creator's description
optimizer, or by asking a fresh session which skill each query would load.

## Manual checklist (what headless runs cannot see)

| ID | Check | Pass when |
|---|---|---|
| M1 | Ask for "a notification system" and nothing else, interactively | asks 3-5 high-leverage questions, stops before topology, resumes cleanly |
| M2 | Interviewer mode, live | time callouts, probes the weak spot, scores with the sheet afterwards |
| M3 | agy present and working | findings tagged `agy`, kept separate, verified before acting |
| M4 | agy quota or auth failure | says which failure; never presents a failed review as clean |
| M5 | `--html` | renders the diagram; no external fetches |
| M6 | Phase loop-back | give a fact that invalidates phase 4 mid-design; it says "back to phase N" |

## Ablation and pruning

1. **Rules.** For a standing rule, copy the skill with that rule deleted and run the cases
   mapped to it, with and without the rule. Delete the rule only when no mapped grader drops
   and the traces show the behaviour unprompted; otherwise keep it.
2. **References.** Tag each section K (textbook knowledge) or T (trap, default, threshold,
   forcing question). Remove the K sections, run the smoke set, and compare the **total**
   graders passed across all cases (one aggregate is far less noisy than per-case results at
   one run each). Bisect only if the total drops.
3. Record every run under `results/` and repeat after each major model release.

## Where new lessons go

Standing rules stay at about ten. A lesson for one phase or topic goes into the `## Traps`
section of the reference loaded for it:

```markdown
### <the lesson as an instruction>
**Seen in:** eval `<case>` (<date>, baseline n/N, with fix n/N)
**Mistake:** what the run did.
**Instead:** what to do.
**Why:** the mechanism.
```

The "Seen in" line ties each trap to the eval that justifies it, so a trap whose eval no longer
fails without it can be removed. When `retro` finds the same correction twice in real sessions,
write it as a failing case here first, then the trap.
