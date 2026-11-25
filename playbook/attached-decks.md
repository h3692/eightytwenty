# Decks the user attaches

When the user attaches their own deck (or a template, or a past deck whose look they want) in chat, its style is the
spec. It stays in the conversation: never pass its content, text or file to `find_references`, `get_reference` or any
other tool that leaves the chat. Search with a plain description of the slide's purpose, never with text copied from
the deck.

## Audit the style

Read the deck file and audit 3 to 5 content slides (skip the title, dividers and appendix). Go by majority; note
exceptions rather than averaging them.

1. **Canvas**: slide size and ratio, margins (left edge of the title and body, distance from the footer).
2. **Fonts**: heading and body families and weights, from the theme and from the text runs actually used (runs often
   override the theme). Note any font that is not a system font: it needs embedding, and a check render will substitute
   it.
3. **Sizes and styling by role**: title, tagline, panel headers, body, big numbers, footnotes. Record the most common
   size, weight (bold, regular, light) and italic per role; new slides match them exactly.
4. **Colour**: the brand colour hex (the fill of header bars, the highlighted tracker item, emphasis), the text colours,
   the grey fills, any second accent and where it is used. Theme colours first, then explicit fills that override them.
5. **Header and tracker**: stacked or inline-pipe header; title form (`Topic: Subtopic`?); tagline style (claim or
   process); tracker form (top breadcrumb or bottom tab bar) and how the current section is marked; logo position.
6. **Box styles**: header bar fills, outline weights and colours, corner radius, grey context boxes, dashed callouts,
   icon style, number tiles.
7. **Charts and images**: chart colours (grey plus one highlight, or default palette), label style, image crops (circle,
   full-bleed, overlay), mockup frames.
8. **Footer**: page number position, source line style, anything else in the footer zone.
9. **Existing devices**: shapes named `Insight_`, `IMG_`, `MOCKUP_`. Hidden working slides from older tools (`show="0"`,
   e.g. Design Options or Research To-Do) carry earlier decisions: read them, carry their open items into your list of
   missing items (`workflow`, Step 3), and offer to delete them, since judges can unhide them. Leave a hidden
   "Financial Reasoning" slide in place (`workflow`, Step 5).
10. **Deck type**: finance pitch or consulting. It is a **finance pitch** (`finance-pitch`, its rules in `polish`,
    Finance pitch decks) when most of these show: valuation exhibits (football field, trading comps, precedent
    transactions, DCF); returns language (IRR, MOIC, `x` multiples, `LTM` / `NTM`, `2025A` / `2026E`); dense tables
    of figures with `$` labels; deal sections (transaction overview, sources and uses, situation overview,
    investment thesis, catalysts, risks to the thesis); plain register with no bold mid-sentence. It is
    **consulting** when most slides carry a problem or recommendation story: issue trees, customer segments,
    recommendation pillars, implementation roadmaps, KPIs, client-world imagery. A consulting deck with one
    financials section is still consulting. If it is mixed or unclear, say what you saw and ask; never guess.
    Always confirm your read with the user before the first change (`workflow`, Step 8); once confirmed, the type
    is locked.

Summarise the spec in two or three short lines (fonts, brand hex, header form, deck type) and state it to the user once,
with the deck type as a question to confirm, so a wrong read is caught early. Then build every new slide to it.

## Using it

- New slides: duplicate an existing content slide of theirs so master, tracker, logo and footer carry over.
- References from the library are rebuilt in this spec; their colours and fonts are ignored.
- Weak spots in their style (process taglines, a so-what bar on every slide, body text under 8pt) are worth one line
  each with the better alternative. Change them only if the user agrees; consistency with their deck comes first.
- If the deck has an applied Design Options choice, that choice is the spec, not the older slides.
- The deck's title form tells you the title mode: claims as titles mean full-sentence mode, short topic titles with a
  tagline mean label mode. Keep it unless the user asks to switch.
- If they attach a deck only as a visual reference (not the deck being built), take its principles (structure, type
  hierarchy, how the insight is shown) and apply them in the working deck's style.
