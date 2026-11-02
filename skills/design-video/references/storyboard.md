# design-video — script and storyboard

Write the storyboard **before** building and show it. It is the single source for the script:
titles, headlines, body lines, on-screen moments, voice-over and captions are all taken from it.
Keep it in the video's folder as `storyboard.md` and hand it over with the video.

## Template

```text
# <Video title> — storyboard

Where it plays: <website | social | meeting | in-product | loop>   Length: <seconds>
Themes: dark + light | dark only | light only    Frame: 1920×1080 · 30 fps · captions on
Audience: <who watches>
The one thing they should understand or be able to do: <one sentence>
Voice-over: <yes (150 wpm) | no>    Music: <yes | no>

TITLE CARD (0–4 s)
  Title:     <short, names the topic>                 e.g. "Unlock a bike in one tap."
  Sentence:  <one sentence that promises the result>  e.g. "Scan the code, ride, lock."

CHAPTER 1 — <Label> (<start>–<end> s)
  Headline:  <states the result, ≤ 8 words>
  Body:      <one sentence, ≤ 12 words>
  Visual:    <what is on the right>
  Moment:    <the one thing that animates, in chapter-local seconds (0 = chapter start)>
  Accent:    <the one accent moment, or none>
  Voice-over / caption: <the words, same as spoken>

CHAPTER 2 … (repeat; 3 chapters up to ~45 s, 4 up to ~75 s, 5 beyond)

END CARD (last 4 s)
  Line:      <the viewer's next step, one sentence>
  Mark:      <identity mark, optional, end card only>
```

## Rules of thumb

- A chapter with a visual is 7–9 s: about 0.8 s to settle, the reading time of the headline, the
  one moment, about 1.5 s of hold. A text-only scene is 4–8 s.
- Chapter labels are one word: Scan, Ride, Lock.
- Headlines state the result ("Pay only for the minutes."), not the mechanism.
- The title names the topic; the end card names the next step. Do not repeat the title.
- On-screen text is not a transcript of the voice-over: the voice says it, the screen shows the
  shortest form. Voice-over runs at 2.5 words per second, so a 4-second line carries at most 10 words.
- Write what a viewer sees and hears, not how it is built.

## Reading-time check (per text block)

```text
minimum on screen = 0.35 × words + 1.0 s, plus 0.5 s of hold after the motion ends
```

Each block's clock starts when it has entered; blocks on screen together run their clocks in
parallel, not one after another. If any block's clock runs past the start of the chapter's
fade-out, cut words or lengthen the chapter.

## Example

```text
# Bike share: unlock — storyboard

Where it plays: social feed   Length: 32 s
Themes: dark + light    Frame: 1920×1080 · 30 fps · captions on
Audience: first-time riders
The one thing they should understand: you unlock, ride and lock with your phone alone.
Voice-over: yes    Music: no

TITLE CARD (0–4 s)
  Title:    Unlock a bike in one tap.
  Sentence: Scan, ride and lock.

CHAPTER 1 — Scan (4–12 s)
  Headline: Scan the code, ride away.
  Body:     Point the phone at the bike. It unlocks in a second.
  Visual:   A bike card (Bike 7306, Harbor Street) with a status pill.
  Moment:   3.0 s: the pill flips from "Locked" to a solid "✓ Unlocked" in the same spot.
  Accent:   a bar grows under the pill at 3.0–3.4 s.
  Caption:  "Scan the code, ride away."

CHAPTER 2 — Ride (12–20 s)
  Headline: Pay only for the minutes.
  Body:     The meter runs while you ride and stops when you lock.
  Visual:   A card with minutes and kilometres.
  Moment:   1.8–5.0 s: both numbers count up (12 min, 3.4 km) while a bar fills.
  Accent:   the bar.
  Caption:  "Pay only for the minutes."

CHAPTER 3 — Lock (20–28 s)
  Headline: Lock it, and you are done.
  Body:     The receipt arrives before you reach the kerb.
  Visual:   A receipt card: start, end, price.
  Moment:   rows appear one by one from 1.8 s; 5.0 s: "✓ Trip ended" pill appears.
  Accent:   none.
  Caption:  "Lock it, and you are done."

END CARD (28–32 s)
  Line:     Take your first ride today.
```

## Caption file

If captions are delivered as a separate file (SRT): at most 2 lines, 42 characters per line, each
cue 1–6 s, cues never overlap, and the text matches the voice-over word for word.

```text
1
00:00:00,300 --> 00:00:03,700
Unlock a bike in one tap.
```

## Review stills

For every chapter export the key-moment frame, plus the title card and the end card, in each theme.
Check: text inside the safe area; nothing under 40 px; the accent once, under about 10% of the
frame; no annotation covering the value it explains; contrast: `--on-dark-1` on `--dark-bg`
18.16:1, `--on-dark-2` on `--dark-surface` 8.63:1, `--text-1` on `--accent` 12.06:1, `--text-3` on
`--bg` 6.69:1.
