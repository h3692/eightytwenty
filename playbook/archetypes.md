# Storyline and slide archetypes

Identify the slide's job, then use its archetype as the **baseline**: the safe answer every other team will also
produce. It is the floor, not the target (`distinctive-design` says how to beat it). The `id` column is the `slide_type`
value for `find_references`.

**Typical arc**: Title -> (optional hook) -> Executive Summary -> Situational / Problem Analysis -> [section divider] ->
Recommendation(s), one mini-section per pillar -> Implementation -> Financials -> KPIs, Risks & Mitigations -> Appendix.

**Required parts.** Each archetype below names parts the slide must deliver (e.g. an executive summary's Problem /
Recommendation / Outcome). A distinctive concept may reshape those parts, never drop them.

| id | Slide job | Baseline archetype |
|---|---|---|
| `title` | Title | Full-bleed photo of the client's world, dark or brand-tinted band with the deck title (an evocative phrase: "Loyalty, Rebuilt", "Every Seat a First-Class Welcome"), client and team names; team headshots in circles optional. |
| `hook` | Hook / opener (optional) | A 2 to 5 slide narrative build before the exec summary: a quote, an analogy ("The client's cash is like a melting ice cube..."), or a reveal sequence ("Best-in-class checkout: retailer A, retailer B... the client? Not yet."). One idea per slide, almost no text. |
| `executive-summary` | Executive Summary | Required parts: **Problem / Recommendation / Outcome**. Baseline: three rotated vertical labels in brand-colour bands on the left edge. Problem row: the case question in an outlined box, key words bold. Recommendation row: optional phase bar (`Fix -> Grow -> Lead`, `Short Term (1-3 yrs) / Long Term (3-10 yrs)`), then 2 to 3 outlined cards each with icon, bold rec name and a 1 to 2 line description. Outcome row: one big number per card (`$XM / Initial Investment`, `+X% / Repeat Visits`, `X% ROI`). Variants: **labelled rows** (the classic consulting form: three full-width rows with dark labels on the left, Problem as the case question, Recommendation as two or three icon cards, Implementation as a chevron path; dense and scannable, suits consulting-structured decks); 5-row Q&A ("Where should we play? / Who is our target? / What is our advantage? / What is the plan? / What are the results?"). Use `find_references(slide_type: "executive-summary", style: ...)` and read each result's `when_to_use` to pick the form that fits the deck style. Judges expect this structure: keep its logic, make the execution distinctive. |
| `section-divider` | Section divider | Full brand-colour or gradient background, or darkened photo, with a question as the title ("So What Can the Client Do?", "How Will We Execute?") and the section name below. |
| `situational-analysis` | Situational / company analysis | Chart left (market share, revenue growth with CAGR) + 3 header-bar columns right; or KPI number tiles (`Founded / Employees / EBITDA`); or a map with stats. |
| `problem-analysis` | Problem analysis | **Root-cause issue tree**: problem at top, branches down, the branch(es) the recs attack highlighted. Or an iceberg (visible vs invisible causes). |
| `internal-external` | Internal / external | **Modified SWOT**: left = Strengths (green header) + Industry Trends (grey header) as 2x2 boxes; right = red-outlined `Weaknesses -> Opportunities` block with a question subheader ("Why does X have low occupancy?"). |
| `market-trends` | Market / trends | Big-number stat slide (three large percentages with short labels, the target segment highlighted, others greyed); tailwinds vs headwinds columns with icons; a trend line with labelled phases. |
| `customer` | Customer | **Persona**: circular photo, name, age, role, 3 characteristics + 3 big key stats; or a pastel full-bleed persona card (About / Goals / Wants / Frustrations / channels). Personas recur later to walk through the journey. |
| `options` | Options | **Decision matrix**: options as rows, criteria as columns, Harvey balls or check/cross icons, totals column, winner highlighted. Numbered criteria with footnoted definitions. |
| `recommendation-overview` | Recommendation overview | Darkened photo background, "RECOMMENDATION" in large caps, 3 icon cards; repeated per pillar with the current one filled in brand colour. |
| `recommendation-detail` | Recommendation detail | Header bar stating the action ("Key Action: partner with a regional delivery platform to..."), then 3 columns of photo/mockup + description; or a phone/laptop mockup on one side and mechanics on the other; or a process flow of numbered chevrons. |
| `customer-journey` | Customer journey / flow | Curved or straight path with circular photo nodes and stage labels (`ATTRACTION -> CONVERSION`), or a funnel (Awareness -> Consideration -> Conversion -> Loyalty) in shaded brand-colour bands with tactics beside each. |
| `implementation` | Implementation | **Gantt**: quarters or weeks across, workstreams grouped under bold group headers, brand-colour bars, phase labels on top (Preparation / Campaign); optional per-phase cost and KPI annotations in the bars; a total cost callout beside it. |
| `financials` | Financials | Left column `Key Assumptions` in grey boxes; right: cost/profit cards per initiative under brand-colour headers; sensitivity table as a heat map; one big output number (`X% ROI`, `$XM`) in a callout. Acquisition variants: sources/uses, football field, accretion tiles. |
| `kpis-risks` | KPIs, Risks & Mitigations | Left KPI tiles stacked; centre risk matrix (impact vs likelihood or difficulty) with numbered dots; right numbered risk headers (brand colour) with mitigation text. |
| `other` | Anything else | No baseline; derive the composition from the shape of the argument (`distinctive-design`, concept C). |

Spotlight, build, shade + ribbon and recap slides: see `narrative` (impact slides).
