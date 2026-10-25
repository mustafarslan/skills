# Second opinions: reviewer, advisor, agy

Up to three outside voices can check a run. They are **critics of the plan and auditors of the ledger, never data sources**. A number from any model is a lead to verify, never a claim.

| Voice | Available | When | Model |
|---|---|---|---|
| `cure-reviewer` agent | Cowork and Claude Code (the plugin ships it) | Full depth: after scoping (sizing only) and before publishing (both flows) | Sonnet 5.5, high effort (from the agent file) |
| `cure-buyer-skeptic` agent | Cowork and Claude Code | Full depth, before publishing, in parallel with the reviewer and blind to it | Fable 5.1, high effort; reads the ledger and draft only, never searches |
| `advisor` tool (optional) | Claude Code only, when the tool is listed | Called by the Opus orchestrator only, after scoping and before publishing; subagents never call it | Set by the user, not by this plugin: `advisorModel: "fable"` makes it Fable 5.1 |
| agy (optional) | Only in Claude Code where an `agy` skill is listed, **and** only when the operator said "agy" (intake question 7) | After scoping, as a critic of `roster.md` or `entity.md` plus the research plan | Gemini Flash by default; `--big` and `--boost` only on the operator's own words |

## Using agy

1. Invoke the `agy` skill and follow it. It owns the brief discipline, `--cwd`, timeouts, `--big`/`--boost`, and failure handling (`AGY_UNAVAILABLE`, `AGY_QUOTA` and so on).
2. Point `--cwd` at the run folder so agy reads `roster.md` or `entity.md` from disk.
3. Write the brief to `agy-brief.md` and its answer to `agy-answer.md` in the run folder.
4. Ask agy for:
   - what is wrong or missing in the scope;
   - which companies, subsidiaries or signals were missed;
   - which classifications are wrong (competitor, partner, HQ decides).

   Tell it any figure it gives is a claim to be verified.
5. Use its gaps to add research. **Never use its figures** without a ledger row from a real source.
6. If it fails, say which failure happened in one line in the report's second-opinions section. Never present a failed review as a clean one.

## If a voice is unavailable

- **`cure-reviewer` can't be spawned** (plain Desktop chat): run the review checklist in SKILL.md §4 yourself, and say in the report "Review: self-check (no reviewer agent on this surface)".
- **The Fable model isn't available** on the operator's seat and the skeptic falls back: say which model it ran on.
- **No advisor (Cowork, Desktop chat):** the Fable skeptic reviews only what it is handed (the ledger and draft). An advisor would see the whole run, so say "Fable review" in the report, not "Fable advisor".

## Reporting

The report's **Second opinions** section keeps each voice apart, in this order:
1. reviewer;
2. buyer skeptic (headed "simulated buyer view: opinion, not evidence"; every statement cites `E<n>` IDs or is phrased as a question);
3. advisor, if it ran;
4. agy, if it ran;
5. Claude's own read.

Each gets 2–5 bullets: what it changed, what it disputed, and where the voices disagree (e.g. "volume" vs "winnable"). Never blend the voices into one paragraph.
