# QA (fix silently, report only decisions)

Run on every finished slide. Fix what you can without asking; report only what needs the user's decision. On an edit
(`workflow`, Step 8), fix only what the edit itself broke and report the rest in one line.

- [ ] Tagline (or the full-sentence title) is a claim, `[DRAFT]` removed, and every panel supports it.
- [ ] The insight device points at the proof, passes the findability test (2 seconds), and does not repeat the tagline's
      words.
- [ ] Insight device differs from both neighbours; no device on more than about a third of content slides; so-what bars
      on at most 1 in 5 and never adjacent.
- [ ] Consistent with the case prompt's facts, constraints and numbers.
- [ ] Passes the swap test (would not work unchanged for a competitor) and has exactly one signature element (in
      finance-pitch decks, the exhibit chosen for the data).
- [ ] Passes the clarity test (claim readable in 5 seconds); any metaphor explainable in one sentence.
- [ ] Every required part of the archetype is present, even if the concept reshaped it.
- [ ] Numbers reconcile across slides: exec summary outcomes = financials slide = pillar slides. Recommendation names
      identical everywhere. Annotation values (CAGR, differences) match the chart data.
- [ ] Every exhibit has a header, units, and a footnoted source or assumption.
- [ ] Number formats consistent and correct (`25%`, not `%25`; one of `$22M` / `$22 M+`; one currency symbol style).
- [ ] Tracker shows the right section.
- [ ] Spelling checked, especially headers and recurring terms.
- [ ] Style matches the deck spec (the deck font and the applied palette) on every text run, table cell and chart
      element; no application defaults (Calibri/Aptos, default chart colours) leaking in. In an existing deck,
      title, header and tagline bold and italic match its slides.
- [ ] Text contrast readable on every fill in the applied palette.
- [ ] Density matches the slide's tier (`polish`).
- [ ] Every precision rule in `polish` holds: shared margins with columns lined up between rows, capitalization with no
      all caps, small caps or caps effects, matched line counts, quiet footnotes, no arrow characters, title
      punctuation, centred tracker, charts filling their section, full boxes, bottom margin, colour tokens, stats
      featured once, one reading path, dividers unlike the title slide, a conclusion slide, Gantt bars arrow-ended with
      a milestone row, the risk matrix as the hero, KPIs and assumptions numbered.
- [ ] Finance-pitch decks follow `polish`, Finance pitch decks.
- [ ] Imagery present where the slide type calls for it, absent from analytical slides, within the per-slide budget;
      every unfilled slot on your list of missing items (`workflow`, Step 3); text over photos has an overlay and is
      readable.
- [ ] Any non-standard font flagged for embedding; any font substituted in a check render flagged.
- [ ] Body text >= 8pt; nothing overlapping (titles colliding with chart titles is a common bug); no overflow (re-check
      after any font change); edges aligned; footer zone clear.
- [ ] Composition not reused within the section; not the same structure as either neighbour (impact slides excepted).
- [ ] No `[ ]` placeholders remain unless the user knowingly left them, and each remaining one is on your private
      list of missing items (`workflow`, Step 3).
- [ ] Nothing extra in the deck file: no options, mock, alternate or to-do slides, hidden or visible. The only
      exception is the originals kept beside a new or merged version the user asked for (`workflow`, Step 8), listed
      in your reply.
- [ ] Every sourced photo whose result carried a `credit` line has it in the footnotes; logos, icons and public-domain
      photos carry none.
- [ ] Every content slide has a claim, the reason it is true, at least one specific number, and what it means for the
      client (the depth rule in `workflow`).
- [ ] Titles follow the title mode the user chose (`writing`, Slide titles) on every content slide.
- [ ] The slide follows the confirmed deck type: no consulting devices in a finance pitch, no banker tables standing
      in for a consulting exhibit.
- [ ] Every calculated, projected or estimated figure appears in the financial appendix (`workflow`, Step 5) and
      matches it exactly.
- [ ] Built natively in the deck's style from any references used; nothing copied wholesale from a reference.
- [ ] A delivery reported as finished has passed the final check (`workflow`), kept to yourself.

**Narrative checks** (on every slide against its neighbours; across the whole deck in deck mode):

- [ ] Chain of proof: the slide uses nothing a later slide establishes; every fact, segment and option it relies on was
      proven earlier or is stated in the case prompt.
- [ ] Every recommendation is preceded by proof of the need, the target market and the failure of the alternatives
      for that market; the alternatives judges will think of are addressed before the recommendation.
- [ ] No orphan analysis: every analysis slide sets up a later decision, or it moves to the appendix.
- [ ] Tagline story test: the taglines read in order tell the whole argument, with no gaps and no repeats.
- [ ] Impact slides only at turning points, each built on the slide just shown, about one per section, never three in a
      row; every ribbon or spotlight carries a claim, not a topic.

**Writing pass** (on every slide's text and speaker notes; rules in `writing`):

- [ ] Read it aloud: each line sounds like a careful analyst talking to the panel; rewrite anything stiff, padded or
      salesy.
- [ ] Specific nouns and numbers: every claim names the segment, product, place or period and carries a number where
      one exists.
- [ ] Honest to the data: no tagline or caption claims more than its chart shows (a narrowing gap is not "falling
      behind").
- [ ] Nothing from the "Reads AI-made" list in `writing`, shape patterns included: no banned words, em dashes, triplet
      cadence, rhetorical-question headers, stacked hedges, exclamation marks or emoji.
