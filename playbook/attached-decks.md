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
3. **Sizes by role**: title, tagline, panel headers, body, big numbers, footnotes. Record the most common value per
   role.
4. **Colour**: the brand colour hex (the fill of header bars, the highlighted tracker item, emphasis), the text colours,
   the grey fills, any second accent and where it is used. Theme colours first, then explicit fills that override them.
5. **Header and tracker**: stacked or inline-pipe header; title form (`Topic: Subtopic`?); tagline style (claim or
   process); tracker form (top breadcrumb or bottom tab bar) and how the current section is marked; logo position.
6. **Box styles**: header bar fills, outline weights and colours, corner radius, grey context boxes, dashed callouts,
   icon style, number tiles.
7. **Charts and images**: chart colours (grey plus one highlight, or default palette), label style, image crops (circle,
   full-bleed, overlay), mockup frames.
8. **Footer**: page number position, source line style, anything else in the footer zone.
9. **Existing devices**: shapes named `Insight_`, `IMG_`, `MOCKUP_`, hidden Design Options / Design Mock / Research
   To-Do slides (`show="0"` on the slide). Read them; they carry earlier decisions.

Summarise the spec in a few lines (fonts, sizes, brand hex, header/tracker form, box styles) and state it to the user
once, so a wrong read is caught early. Then build every new slide to it.

## Using it

- New slides: duplicate an existing content slide of theirs so master, tracker, logo and footer carry over.
- References from the library are rebuilt in this spec; their colours and fonts are ignored.
- Weak spots in their style (process taglines, a so-what bar on every slide, body text under 8pt) are worth one line
  each with the better alternative. Change them only if the user agrees; consistency with their deck comes first.
- If the deck has an applied Design Options choice, that choice is the spec, not the older slides.
- If they attach a deck only as a visual reference (not the deck being built), take its principles (structure, type
  hierarchy, how the insight is shown) and apply them in the working deck's style.
