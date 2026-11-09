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
- [ ] Style matches the deck spec (the deck font and the applied palette) on every text run, table cell and chart
      element; no application defaults (Calibri/Aptos, default chart colours) leaking in.
- [ ] Text contrast readable on every fill in the applied palette.
- [ ] Density matches the slide's tier for the deck type (`polish`).
- [ ] Every precision rule in `polish` holds: shared margins, capitalization, matched line counts, quiet footnotes, no
      arrow characters, title punctuation, centred tracker, full boxes, bottom margin, colour tokens, stats featured
      once.
- [ ] Imagery present where the slide type calls for it, absent from analytical slides, within the per-slide budget;
      every unfilled slot on the research to-do list in chat; text over photos has an overlay and is readable.
- [ ] Any non-standard font flagged for embedding; any font substituted in a check render flagged.
- [ ] Body text >= 8pt; nothing overlapping (titles colliding with chart titles is a common bug); no overflow (re-check
      after any font change); edges aligned; footer zone clear.
- [ ] Composition not reused within the section; not the same grid as both neighbours.
- [ ] No `[ ]` placeholders remain unless the user knowingly left them, and each remaining one is on the research
      to-do list in chat.
- [ ] Nothing extra in the deck file: no options, mock or to-do slides, hidden or visible.
- [ ] Every sourced photo whose result carried a `credit` line has it in the footnotes; logos, icons and public-domain
      photos carry none.
- [ ] What was built matches the approved plan; any change from it was named in chat.
- [ ] Built natively in the deck's style from any references used; nothing copied wholesale from a reference.
- [ ] A delivery reported as finished ends with the completion audit (`workflow`): every run sheet step done, with
      evidence.

**Narrative checks** (on every slide against its neighbours; across the whole deck in deck mode):

- [ ] Chain of proof: the slide uses nothing a later slide establishes; every fact, segment and option it relies on was
      proven earlier or is stated in the case prompt.
- [ ] Every recommendation is preceded by proof of the need, the target market and the failure of the alternatives
      for that market; the alternatives judges will think of are addressed before the recommendation.
- [ ] No orphan analysis: every analysis slide sets up a later decision, or it moves to the appendix.
- [ ] Tagline story test: the taglines read in order tell the whole argument, with no gaps and no repeats.
- [ ] Impact slides only at turning points, each built on the slide just shown, about one per section, never three in a
      row; every ribbon or spotlight carries a claim, not a topic.
