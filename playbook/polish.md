# Density and polish

The details a judge notices in the first minute, and that separate a careful team's deck from an AI-generated one.
Apply them while building, then again as a polish pass over each slide and over the whole deck before QA.

## Density, set by the deck type, never asked separately

Question 1 in `workflow` decides whether this is a presentation deck or a reading deck, and that sets the density. Do
not show density samples or ask the user to choose a density.

- **Presentation deck**: content slides at Low; financials and the problem analysis at Medium. Detail cut to fit goes to
  the speaker notes or the appendix.
- **Reading deck**: content slides at Medium; financials and the problem analysis at High. The slide must stand on its
  own.

**Speaker notes** (presentation deck): for each slide, write what to say aloud and the numbers behind the slide that
were cut from it, in full sentences the presenter can read; never repeat the slide text.

Change a slide's or the deck's density only when the user asks ("make this one lighter", "make the whole deck Low").
What separates the tiers is structure more than word count: Medium uses 3 to 4 boxed panels and several supporting
stats around a lead element; Low uses one dominant anchor and open layouts.

Body only (excludes title, tagline, tracker and footnotes); sizes as 13.33in canvas / 10in canvas:

| | **Medium** (reading: content; presentation: financials, problem analysis) | **High** (reading: financials, problem analysis) | **Low** (presentation: content) |
|---|---|---|---|
| Body words | ~100 to 150 | ~150 to 250 | ~50 to 100 |
| Content blocks | 3 to 4 | 4 to 6 | 2 to 3 |
| Anchor element | Lead element ~25 to 35%, supporting panels around it | No single anchor; the output number or priority root cause still stands out | One dominant element, at least ~40% of the body |
| Exhibits | 1 to 2 | 2 to 3 (revenue build + cost table + sensitivity; driver tree + evidence table) | 1 |
| Tables / Gantt | Max ~6 x 6; Gantt up to ~10 rows | Max ~10 rows; sensitivity tables, full assumption lists | Max ~4 x 4 |
| Body type | 11 to 13pt / 9 to 10pt | 9 to 11pt / 8 to 9pt | 13 to 16pt / 10 to 12pt |
| Smallest text (not footnotes) | 9pt / 8pt | 8pt / 8pt | 10pt / 8pt |
| White space | A fifth to a third | A tenth to a fifth | A third or more |
| Numbers shown | ~8 to 20 | 20+ | ~3 to 8 |
| Insight devices that suit it | Any; rotate freely | Comments sidebar, on-chart annotation, numbered callouts, hero number for the output | Hero number, highlight the one, tagline only |
| Where cut detail goes | Footnotes and appendix (presentation deck: speaker notes and appendix) | On the slide | Speaker notes and appendix |

**Financials slides**: revenue build, cost build, unit economics, P&L, NPV / payback, sensitivity, transaction or
valuation; the problem analysis takes the same tier. **Content slides**: every other content slide, including the
executive summary, situation, market, customer, recommendation, implementation, KPIs / risks and conclusion. The
appendix may use High in either deck type. Title, hook and divider slides are unaffected. Nothing below 8pt on any
slide.

## Precision rules

1. **Shared margins.** One left and one right content margin per slide. Every row of boxes spans exactly from margin to
   margin: box width = (content width - gutters) / number of boxes, identical gutters. When a slide has a full-width
   element (a problem box, a phase arrow, a chevron row), every other row ends at that same right edge.
2. **Capitalization**, one convention deck-wide. Title Case for slide titles, panel and box headers, card titles,
   recommendation names, phase labels, table column headers, tracker labels, axis titles and KPI names. Sentence case
   for taglines, body text, bullets, descriptive chart titles, captions and footnotes. ALL CAPS only for small eyebrow
   labels, and then for every eyebrow label. Proper nouns, product names and acronyms as the client writes them.
3. **Matched line counts in sibling boxes.** Boxes side by side (outcome cards, rec cards, KPI tiles, persona panels)
   get text of the same number of lines, with every number at the same height: anchor text to the top, put big numbers
   in their own fixed-position text box, keep labels under them to equal line counts. Edit the words, not the font
   size.
4. **Quiet footnotes.** Superscripts ~60% of the surrounding size, secondary grey, never bold or brand-coloured. The
   footnote line holds only numbered notes that support a numbered fact on the slide. No unnumbered notes ("Illustrative
   persona", "Bars to scale", "Timing indicative"); an estimate's assumption goes in its numbered note, anything else in
   speaker notes.
5. **No arrow characters** (`→`, `->`, `=>`) in slide text; it is an instant tell of AI-made slides. Say the
   relationship instead: change over time as two labelled numbers with the change in a small tag (`-14 pts`); sequence
   as numbered steps, chevrons or a phase bar; cause and effect as a drawn connector or words ("so", "which leads to");
   transformation as "from X to Y" or `Today` / `With [Rec Name]` columns. Drawn arrows on charts and diagrams are
   fine.
6. **Consistent title punctuation.** If any content slide title uses a colon subtitle, every one does; otherwise none
   does. Default: none, with the specifics in the tagline. A section label like `Recommendation 1` can sit as a small
   eyebrow above the title.
7. **Centred, designed section tracker**, horizontally centred, page number separate (bottom right), matched to the
   deck's look (small caps with a brand underline under the active section, a thin progress line, numbered chips, or
   slim rounded tabs). Same treatment on every content slide.
8. **Charts**: native, with an exact descriptive title, units and population base; grey history and a brand-colour
   latest bar; drawn difference brackets where a gap matters.
9. **A so-what on every problem-brief slide.** The situation, problem analysis, market and customer slides each end with
   an explicit so-what that names the implication for the client and sets up the recommendation. Vary its form
   (implication sidebar, conclusion column after a cause chain, bridge line under the exhibit, so-what bar); a tagline
   alone is not enough here.
10. **Problem analysis at expert depth** (at its tier; in a presentation deck the rest goes to the appendix): a MECE
    issue or driver tree separating **symptoms** from **root causes**; for each of 3 to 5 root causes, a quantified
    effect, the evidence and its source, and the **mechanism** behind it (present bias, choice overload, friction cost,
    missing feedback loops, principal-agent problems), named precisely and briefly; **prioritisation** (impact vs
    addressability, the causes the recommendation attacks highlighted); **what was ruled out** (1 to 2 plausible
    hypotheses the evidence rejects, and why); segment differences where they exist; the so-what. Missing evidence for a
    cause is marked `[verify]` and logged, never replaced with a vaguer cause.
11. **Full boxes.** Text fills a box to roughly 70 to 90% of its height. Under-filled: add a specific number, example or
    sourced fact, or shrink the box and rebalance. Never leave visual holes; keep siblings matched (rule 3).
12. **Consistent bottom margin.** All columns end on the same bottom line, the same distance above the footnotes and
    tracker on every slide.
13. **One quote style.** Opening and closing quotation marks match in size, weight and colour: both oversized or both at
    text size.
14. **Feature each stat once.** Keep a running list of stats shown as big numbers or stat boxes; a featured stat is not
    featured again later (body text may mention it).
15. **Dividers are not title slides.** Section dividers differ visibly from the title slide in composition and
    background; they should feel like a turn in the story.
16. **Colour discipline.** Only the palette's named tokens (primary, primary dark, light tint, accent, text, secondary
    text, grey fill, mid grey). Same role, same fill: all header chevrons alike, all body cards alike, one highlighted
    column or row in the primary. Shade progressions only when they encode a real order, applied the same way in every
    row.
17. **Client-world artifacts work.** A recommendation shown as an artifact from the client's world (a fund fact sheet, a
    statement, a boarding pass) is memorable; see `distinctive-design`.
18. **Equations shown with care.** A calculation is laid out as an equation: one term per cell, operators (`+`, `x`,
    `÷`, `=`) as separate centred glyphs in their own narrow column; or a receipt-style stack with values right-aligned,
    a rule, and the result in bold brand colour. Never let a formula wrap mid-term. Label each term in small text under
    it.
19. **Hubs and guardrails work.** A hub with the decisive number at the centre and benefits around it, next to a
    checklist of guardrails, reads well for "what the client gains".
20. **Gantt and roadmap details.** Bars end in an arrow point (pentagon or chevron shapes), not flat rectangles.
    Milestone diamonds sit in their own row under the bars, aligned to their date with a short label.
21. **Numbered assumptions** on financials slides (1, 2, 3...), referenced by number where they drive a line; where it
    fits, show each one's effect on the output (a tornado). Numbering is not optional.
22. **KPIs and risks.** KPIs numbered (KPI 1, 2, 3 or 01, 02, 03). The risk matrix is the star of its slide: about half
    the body or more, labelled axes and quadrants, the high-impact, high-likelihood zone highlighted, numbered dots
    readable from the back of a room, numbered mitigations beside it.
23. **Always a conclusion slide** before the appendix: the recommendation, its outcome and the ask, in one view.

## Deck-wide polish pass

Across slides, not just within each: the same margins and bottom line on every slide; one capitalization convention;
colons in all titles or none; the tracker identical and centred; no arrow characters anywhere; no stat featured twice;
dividers unlike the title slide; every problem-brief slide carries a so-what; a conclusion slide exists; every text run
in the deck font.
