# design-video — moments for a chapter's visual

A chapter shows **one moment**: one thing that changes, at a known second, while everything else
holds still. Pick the pattern that fits the story, build it from neutral panels, and mark the one
accent moment with a bar.

| Pattern | What the viewer sees | How it is drawn |
|---|---|---|
| **State flip** | A status changes in the same place: "Locked" becomes "✓ Unlocked". | Outlined pill swaps to a solid inverse pill at the second; the accent bar grows under it. |
| **Rows one by one** | A list is processed row by row. | Each row enters with a stagger of 0.5–0.8 s; a row that needs explaining gets an annotation after it settles. |
| **Many into one** | Messy inputs resolve to one clean value. | Variants of a value stack on the left; progress 0→1 morphs them into one canonical form on the right. |
| **Counter** | A number reaches its value. | `counter(t, a, b, from, to)` with ease-out; the unit stays still, only digits change; tabular numerals. |
| **Fill** | Progress or confidence builds. | A bar's width follows `span(t, a, b, ease.inOut)`; the bar is the accent. |
| **Pinned note** | A rule or reason explained next to the thing it concerns. | A bordered annotation anchored to the card's edge; placed so it never covers the data it explains. |
| **Sources to hub** | Several inputs converge. | Several small panels on the left, connectors drawn with a dot travelling along them (`ease.inOut`), one hub panel on the right. |
| **Timeline** | Events happen in order. | Entries appear one by one on a vertical rule; the newest has weight, older ones return to normal weight. |
| **Typed text** | Something is being written. | `typewriter(text, t, at, cps)`; blinking caret only while typing. |
| **Before / after** | Two states of the same thing. | Left and right panels of equal size; "before" in outline, "after" in solid; the accent bar sits under the "after". |

Rules for every pattern:

- **Keep the visual inside 840 × 720 px**, aligned to the 120 px cells; satellites (notes,
  callouts) are positioned absolutely inside it and never cover the data they explain. Check stills.
- **Key the moment to chapter-local seconds**, and write the same seconds in the storyboard.
- **Only one thing changes at a time:** do not start a second moment before the first has settled.
- **No hue for meaning:** use a glyph and a label (✓, !, ×), weight, outline versus solid.
- **Final state is stable:** when a moment completes, it stays completed for the rest of the
  chapter (about 1.5 s of hold).
- Static content around the moment stays visible from the settle time on; only the moment moves.

## Story shapes

Three shapes cover most videos; choose the one that matches the brief.

| Shape | Chapters (label → moment) | End card |
|---|---|---|
| **A job, start to finish** | Start → state flip; Do → rows one by one or fill; Finish → state flip to done | the viewer's next step |
| **A problem solved** | Problem → many messy things stacked; Fix → many into one; Result → counting number of the improvement | the viewer's next step |
| **A short tour** | one chapter per area: Capture, Review, Share; each → a different pattern | the viewer's next step |
