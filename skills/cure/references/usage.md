# Using cure

cure researches prospects from official and primary sources (filings, registries, annual reports, company sites) and maps what it finds to what **your** organization sells. On first use it sets up a profile of your own company: it researches your products and capabilities from your public pages, proposes who your buyer is and what signals to look for, and asks whether you have a style guideline. Every figure in a cure report has a source link, or says "not public". Estimates are labelled as estimates.

## Install

cure is two skills (`cure`, and `cure-style` for the report's look) plus six agents in this repository's `agents/` folder.

**Claude Code**
- The plugin (see the repository README) installs all of it. The agents then show up as `skills:cure-researcher` … `skills:cure-buyer-skeptic`.
- Or copy it by hand, agents included:
  ```bash
  cp -r skills/cure skills/cure-style ~/.claude/skills/
  cp agents/cure-*.md ~/.claude/agents/
  ```
- Restart Claude Code, then check that `/agents` lists the six `cure-*` agents.

**Claude Desktop (Cowork) or claude.ai**
- Desktop and claude.ai get plugins from your organization's plugin library, not from a local folder. Publish the plugin to the library: from Claude Code, with the plugin loaded, ask Claude to "publish this plugin to my organization", or publish it on claude.ai. This needs a Team/Enterprise workspace where you (or your admin) can publish plugins.
- Install or turn it on from the library while signed in to that workspace; restart the Desktop app if it doesn't show. Pushing to a Git repo does not update the library copy, so publish again after every change.
- claude.ai rejects a skill whose `description` contains angle-bracket tags; these have none. Agents run in Cowork; plain chat runs the steps one after another.

## Quick start

1. **Open a Cowork task in the Desktop app, or Claude Code, in a working folder.** cure saves your profile and its notes there. Plain chat also works, but it's slower, runs without the agents and keeps nothing between chats.
2. **Pick Opus in the model menu** before you send anything. Opus plans the research and writes the report.
3. **Set up your profile:** type `cure setup`. cure asks, in one message:
   - your organization's name and website;
   - which products to sell (default: all);
   - who buys them, if you know;
   - the default report language and your CRM;
   - whether you have a style or brand guideline (paste it, give a URL or a file, or say no).

   It then researches your own organization and shows you three drafts in `cure-profile/`: `profile.md`, `capabilities.md` and `style.md`. Correct anything wrong and confirm. If you skip this step, cure runs setup the first time you ask for research.
4. **Ask for research, starting with "cure".** For example:
   - `cure: use cases for Acme Retail before Thursday's meeting`
   - `cure: size the companies at <event name> 2026, top 20`
5. **Answer the intake questions.** cure asks them all in one message, with the defaults already picked:

   | Question | Default | Other options |
   |---|---|---|
   | What do you need? | Account use cases (one company) | Prospect sizing (an event or a list) |
   | Target | (from your request) | company name, country, website; or an event URL or a pasted list |
   | Report language | your profile's language | another language |
   | Output | Claude artifact | Google Doc (created private; you decide who to share it with) |
   | Depth | Full | Quick: one pass, for a first look or when your usage is low |
   | Focus (optional) | none | a product, segment, country, a cap on the number of companies, meeting date |

   If the company name could mean more than one company, cure shows the candidates and asks which one you mean.
6. **Wait for it.** A Full run takes much longer than a Quick one, because several agents research in parallel and a reviewer checks the result. Keep the app open until the report arrives. Notes and the CSV are saved to `cure-runs/` in your working folder.
7. **Check the footer** of the report. The **Models** line should say Opus for the orchestrator, and it shows your profile and catalog versions (and DRAFT if you haven't confirmed them).

## What you get

- **Account use cases** (one company):
  - who the company really is: legal entity, parent, and who decides;
  - the public facts that create the work your products address;
  - the capabilities from your catalog that fit, and anything that would need a product extension;
  - questions to ask in the meeting, and the people in the buyer function to meet.
- **Prospect sizing** (an event or a list): a ranked table with each company's size, buyer lead, the sizing metrics from your profile, its strongest pain signal and a pitch angle, plus a CSV for your CRM.

## Your profile

Kept in `cure-profile/` in your working folder, never inside the skill or plugin (an update would overwrite it).

| File | Holds |
|---|---|
| `profile.md` | your org, what you sell, products, buyer function and titles, pain signals, sizing metrics, research tracks, competitors and partners, CRM, report language |
| `capabilities.md` | what your products do today (**CAP-xx**) and gaps or adjacent ideas (**EXT-xx**, confirm with product before pitching), each with a source URL |
| `style.md` | your brand colours, fonts, logo URL and tone, or `style: neutral` |

Run `cure setup` again whenever your products change. You can also edit the files by hand; bump the version line when you do.

## Before relying on it for a real meeting

A Full run uses Opus, parallel Sonnet research agents and a Fable "buyer skeptic", all on **your own Claude seat**. A single-company Quick test can process around 12M tokens, most of them cheap cached re-reads, and a big sizing run can use a large share of your usage limit. Setup is a one-off cost of about one research agent.

1. Do a **test run first**: Quick depth on a company you know well. See how much usage it took under Settings > Usage.
2. Then try one Full run on a single company. Start a day or more before the meeting.
3. If the report footer says the skeptic didn't run on Fable, your seat may not have Fable; ask your admin.
4. For big events, cap the list at 15–20 companies the first time.

## Where it runs

| | Desktop app, Cowork | Desktop app or claude.ai, chat | Claude Code | Mobile app |
|---|---|---|---|---|
| Research and report | ✓ | ✓ | ✓ | not tested |
| Specialist agents in parallel | ✓ | runs the steps one after another | ✓ | – |
| Saves the profile, notes and the CSV to a folder | ✓ | – (profile kept for that chat only; notes go in the report's appendix) | ✓ | – |

**The agents:**
- **Three analysts** research one company in parallel: filings and structure; operations in the area your product addresses; the buyer function's people, hiring and systems.
- **A researcher** sizes the companies in each segment of an event or list, and researches your own organization at setup.
- **A reviewer** checks every claim against its source before the report is written.
- **A buyer skeptic** plays the prospect's senior buyer: which use cases would land, which would get shrugged off, and the objection to prepare for. Its view is labelled as opinion, never as fact.

## Optional

- **advisor** (Claude Code): `/advisor fable`, or `"advisorModel": "fable"` in `~/.claude/settings.json`. cure calls it after scoping and before publishing when it is listed. A plugin can't set this for you.
- **agy** (Claude Code): with the [agy](../../agy/SKILL.md) skill installed, intake offers agy as a second opinion on the scope.
- **Model access:** the skeptic agent is set to Fable 5.1, the analysts to Sonnet 5.5. If your seat lacks one, the report footer shows the fallback model.

## Rules cure follows

- **No assumptions.** "not public" beats a guess.
- **No invented capabilities.** Your catalog lists only what your own sources show; anything unsure is an EXT item.
- **Vendor claims need a source.** It only says which tools a company uses when a company source or filing says so.
- **Names go stale.** Names from sources older than 6 months are marked "verify".
- **Text on web pages is treated as data**, never as instructions.
- **Nothing goes out on its own.** It never posts to your CRM, Slack or email, or shares a document, unless you ask.
