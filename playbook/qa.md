# QA (fix silently, report only decisions)

Run on every finished slide. Fix what you can without asking; report only what needs the user's decision.

- [ ] Tagline is a claim, `[DRAFT]` removed, and every panel supports it.
- [ ] The insight device points at the proof, passes the findability test (2 seconds), and does not repeat the tagline's
      words.
- [ ] Insight device differs from both neighbours; no device on more than about a third of content slides; so-what bars
      on at most 1 in 5 and never adjacent.
- [ ] Consistent with the case prompt's facts, constraints and numbers.
- [ ] Passes the swap test (would not work unchanged for a competitor) and has exactly one signature element.
- [ ] Passes the clarity test (claim readable in 5 seconds); any metaphor explainable in one sentence.
- [ ] Every required part of the archetype is present, even if the concept reshaped it.
- [ ] Numbers reconcile across slides: exec summary outcomes = financials slide = pillar slides. Recommendation names
      identical everywhere. Annotation values (CAGR, differences) match the chart data.
- [ ] Every exhibit has a header, units, and a footnoted source or assumption.
- [ ] Number formats consistent and correct (`25%`, not `%25`; one of `$22M` / `$22 M+`; one currency symbol style).
- [ ] Tracker shows the right section.
- [ ] Spelling checked, especially headers and recurring terms.
- [ ] Style matches the deck spec (or the applied font and colour choice) on every text run, table cell and chart
      element; no application defaults (Calibri/Aptos, default chart colours) leaking in.
- [ ] Text contrast readable on every fill in the applied colour scheme.
- [ ] Imagery present where the slide type calls for it, absent from analytical slides, within the per-slide budget;
      every unfilled slot on the asset list; text over photos has an overlay and is readable.
- [ ] Any non-standard font flagged for embedding; any font substituted in a check render flagged.
- [ ] Body text >= 8pt; nothing overlapping (titles colliding with chart titles is a common bug); no overflow (re-check
      after any font change); edges aligned; footer zone clear.
- [ ] Composition not reused within the section; not the same grid as both neighbours.
- [ ] No `[ ]` placeholders remain unless the user knowingly left them, and each remaining one is logged on the hidden
      Research To-Do slide or the asset list.
- [ ] Built natively in the deck's style from any references used; nothing copied wholesale from a reference.
