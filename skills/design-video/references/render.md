# design-video — build, preview and render

The renderer needs **Node 18+, npm and Google Chrome** (or Chromium). On first run it installs
pinned `playwright-core` and a static `ffmpeg` (44 MB measured) into a per-user cache folder:
`$XDG_CACHE_HOME/design-video/` (default `~/.cache/design-video/`; `%LOCALAPPDATA%\design-video\`
on Windows), or `$DESIGN_VIDEO_CACHE`. Neither the project nor the skill folder (read-only in a
plugin install) is written to; later renders, from any project, reuse the cache.

`S` below stands for `"${CLAUDE_SKILL_DIR}/scripts"`; write it out in full in the commands you run.

## Steps

1. **Storyboard approved** (`storyboard.md`).
2. **Start the composition in the project:** `node S/new-video.mjs videos/<topic>` writes
   `index.html`, `motion.js` and `tokens.css` side by side (the page links `tokens.css` and
   `motion.js` next to it), so the folder previews, renders and ships on its own. It refuses to
   overwrite an existing `index.html`.
3. **Edit the composition:** the timeline constants (`TITLE`, `CHAPTER`, `END`, `CHAPTERS`), the
   `COPY` and `CAPTIONS` objects, the visual functions and their time-keyed moments. Keep the
   structure: title card → chapters → end card (a hero loop has neither card), the dip transitions, the progress bar.
4. **Preview a frame in a browser** by opening the file with `?t=12.5&mode=light`.
5. **Render stills first** (about 3 s each):

   ```bash
   node S/render.mjs videos/<topic>/index.html --still 2   --out title.png
   node S/render.mjs videos/<topic>/index.html --still 14  --mode light --out ch2-light.png
   ```

   Check the title card, each chapter's key moment and the end card, in both themes, against the
   checklist in `SKILL.md`. Fix layout in the composition before rendering the whole video.
6. **Render:**

   ```bash
   node S/render.mjs videos/<topic>/index.html --mode both --out my-video.mp4 [--audio voice.wav]
   ```

   Writes `my-video-dark.mp4` and `my-video-light.mp4`. Measured here: a 5-second slice rendered
   in about 13 s (roughly 2.6 × real time at 1080p, one theme at a time). Add `--scale 2` for 4K
   (measured: 0.5 s of video came out as 3840 × 2160, 15 frames, in 2 s, about 4 × real time), `--fps 60` for smoother motion, `--from` and `--to` to render a section.
7. **Probe and watch** the MP4 (`export.md`), then deliver MP4s, storyboard and composition source.

## Options

| Option | Meaning |
|---|---|
| `--out <file>` | output file (`.mp4`, or `.png` with `--still`) |
| `--mode dark\|light\|both` | theme(s); `both` writes `-dark` and `-light` files |
| `--still <s>` | write one PNG at time `s` instead of a video |
| `--from <s> --to <s>` | render only a section |
| `--fps <n>` | frames per second (default 30) |
| `--scale 1\|2` | device scale factor; 2 gives 3840 × 2160 |
| `--audio <file>` | add an audio track, loudness-normalised to −14 LUFS |
| `--chrome <path>` | Chrome or Chromium executable (also `CHROME_PATH`) |
| `--work <dir>` | folder for the render dependencies (default: the per-user cache above) |

## Composition contract

```html
<link rel="stylesheet" href="tokens.css">
<script src="motion.js"></script>
<script>
  window.__video = { width: 1920, height: 1080, duration: 32 };   // seconds; 1080 x 1920 for vertical
  window.__frame = (t, mode) => { /* draw the frame at time t; mode is 'dark' or 'light' */ };
</script>
```

- **Every visual state is a function of `t`** (or of a scene's local time `lt = t - scene.at`).
  No `setTimeout`, no CSS animations or transitions, no `Math.random()`, no `Date.now()`:
  the renderer asks for frames one after another, and a preview or a still asks for any `t`.
  Determinism is tested: the same still rendered twice has the same SHA-256.
- Build the scene DOM **once**, then update styles from `t` (the template does this). Do not
  rebuild nodes per frame.
- Use the tokens (`var(--…)`), never a hex.
- Wait for nothing asynchronous inside `__frame`: images and fonts must be loaded before the
  first frame (system fonts and inline SVG or data URIs need no waiting).

## `motion.js` helpers

| Helper | Purpose |
|---|---|
| `M.span(t, a, b, ease)` | eased progress of `t` through [a, b], clamped to 0..1 |
| `M.ease.out / .in / .inOut / .linear` | the allowed easing curves |
| `M.enter(t, at, dur, dist)` | `{ o, y }`: fade and rise |
| `M.leave(t, at, dur)` | `{ o, y }`: exit |
| `M.stagger(i, gap)` | delay for the i-th item |
| `M.typewriter(text, t, at, cps)` | typewriter text |
| `M.counter(t, a, b, from, to)` | counting number |
| `M.minOnScreen(text)` | reading-time minimum in seconds |
| `M.put(el, state)` | apply `{ o, y }` to an element |

## Troubleshooting

| Message | Fix |
|---|---|
| `Chrome or Chromium not found` | Install Google Chrome, or pass `--chrome <path>` / set `CHROME_PATH`. |
| `composition did not define window.__video and window.__frame` | The page threw on load; the message after the colon names the error. |
| `composition threw: …` | A runtime error inside `__frame`. |
| Text in a serif font | A font-family without the token stack; use `font-family: var(--font-sans)`. |
| Something appears in the wrong frame | A state is not derived from `t` (a timer, an animation); make it a function of `t`. |
| The frame has a flash at a scene change | The incoming scene's first frame is at full opacity; check the dip transition uses `fin`/`fout`. |
| `npm install` fails behind a proxy | Run once with network access, or pass `--work` pointing to a folder where the dependencies are already installed. |
| `template link not found` from `new-video.mjs` | The template's links to `tokens.css` / `motion.js` changed; restore them to `../../references/tokens.css` and `../lib/motion.js`. |

## Hosted design tool (no terminal)

If the person cannot run the renderer, hand over the storyboard plus one build brief for whichever
tool they use: the frame size, 30 fps, the token table (colours, sizes), and for every scene the
exact start second, the one moment with its local second, the accent moment, and the copy. A
tool that exports video can then follow the same timings; the checklist in `SKILL.md` still applies.
