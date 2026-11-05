# Visual rules and design options

## Visual rules

- **Palette**: the client's brand colour as the single primary, plus black/dark grey text, mid and light grey fills,
  white. Red/green only for explicit bad/good (weaknesses vs strengths, check/cross, heat maps). No second accent unless
  the deck already has one or the approved colour scheme adds one.
- **Type**: one clean sans family with a light weight for secondary text (e.g. Helvetica Neue + Helvetica Neue Light,
  Inter, IBM Plex Sans, Montserrat). Titles bold ~18pt, taglines ~11 to 12pt, body 8 to 12pt (most often 10 to 12), card
  numbers 20 to 30pt (hero numbers larger), footnotes 6 to 7pt. Match the deck's actual values or the approved font
  option.
- **Box semantics**: brand-colour filled header bar = label; outlined box = content; light grey fill = context or
  assumptions; brand colour on a single element = "this is the point"; numbered circles = cross-reference between a
  visual and its explanation.
- **Charts**: native, editable, labelled with units; grey plus one highlight.
- **Layout shape mirrors the logic**: funnel for conversion, tree for root causes, path for journeys, Gantt for timing,
  matrix for choosing.
- **Imagery**: see image slots below. Every image carries meaning; no decorative stock.

## Design options -> mock -> apply (after the first finished slide)

Decks that stand out look like they belong to their client and prompt, not to a generic consulting template. A
healthcare foundation, a youth-focused gifting campaign and an airline's self-service rollout should not share a look. Fonts and
colours are chosen separately because users often like one option's type and another's palette; a mock of a real slide
comes before any change because swatches don't show how a full slide feels.

Three stages, each gated on the user. Nothing on the deck's real slides changes until stage 3.

**Stage 1: Design Options slide (hidden).** Once the first slide has finished Step 6 (`workflow`), create one hidden
slide titled `Design Options`, directly after the title slide. One per deck; on later runs, read and update it, never
create a second. Every option renders as a real sample:
1. **Prompt read** (one line): 3 to 5 tone words the prompt calls for and why ("Warm, trustworthy, community: nonprofit
   healthcare donor audience").
2. **Current**: the deck's existing fonts and colours, labelled `Keep current`.
3. **Font options F1, F2, F3** side by side: a short name ("Editorial", "Clean Tech", "Friendly"), heading and body font
   named, a live sample of a real title and tagline from the deck in those fonts, a one-line reason, and a flag if the
   font must be downloaded or embedded.
4. **Colour schemes C1, C2, C3** side by side: a short name, swatches with hex codes and roles (primary, accent, dark
   text, light fill, mid grey), a one-line reason. Every scheme is anchored on the client's brand colour as primary;
   vary the accent, the neutrals (warm vs cool greys) and how much brand colour is used (bold fills vs restrained
   lines). Check text contrast on every fill.
5. **Asset list**: every image and mockup slot in the deck, one row each: `slide title | slot | what's needed | suggested
   source | status`.
6. Footer: `Reply with a font and a colour (e.g. "F2 + C1"). Strike through asset rows once added.`

Ask as one message with two picks: "Which font option (F1 to F3) and colour scheme (C1 to C3)? Say 'keep current' for
either." Offer it at a natural pause, never mid-interrogation. If you render the options to an image to check them,
flag any font the renderer substituted.

**Stage 2: Design Mock slide (hidden).** After the picks, duplicate the most recently finished slide (or the most
representative: one with a header bar, a card, a big number and a chart) and restyle only the copy. Title it `Design
Mock: F2 + C1`, hide it, place it directly after `Design Options`. Also apply the shape language and image treatment
that fit the combination (corner radius, line weight, dashed vs solid callouts, icon style, photo treatment) and state
those choices in one line on the mock. In chat: one line on what changed, then "Apply this look to the whole deck?" The
user can approve, swap a pick ("try C3") or ask for a tweak ("accent less orange"); rebuild and ask again, still one ask
per round.

**Stage 3: Apply deck-wide.** Only after the mock is approved; approval also confirms changing the theme fonts and
colours on the master. Restyle every content slide's text runs, fills, lines and chart colours to match, keep all
content and positions, then re-run the QA style checks. Mark the choice on the Design Options slide (`Chosen: F2 + C1`)
and delete the mock (unless the user wants it kept). Report in one line how many slides were restyled and anything that
needs a human eye (e.g. text now overflowing because the new font runs wider).

**Choosing fonts**: the deck will usually be presented on a machine you do not control. At least two of the three font
options should ship with PowerPoint on both Mac and Windows. Flag any downloaded font (e.g. a Google Font) on the slide
and in chat: it must be embedded in the file or the deck falls back to a default. Always recommend a PDF backup for
presentation day.

**Later changes**: a different look after applying goes back to stage 2 with new picks; never restyle without a fresh
approved mock.

## Image and mockup slots

Strong decks use pictures where a human, a product or a place makes the argument concrete, and leave analytical slides
clean.

| Slide job | Imagery? | What works |
|---|---|---|
| Title | **Always** | Full-bleed photo of the client's world (aircraft wing, store front, skyline, home move) with a dark or brand-tinted overlay behind the title. Team headshots in circles optional. |
| Hook / opener | Usually | One striking image per slide, little or no text. |
| Section divider | Often | Darkened full-bleed photo or brand gradient; alternate the two. |
| Persona / customer | **Always** | Circular-cropped portrait, or a full-bleed persona photo on a tinted card. Same person reused through the journey. |
| Recommendation overview | Often | Darkened background photo behind the rec cards. |
| Recommendation detail | **Usually** | Phone or laptop mockups of the proposed product, photos of the activation (events, store displays), partner screenshots, 3 photos above 3 description columns. |
| Customer journey | Usually | Circular photo nodes along the path, mockup screens at each step. |
| Situational / market | Sometimes | Maps with pins, competitor or partner logos, product photos. Not photos for their own sake. |
| Exec summary | Icons only | Simple line icons above rec cards. |
| Issue tree, SWOT, decision matrix | No | Clean boxes; icons at most. |
| Implementation, financials, KPIs, risks | No | Data and structure only; KPI icons at most. |

Budget: one hero image or up to three small images per slide. If more than half the content slides carry photos, cut
the weakest.

**How to block a slot** (in the rough layout, and on finished slides until filled):
- **Photo**: light grey shape in the final crop shape (rectangle, circle, full-bleed with the overlay already applied)
  with a bracketed label: `[PHOTO: young couple unpacking boxes in first home | full-bleed, darkened 40% | why: sets up
  the homeowner milestone]`. Name it `IMG_<role>` (`IMG_Persona`, `IMG_Hero`).
- **Mockup**: a native device frame (rounded-rectangle phone or laptop outline in dark grey) with a grey screen labelled
  `[MOCKUP: loyalty app screen showing a points balance and a redeem button]`. Name it `MOCKUP_<role>`. If the user has
  no screenshot, offer to build a simple concept screen from shapes in the deck's design, clearly a concept, not the
  client's real app.
- **Logos and maps**: `[LOGO: client, two partner logos]`, `[MAP: country, pins at four largest cities]`. Maps can
  usually be built from a provided image or simple shapes.
- Log every slot on the Design Options asset list; if that slide does not exist yet, add them when it is created.

**Sourcing** (suggest, don't overwhelm; image requests count toward the 1 to 2 asks):
- The client's press kit, newsroom, app store screenshots or website for product and brand images.
- Free licensed stock (e.g. Unsplash, Pexels) for scenes and persona portraits; suggest 2 to 3 search terms per slot.
- The user's own photos or screenshots.
- Never pull photos of real public figures from the web; ask the user to supply any such image.
- Persona portraits must read as illustrative: a stock model, never a real private person.

## Default style (blank deck only)

Only when the deck has no content slides and no applied choice; the deck's own spec and the applied choice always win.

- 16:9, 10 x 5.625in. Margins ~0.3in.
- Helvetica Neue (fallback Arial), Helvetica Neue Light for taglines and secondary text.
- Primary = the client's brand colour (ask only if it cannot be found from the prompt or the client's logo). Neutrals:
  text `#262626`, secondary `#595959`, fill grey `#F2F2F2`, mid grey `#D9D9D9`. Good/bad: green `#6AA84F`, red
  `#C00000`.
- Title 18pt bold; tagline 12pt light; panel header bars 10 to 11pt bold white on brand colour; body 10 to 11pt; big
  numbers 24 to 30pt bold brand colour (hero numbers larger); footnotes 7pt.
- Bottom tab tracker (Introduction | Problem Brief | Recommendation | Implementation), current tab in brand colour.
