# `check_spec.py` — what it must do

`skill/scripts/check_spec.py` is the machine half of spm. A working, sanitized copy sits in
`skill/scripts/check_spec.py`, with the passing tests in `tests/test_check_spec.py`. If you rebuild
it from scratch, this document is the behaviour contract, and **the test file is the acceptance
suite**: your rebuild is right when
`python3 -I -m unittest discover -s skills/spm/tests` passes (the script is at `skills/spm/scripts/`,
the trigger hook at `skills/spm/hooks/spm-trigger.py`).

Standard library only. Python 3.9+. One file.

## Why it exists

The skill's prompt tells the model "never write solutions". A prompt alone is not a guarantee, so
the script enforces the part that can be enforced by code, **on the output side**:

- It runs as a skill-scoped `PreToolUse` hook on `Write|Edit|MultiEdit|Bash`, so a leaky pack
  file cannot be saved at all.
- It runs as a command (`<pack-dir>`) so the model and the PM can see every finding.
- It runs as the final gate (`--approve`) so engineering can check the record is complete.

The promise is **"no silent leak"**, not "zero leaks". Wording that hides a solution in plain
business language cannot be caught by regex; the two red-team passes and the engineer's review
catch it. Say that exactly, in the skill and in the README.

## The four modes

| Command | Behaviour | Exit |
|---|---|---|
| `check_spec.py <pack-dir> [--repo <git-root>] [--json]` | Check every pack file that exists. Print `file:line [kind] text - message` per finding, then `N finding(s); repo cross-check: <repo or "not in a git repo">`. `--json` prints a JSON list of findings instead. Repo defaults to the git root of the current directory, else of the pack folder. | 0 clean, 1 findings, 2 usage error or no pack files |
| `check_spec.py --approve <pack-dir>` | Final gate. Prints `NOT READY: <problem>` lines, or `READY: pack <hash> is clean, red-teamed twice, every finding decided, approved by product.` Warns if not inside a git repo (the repo cross-check was skipped). | 0 ready, 1 not ready, 2 not a folder |
| `check_spec.py --pack-hash <pack-dir>` | Print the 16-hex-char pack hash. | 0 |
| `check_spec.py --hook` | The `PreToolUse` hook: reads the tool call as JSON on stdin; see "The hook". | 0 allow or deny-JSON, 2 fail closed |

## Pack files, marker, hash

- `MARKER = '<!-- spm:draft'`.
- `PACK_FILES = intent.md, world.md, stories.md, scenarios.md, design-input.md`.
- `REQUIRED_FILES = intent.md, world.md, stories.md, scenarios.md`.
- `decisions.md` and `redteam-N.md` are **records**: not content-checked (they quote flagged
  words), but the hook guards them against Bash writes, and `--approve` reads them.
- **Pack hash** = first 16 hex chars of SHA-256 over, for each pack file in `PACK_FILES` order that
  exists: `name + NUL + text(with CRLF→LF) + NUL`. Any edit to any pack file changes the hash.
  `decisions.md`, red-team files and `inputs/` are not hashed.

## What a finding is

`Finding(file, line, kind, text, message)`. Kinds in use: `backticks`, `snake_case`,
`SCREAMING_CASE`, `CamelCase`, `camelCase`, `call`, `operator`, `url-path`, `http`, `header`
(code shapes), `code-block`, `tech-word`, `mechanism`, `ui`, `ui-copy`, `channel`, `constraint`,
`actor`, `story`, `incomplete`, `duplicate-id`, `constant`, `contradiction`, `design-source`.

## Checks, per file

| File | Checks that run |
|---|---|
| every pack file | code shapes (`SHAPES`), code fences outside the allowed set, `TECH_WORDS` |
| `design-input.md` | the above, plus `design-source`; **nothing else** (UI design is allowed here) |
| every other pack file | + `mechanism_findings` + `ui_findings` |
| `intent.md`, `stories.md`, `scenarios.md` | + `channel_findings` |
| `intent.md` | + `constraint_findings` |
| `stories.md`, `scenarios.md` | + `actor_findings` |
| `stories.md` | + `story_findings` |
| `intent.md`, `stories.md` | + `number_findings` |
| `scenarios.md` (full-pack mode only) | + `scenario_findings` (duplicate IDs; each scenario has Given, When, Then, Must not, an outcome table) |
| `world.md` | duplicate Values names with different values → `contradiction` |

Details that matter and are easy to miss:

- **Accepted terms.** In `world.md` only, everything under a heading matching `accepted terms` (to
  the next heading of the same or higher level) is exempt from every check. The same heading in
  any other pack file exempts nothing. Terms listed there (bullet text before
  ` — `, or the first column of a table) also suppress findings for that exact term elsewhere.
- **Fences.** Only fences of language `text`, `csv`, `eml`, `email`, `txt` or none are allowed;
  anything else is a `code-block` finding. Lines inside an allowed fence are raw example data and
  are not otherwise checked, but only in `scenarios.md` and `world.md`. In every other pack file
  they are checked like any other line.
- **Markdown link targets** are stripped before code-shape and tech-word checks.
- **`TABLE_OK`:** the word "table" is fine inside "outcome table", "examples table",
  "constants table", "scenario table", "summary table", "decision table", "this table".
- **Channels** (`CHANNEL_RE`): allowed only when the word (or its singular) is a *settled*
  Constraint or an Accepted term. A Constraint is settled when its "Why" cell is non-empty and has
  no `Q-nn`, "open", "tbd", "todo", or trailing `?`. The `Constraints` and `Out of scope` sections
  are skipped; `inputs/...` file names are blanked out first. An unsettled Constraint row is
  itself a `constraint` finding.
- **Actors** (`REQ_LINE` = lines starting with `**AC-n.m …**` or `**Then**`): strip a leading
  `(Pn)`, strip a leading "When/If/While/…, " clause, cut at the first sentence end. Find the first
  observation verb (`OBS_VERBS`); none → finding. The text before the verb is the subject: if it
  starts with the system/platform/app/…/it/we/they (`BANNED_SUBJECT`) → finding; if it contains no
  quantifier (`QUANTIFIERS`) and no actor from `world.md` → finding. Actors = persona IDs, persona
  names and first names, business roles (column 4), tenant names (column 2), outside-system names;
  matched as whole words, plural `s`/`es` allowed. A capitalised verb-like match that is itself a
  persona name (a persona called "Can") is skipped.
- **Stories** (`STORY_LINE` = `**US-n …**` followed by text): the text must match
  `As a/an <persona>, I want <goal>, so that <benefit>`; the persona must be a known actor. In
  full-pack mode each `### US-n` block needs at least one `**AC-n…**` line and a `**Done when`
  line.
- **Numbers** (`NUMBER_RE`): in prose lines of `intent.md` and `stories.md` (not tables, fences,
  headings or the marker line), every number ≥ 10, every number with `%`, and every `hh:mm` time
  must appear in the Values table in `world.md` (Values/Constants section). IDs like `US-01`,
  ISO or dotted dates, versions `v1.2` and priorities `P0..P3` are blanked out first. Number
  *readings* are tolerant of Turkish (`50.000,00`) and English (`50,000.00`) styles but must not
  widen the match: `50` is not covered by `50.000`.
- **UI** (`UI_RE`): UI nouns and interaction verbs anywhere outside `design-input.md` and
  Accepted terms. `UI_COPY_RE` additionally flags a quoted string of **4 or more words** on a
  requirement or story line (exact on-screen wording); shorter quoted literals count as data.
- **Design input:** each `### D-n` block must contain a line starting `Source:` that names a
  UI/UX designer. Text outside the `D-n` blocks is unsourced, so it gets the mechanism and UI
  checks like any other file.
- **Repo cross-check:** collect identifier-shaped tokens from code-shape findings (snake_case,
  camelCase, long backticked words); `git grep -w` them over source files (`SOURCE_GLOBS`: py, ts,
  tsx, js, jsx, mjs, go, java, kt, rb, rs, cs, php, swift, scala, sql, vue, svelte), at most 300
  candidates, 20 s timeout. A finding whose text contains a token that exists in the code gets its
  message prefixed `NAMES CODE IN THIS REPO - `. If not in a git repo, skip silently in check
  mode and print a WARNING in `--approve`.

## The hook (`--hook`)

Input (stdin JSON): `{"tool_name": "Write|Edit|MultiEdit|Bash", "tool_input": {...}, "cwd": "..."}`.

1. `Bash`: run the **Bash write gate**. Deny if the command redirects (`>`/`>>`) to a path ending
   in a guarded file name, or mentions a guarded file name together with a write operation
   (`tee mv cp rm truncate dd install rsync ln`, `sed -i`, `perl -i`, `write_text`, `.write(`,
   `open(` with a write mode). A guarded name matches only as a whole file name
   (`user_stories.md` and `hello-world.md` are not guarded). One regex over the whole command, no
   shell parsing: a command that writes anything and also names a pack file is denied. Guarded names: `intent|world|stories|scenarios|design-input|decisions` + `.md`, and
   `redteam-N.md`. Deny reason: pack files are written only with Write or Edit, so the leak gate
   checks them.
2. `Write`/`Edit`/`MultiEdit` on a path not ending `.md` → allow.
3. Compute the **file's content after the tool call** (for `Edit`/`MultiEdit`, apply the edits to
   the current file text; if an `old_string` is not found, check the new text anyway).
4. If neither the old nor the new text carries the marker within its first 400 characters:
   - the file name is not one of `PACK_FILES` → allow (not an spm file), so an unmarked
     `ideas-for-engineering.md` is never checked;
   - the file already exists and no other pack file in its folder carries the marker → allow. It
     belongs to some other project (the hook stays on for the whole session, in any repo);
   - otherwise (a new file with a pack name, or one next to a marked pack) → check it. Leaving
     the marker off does not skip the gate, and `--approve` requires the marker everywhere.
5. For a marked/pack file: read `world.md` and `intent.md` from the same folder as **context**
   (personas, values, accepted terms, constraints), run all checks in **non-full-pack mode**
   (no "story needs AC", no scenario completeness, since the file is mid-edit), and keep only the
   findings for the edited file.
6. No findings → exit 0. Findings → print deny JSON and exit 0:

```json
{"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
  "permissionDecisionReason": "spm leak gate: N finding(s) in <file>.\nline L [kind] text - message ... (first 40)\nTake these to the PM with AskUserQuestion (at most 4 per call). For each, offer: rewrite as behaviour ... / move it to ideas-for-engineering.md ... / keep it as a Constraint with the users' reason, an Accepted term, or UI/UX designer input in design-input.md. Never reword only to get past this check."}}
```

7. **Fail closed.** Any exception while checking a marked file, or unparseable stdin → print the
   reason to stderr and exit **2** (which blocks the tool call). The hook command in the SKILL
   frontmatter ends with `|| exit 2` so a crash of the interpreter itself also blocks.

## `--approve` logic

`NOT READY` lines are collected, never short-circuited, then printed. Ready only if all hold:

1. Each required file exists and has the marker in its first 400 characters.
2. A full-pack check (with the repo cross-check) has zero findings.
3. Both `redteam-1.md` and `redteam-2.md` exist, and each contains
   `spm:redteam pack=<hex>` where `<hex>` equals the **current** pack hash (otherwise: "the red
   team reviewed an older version of the pack; run it again").
4. `decisions.md` exists. Its table rows are `| Pack | Finding | Where | Words | Decision | Reason | Date |`.
   Every finding ID `RT<n>-<m>` found in a red-team file, **keyed by (that file's pack hash, ID)**,
   must have a row with the same key (a fresh round restarts at RT1-01, so an old round's decision
   must not cover a new finding).
   - Decision `keep` resolves a finding.
   - Decision `rewrite` or `move` resolves it **only if the row's pack hash differs from the current
     one** (the pack was changed afterwards). If the hash equals the current one, report that the
     decision says the pack changes but it has not, and that a new red-team round (or `keep`) is
     needed.
5. `decisions.md` has a `## Approval` section containing a line `Approved by <name>`.

## Acceptance list

`tests/test_check_spec.py` is the full list (58 tests: the original 43, one for running from a
folder that is not a repo, and 14 from an outside review, in `GlobalUseAndReviewTests`). Grouped by what each proves:

- **Pack mode:** a clean pack has no findings; a leaky story file flags every leak; the same Values
  name with two values is a `contradiction`; incomplete or duplicate scenarios are flagged; a token
  that exists in a real source file in a temp git repo gets the `NAMES CODE IN THIS REPO` prefix.
- **Actors, verbs, mechanisms:** "the system …" as an actor is flagged; a `Then` with no actor is
  flagged; declared personas, outside systems and ID-style actors pass; plain-word mechanisms
  ("its own list and screen", "a nightly run recalculates", "stored separately per supplier",
  "a dedicated page lists", "sync with the ERP") are flagged; a number's alternative readings do not
  widen the Values match (`50` ≠ `50.000`); UI nouns and exact on-screen copy (4+ words) in criteria
  are flagged, short quoted literals are data; a channel word needs a settled Constraint; a
  Constraint with an empty or open reason does not count; `inputs/…` file names are not channels;
  a persona named like a verb works; story-line shape and persona are enforced; a story needs
  criteria and a Done when line; design input needs a designer source; a "Notes for engineering"
  heading is no longer exempt; an unmarked pack file is still checked by the hook.
- **`--approve`:** passes on a complete pack; fails without red team, when the pack changed after
  the red team, with an undecided finding, with an old round's decision covering a new round,
  with `rewrite` in the final round; says when the repo check was skipped; requires stories; fails
  without a marker or approval.
- **Hook:** an unmarked non-pack file is allowed; a marked leaky write is denied; a marked clean
  write is allowed; an Edit is applied before checking; editing Accepted terms is not blocked;
  the stories hook reads Constraints from `intent.md`; `ideas-for-engineering.md` is never
  checked; an error on a marked file fails closed (exit 2); Bash writes to pack files are denied;
  garbage stdin fails closed.
- **Trigger hook:** the words `spm`, `superpm`, `super-project-manager` trigger it (not as part of
  a longer word, and not when the prompt already starts with `/spm`); nothing else does.

## Rebuild order (suggested)

1. Parsing helpers (`section_lines`, `section_text`, `table_rows`) and the code-shape and
   tech-word checks → make `test_clean_pack_has_no_findings` and `test_leaky_stories_flag_every_leak` pass.
2. World parsing (actors, Values, Accepted terms) → actor, number, contradiction tests.
3. Mechanism, UI, channel, constraint, story, design checks.
4. Pack hash, then `--approve`.
5. The hook, last (it reuses everything), with fail-closed behaviour tested explicitly.
