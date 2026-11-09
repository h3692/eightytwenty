# Visual rules and design options

## Visual rules

- **Palette**: the client's brand colour as the single primary, plus black/dark grey text, mid and light grey fills,
  white. Red/green only for explicit bad/good (weaknesses vs strengths, check/cross, heat maps). No second accent unless
  the deck already has one or the approved palette adds one. Use only the palette's named tokens (`polish`).
- **Type: one deck font.** Helvetica Neue by default, or the deck's existing font if the user chose to keep it
  (`workflow`, question 1). Bold for titles, header bars, card titles and big numbers; regular for body; light for
  taglines and secondary text (if the font has no light weight, regular in the secondary grey). Titles ~18pt, taglines
  ~11 to 12pt, body size by the density tier (`polish`), card numbers 20 to 30pt (hero numbers larger), footnotes 6 to
  7pt. Charts, tables and pasted text are converted to the deck font too; no Calibri, Aptos or stray Arial.
- **Box semantics**: brand-colour filled header bar = label; outlined box = content; light grey fill = context or
  assumptions; brand colour on a single element = "this is the point"; numbered circles = cross-reference between a
  visual and its explanation.
- **Charts**: native, editable, labelled with units; grey plus one highlight.
- **Layout shape mirrors the logic**: funnel for conversion, tree for root causes, path for journeys, Gantt for timing,
  matrix for choosing.
- **Imagery**: see image slots below. Every image carries meaning; no decorative stock.

## Palette options -> mock -> apply (after the first finished slide)

Decks that stand out look like they belong to their client and prompt, not to a generic consulting template. A
healthcare foundation, a youth-focused gifting campaign and an airline's self-service rollout should not share a look.
The font is settled in the first question, so the palette is the main lever on mood. A mock of a real slide comes before
any change because swatches don't show how a full slide feels.

Three stages, each gated on the user. Nothing in the deck changes until stage 3, and **none of this goes into the deck
file**: the options and the mock go to the user in chat.

**Stage 1: Palette options, in chat.** Once the first slide is finished (`workflow`), send the options board as an
**image** if you can render one (an SVG or HTML artifact, or a PNG drawn in your code sandbox), otherwise as **plain
text**. It holds:
1. **Prompt read** (one line): 3 to 5 tone words the prompt calls for and why ("Warm, trustworthy, community: nonprofit
   healthcare donor audience"), where the brand colour came from ("primary #1F5FA8 sampled from the logo in the case
   PDF"), and the deck font.
2. **Six palettes**, each with a short name, swatches with hex codes and roles (primary, primary dark, accent, light
   fill, mid grey, text), a one-line reason it fits the prompt, and in the image version a mini sample (a header bar, a
   card and a big number in that palette):
   - **C0, No change**: the current scheme (the brand-derived default, unless the deck had its own).
   - **C1, Warm**: a warm-leaning accent (amber, coral, terracotta) with warm greys and creams.
   - **C2, Cool**: a cool-leaning accent (teal, slate blue, sky) with cool greys.
   - **C3, Neutral**: restrained greys, charcoal and off-white, the brand colour used sparingly as the only accent.
   - **C4, Monochrome**: tints and shades of the brand colour only, plus white and near-black; hierarchy from lightness.
   - **C5, Bold**: high contrast; the brand colour (or its darkest shade) as full backgrounds on title, divider and
     hero-number slides, one saturated complementary accent; content slides stay on white.
   Every palette is anchored on the client's brand colour and chosen for this prompt. Check text contrast on every fill;
   drop or adjust any palette that fails.
3. **Image and mockup slots**: the open rows of the research to-do list (`workflow`, Step 5).

Ask one question: "Which palette: C0 no change, C1 warm, C2 cool, C3 neutral, C4 monochrome or C5 bold?" If the user
picks C0, skip to the next slide.

**Stage 2: Mock, in chat.** Restyle a copy of the most representative finished slide (a header bar, a card, a big number
and a chart is ideal) in the chosen palette, with the shape language and image treatment that fit it (corner radius,
line weight, dashed vs solid callouts, icon style, photo treatment). Show it as a **rendered preview image**, or as a
separate one-slide file if you cannot render; never as a slide in the user's deck. One line on what changed, then
"Apply this palette to the whole deck?" The user can approve, switch ("try C4") or tweak ("accent less orange"); rebuild
the mock and ask again, one ask per round.

**Stage 3: Apply deck-wide.** Only after the mock is approved; approval also confirms changing the theme colours on the
master. Restyle every content slide's fills, lines, text colours and chart colours, keep all content and positions,
make sure every text run is in the deck font, then re-run the QA style checks. Report in one line how many slides
changed and anything that needs a human eye.

**Later changes**: a different palette after applying goes back to stage 2; never restyle the deck without a freshly
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

**How to block a slot** (in the layout spec, and on finished slides until filled):
- **Photo**: light grey shape in the final crop shape (rectangle, circle, full-bleed with the overlay already applied)
  with a bracketed label: `[PHOTO: young couple unpacking boxes in first home | full-bleed, darkened 40% | why: sets up
  the homeowner milestone]`. Name it `IMG_<role>` (`IMG_Persona`, `IMG_Hero`).
- **Mockup**: a native device frame (rounded-rectangle phone or laptop outline in dark grey) with a grey screen labelled
  `[MOCKUP: loyalty app screen showing a points balance and a redeem button]`. Name it `MOCKUP_<role>`. If the user has
  no screenshot, offer to build a simple concept screen from shapes in the deck's design, clearly a concept, not the
  client's real app.
- **Logos and maps**: `[LOGO: client, two partner logos]`, `[MAP: country, pins at four largest cities]`. Maps can
  usually be built from a provided image or simple shapes.
- Log every slot on the research to-do list in chat (`workflow`, Step 5).

**Sourcing** (you find the images; the user is the last resort):
1. **Icons, and single-colour brand marks:**
   - In claude.ai, use the preinstalled `react-icons` (Tabler, Lucide, Phosphor, Heroicons, Material, Simple Icons)
     and render with `sharp`, with no tool call.
   - Elsewhere, call `find_images(kind: "icon", query)`.
   - Search by the object drawn ("truck", "clock", "shield"), not the concept ("logistics", "speed", "trust").
   - One icon family per deck.
2. **Logos** (the client, partners, competitors): first look for the client's logo in the case files the user gave you,
   then `find_images(kind: "logo", query: "<company>")`. Logos identify a company; never use them as decoration.
3. **Photos** (scenes, settings, persona portraits): `find_images(kind: "photo", query)`. Describe the scene, not the
   argument ("nurse at a hospital reception desk", not "healthcare access"). Look at the thumbnails and pick the one
   that fits the slot's crop, mood and palette.
4. **Turn each pick into a file:**
   - **SVG text** (logos, icons): write it to a `.svg` file and rasterise it to PNG at the slot's size. Use whichever
     tool your sandbox has: `sharp`, then `cairosvg`, then `rsvg-convert`, then `soffice --convert-to png`. Recolour
     icons and single-colour marks to the palette's tokens; keep multi-colour logos as they are. Never turn on a
     rasteriser's unsafe or external-resource options.
   - **Photos:** download `download_url` inside your sandbox.
5. **If your sandbox can't download (step two, by hand):** send one message that lists every photo slot. For each, give
   the photo's title, creator, landing link, direct link, and a file name to save it as (`s07-hero.jpg`), so the
   user's uploads map back to slots. This one batched ask is exempt from the 1 to 2 asks rule. Keep building everything
   else, and track open slots on the research to-do list in chat.
6. **Place it** cropped to the slot shape, with the overlay kept. **Credit only when the result carries a `credit` line**
   (openly licensed photos that require attribution): put it in the footnote. Logos, icons and public-domain photos
   need none.
- The user's own photos and screenshots always win over sourced ones.
- Never source photos of real public figures; ask the user for any such image.
- Persona portraits must read as illustrative (a stock model), never a real private person.

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
