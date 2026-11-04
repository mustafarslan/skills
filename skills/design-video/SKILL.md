---
name: design-video
description: The user's house style and pipeline for short videos (8–100 s) — explainers, product walkthroughs, feature clips, release notes, hero loops — in a neutral, achromatic look with one yellow accent. Use when the user says "design-video", or asks to make, storyboard, animate or render such a video and has not named another tool or brand. Takes an idea to a storyboard, an HTML composition in their project and a frame-exact MP4 (Node 18+ and Chrome). Not for editing existing footage or for a project with its own motion or brand guidelines.
---

# design-video — one accent on neutral dark

A skill for short videos (8–100 seconds): explainers, product walkthroughs, release notes,
tutorials, loops. It takes a one-line idea to a storyboard and then to an MP4, and it makes every
video look like it came from the same hand.

It uses the same scheme as `design-doc`: an **achromatic scheme with a chromatic accent**. Every
colour in the frame is a true neutral and exactly one saturated hue, a warm yellow, marks the one
thing the viewer must see. Tokens: `references/tokens.css` (a byte-identical copy of the one in
`design-doc`).

Paths below are relative to this skill's folder, `${CLAUDE_SKILL_DIR}` (the base directory shown
when the skill loads; `~/.claude/skills/design-video` for a copy install). Everything you make —
the storyboard, the composition, stills and MP4s — goes in the user's project or working folder,
never in the skill folder. If the project has its own motion or brand guidelines, those win: ask
before applying this look.

Read, in this order: this file → `references/storyboard.md` before you write the plan →
`references/moments.md` when you design a chapter's visual → `references/diagrams.md` when a
chapter shows an architecture, a flow or a state diagram (use its dark variant, and its
"In a video" sizing) → `references/render.md` when you build, preview and export.
`references/diagrams.md` is a byte-identical copy of the one in `design-doc`, like the tokens.

## Workflow

1. **Brief.** Ask only what is missing, in one message: the story (what the viewer should
   understand), where it plays, and the theme. If the person gives only a topic, propose the
   chapters yourself and ask for a yes or a correction instead of a list of questions.

   | Where it plays | Length | Notes |
   |---|---|---|
   | Website feature page | 45–75 s | full skeleton |
   | Social feed | 20–40 s | autoplays muted: every scene must make sense **without sound**, so headline, body and captions carry the story; hand over the captions with the storyboard |
   | Sales follow-up or launch | 60–100 s | 4–5 chapters |
   | Website hero loop | 8–12 s | no title card, no end card, one moment that repeats; the last frame leads straight into the first |

   Theme: deliver dark and light from one timeline unless they name one. The template is 16:9; a
   vertical video needs its own scene layout (safe areas below) and should be said up front.
2. **Storyboard first.** Write it with `references/storyboard.md` and show it before building:
   a word is easy to change on paper and slow to change once it is animated. If the person is not around to
   answer, do not block: build from your storyboard, list your assumptions, and hand the
   storyboard over with the result.
3. **Build** from the reference composition: `node "${CLAUDE_SKILL_DIR}/scripts/new-video.mjs" <folder>`
   creates `<folder>/index.html` with `motion.js` and `tokens.css` beside it, in the user's project
   (it refuses to overwrite). Keep the structure; replace copy, data and visuals.
   Never edit the template inside the skill folder.
4. **Check stills** before any full render (see Checklist). Fix layout in the composition.
5. **Render** with `node "${CLAUDE_SKILL_DIR}/scripts/render.mjs" <folder>/index.html …`
   (`references/render.md`).
6. **Deliver** the MP4 for each theme, the storyboard, and the composition source, so changing a
   word later does not mean rebuilding. The storyboard is also the voice-over and caption script.

## The rules

### Structure

- **Skeleton, every video:** title card → chapters → end card. The one exception is the website
  hero loop (see the brief table): no title card and no end card, one moment that repeats.
  - **Title card** (≤ 4 s): the topic as a short title and one sentence that promises the result.
    It is the hook: the viewer learns the problem or the result in the first 3 seconds. Never open
    on a logo. Title and sentence must meet the reading-time rule inside the card: a 6-word title
    plus a 4-word sentence fits 4 s; anything longer needs a longer card.
  - **Chapters:** one idea each: 3 chapters up to about 45 s, 4 up to about 75 s, 5 beyond.
  - **End card** (≤ 4 s): one line that names the viewer's next step. An identity mark, if the
    owner has one, may sit here; it is never the first thing on screen.
- **Chapter layout** (16:9): label and headline and one-sentence body on the left; the visual on
  the right; a segmented progress bar along the bottom safe edge (neutral, no accent).
- **Headlines state the result, not the mechanism.** "Pay only for the minutes." not "Our metering
  engine". Chapter labels are one word: a verb or a noun (Scan, Ride, Lock).
- **The end card names the viewer's outcome or next step; the title names the topic.** Do not
  repeat the title at the end.
- **Scene length:**
  - text-only scene: 4–8 s;
  - chapter scene with a visual: 7–9 s, built as about 0.8 s to settle, the reading time of the
    headline, the one moment that animates, then about 1.5 s of hold;
  - never shorter than the reading-time rule (below).
- **One idea per scene, and only one thing changes at a time**, so the eye has one place to go.

### Frame

- **1920 × 1080 (16:9), 30 fps, constant frame rate.** Export 4K by rendering at 2× scale.
- **Stage:** `--dark-bg` (`#0A0A0A`) for the default dark theme; `--bg` for the light theme.
  Panels use `--dark-surface` / `--surface`.
- **Safe areas (16:9):** every piece of text and every logo stays **120 px from every edge** (one
  layout cell). Decoration may bleed.
- **Vertical (1080 × 1920) for feed platforms:** 90 px left and right, **240 px top, 420 px
  bottom**, because platform controls and captions cover those bands.
- **Grid:** 16 × 9 cells of 120 px (`--v-cell`; 9 × 16 vertical). Align element edges to cell
  edges so nothing sits on a fractional pixel. The chapter layout uses a 720 px text column, a
  120 px gap and an 840 px visual column.

### Colour

- Same rules as `design-doc`: neutrals are R = G = B, one hue only, no second colour.
- **Both themes come from one set of token aliases** (stage, text, secondary text, panel, hairline,
  inverse). Never write a hex in a composition.
- **Emphasis is a fill, not a hue change:** the accent is a **bar** that grows under or behind the
  key element. The accent is never text colour on the light theme (1.55:1 on white).
  On the dark theme accent text is allowed (≥ 9.99:1) but a bar is preferred, so both themes match.
- **At most one accent moment per scene**, at most two accent elements in a frame, and the accent
  covers under about 10% of the frame.
- Text on an accent fill is `--text-1`. No gradients, shadows, glow or transparency tricks: solid
  neutrals keep every contrast figure true after compression.
- **States without hue.** Status, success, warning and "done" are a glyph, a label and weight or
  inversion, never a new colour: "✓ Unlocked" as a solid inverse pill, "Locked" as an outlined pill.
  Emphasise a deviating value with weight and an annotation, not with colour.

### Type

- `--font-sans` and `--font-mono` from the tokens (system stacks). Sentence case. Mono only for
  code, commands and file names.
- **Sizes at 1080p** (the `--v-*` tokens; ratio 1.25; these are minimums):

  | Role | Token | Size (px) | Weight |
  |---|---|---|---|
  | Caption, kicker, meta | `--v-caption` | 40 | 600 |
  | Body | `--v-body` | 50 | 400 |
  | Subtitle | `--v-subtitle` | 63 | 600 |
  | Headline | `--v-title` | 78 | 700 |
  | Title card and end card | `--v-hero` | 98 | 700 |
  | One big number | `--v-display` | 122 | 700 |

  Nothing smaller than 40 px except a file name or code token in a screen recording (then 36 px,
  mono). If it cannot be read at a thumbnail 480 px wide, enlarge it or remove it.
- Headlines are semibold or bold, tight, sentence case, and end with a full stop when they are
  full sentences. State facts plainly; leave out exclamation marks and claims the picture cannot show.
- **Text blocks:** a headline is at most 8 words, a body line at most 12, a caption at most 2
  lines of 42 characters.
- **Reading time:** a block stays up for 0.35 s per word plus 1 s, then holds 0.5 s after its
  motion ends. Each block runs its own clock from the moment it has entered; blocks on screen
  together share the time rather than add up. A scene is too short when any block's clock runs
  past the start of the scene's fade-out (`M.minOnScreen` in `assets/lib/motion.js`).
- **Example data is realistic and invented:** believable names, units and times; never lorem,
  foo or "test". Real customers, people and prices never appear.

### Motion

- **Everything is a pure function of time.** Any frame can be computed alone and out of order.
  No timers, CSS animations or transitions, random numbers or real clocks inside a composition.
- **Animate transform and opacity only.** Enter with ease-out
  `cubic-bezier(0.16, 1, 0.3, 1)`; exit with ease-in `cubic-bezier(0.7, 0, 0.84, 1)`; move from one
  place to another with ease-in-out. **No bounce, overshoot or spring; no spinning, zooming or
  3D effects; no confetti, particles or stock footage.**
- **Durations:** small element 150–250 ms; text and panel enter 350–450 ms with a rise of about
  24 px; exits 30% shorter than enters. Stagger related items by 70 ms (up to 5), longer for rows
  that should read one by one.
- **Scene transitions dip:** the outgoing scene fades out completely over its last 250 ms, then
  the incoming scene fades in over its first 250 ms, so texts never overlap. The video opens
  straight on the title card, with no fade-in, and ends on the end card.
- **One motion idea per scene** (a slide, a flip, a count-up). Moments inside a chapter are
  written in **chapter-local seconds** (0 = the chapter's start), the same way in the storyboard
  and in the code.
- Cuts over transitions; use a fade only to mark a change of topic.

### Sound

- Integrated loudness −14 LUFS, true peak −1 dBTP; music 18 dB under the voice, no lyrics under
  speech; silence is allowed.
- Captions are burned in: at most 2 lines, 42 characters per line, theme text (`--on-dark-1` on dark,
  `--text-1` on light) on a solid stage-coloured box (no transparency), bottom-centre above the progress bar, inside the safe area; the words
  match the voice-over.

## Checklist (stills first, then the video)

Render stills at the title card, each chapter's key moment and the end card, in **both** themes,
and confirm:

- [ ] Opens on the title card and ends on the end card; nothing before or after (hero loop: the last frame leads into the first).
- [ ] 1920 × 1080 (1080 × 1920 vertical), 30 fps constant; all text inside the safe area.
- [ ] Every colour is a token; every neutral is R = G = B; the only hue is the accent.
- [ ] At most one accent moment per scene; the accent under about 10% of the frame; no accent text on light.
- [ ] No text under 40 px (36 px mono tokens in screen recordings); blocks within the word limits.
- [ ] Each block stays up for 0.35 s per word + 1 s.
- [ ] Only one thing changes at a time; no overlapping texts during a transition.
- [ ] Ease-out in, ease-in out; no bounce; one motion idea per scene.
- [ ] Headlines state results; data is realistic and invented; copy matches the storyboard.
- [ ] Captions on, 2 lines, solid box; the same words as the voice-over.
- [ ] A visual satellite (annotation, callout) never covers the data it explains.
- [ ] −14 LUFS, −1 dBTP when audio is present; meaning never depends on colour alone.
