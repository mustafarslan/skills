# Intake: ask every run

Setup (`setup.md`) runs first if there is no seller profile. Then ask these in **one** message, with the defaults pre-selected. Use a multiple-choice question tool if the surface has one; otherwise a short numbered list. Never skip intake because a past run used certain answers: the operator may change their mind.

| # | Question | Options (default first) |
|---|---|---|
| 1 | What do you need? | **Account use cases** (one company) · **Prospect sizing** (an event or a list of companies) |
| 2 | Target | Use cases: company name, plus country and website if known. Sizing: event URL or name and edition, or a pasted or attached list |
| 3 | Report language | **the profile's `report_language`** · English · other |
| 4 | Output | **Claude artifact** · Google Doc (created private; sharing is your call) |
| 5 | Depth | **Full** (parallel research, reviewer pass) · Quick (one pass, fewer searches; for a first look or a low usage budget) |
| 6 | Focus (optional) | A product from the profile, a segment, country, business unit, a cap on the number of companies (sizing default 30), or a meeting date to prepare for |

**Only when running in Claude Code and an `agy` skill is listed**, add:

| 7 | Second opinion from agy? | **No** · agy · agy big · agy boost · agy big boost |

Map the answer to flags only as the operator worded it. "big" means `--big` and "boost" means `--boost`; never add either on your own.

## Rules

- **If the operator already answered something in their request**, pre-fill it and show it as the default; still ask the rest.
- **If a profile file is DRAFT**, add one line to the same message: "Your profile is still a draft. Confirm it now, or run on the draft?"
- **For use cases, if the company name is ambiguous**, don't guess. Show the candidates (legal name, country, website) and ask which one they mean before researching. See `entity-resolution.md`.
- **Write the answers to `brief.md`** in the run folder before research starts (see the run folder in SKILL.md), with the profile and catalog versions used.
