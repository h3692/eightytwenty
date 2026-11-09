import json
import re

import jsonschema
import pytest
from PIL import Image

from pipeline import flow
from pipeline.__main__ import main

DECK = "00000000000000aa"
SECTIONS = ["cover", "hook", "executive-summary", "executive-summary", "situation", "situation", "problem-analysis",
            "solution", "solution", "solution", "closing", "appendix"]
ARCHETYPES = ["title", "hook", "executive-summary", "executive-summary", "section-divider", "situational-analysis",
              "problem-analysis", "section-divider", "recommendation-overview", "recommendation-detail", "other",
              "other"]
WHY = "Opens on one bold promise, builds the evidence, then lands the plan before any detail"


def _deck(lib, archetypes=ARCHETYPES, industries=None, renders=False):
    """A work folder as extract + labelling leave it: slide-NN.json, labels/slide-NN.json and optional renders."""
    work = lib / "work" / DECK
    (work / "labels").mkdir(parents=True)
    for n, a in enumerate(archetypes, 1):
        (work / f"slide-{n:02d}.json").write_text(json.dumps({"deck_id": DECK, "slide": n, "regions": []}))
        (work / "labels" / f"slide-{n:02d}.json").write_text(json.dumps({
            "archetype": a, "industry": (industries or ["technology"] * len(archetypes))[n - 1],
            "purpose": f"Purpose of a {a.replace('-', ' ')} slide"}))
        if renders:
            Image.new("RGB", (1280, 720), (40 * (n % 6), 90, 160)).save(work / f"slide-{n:02d}.png")
    (work / "style.json").write_text(json.dumps({"style": "consulting-structured"}))
    return work


def _flow(work, sections=SECTIONS, arc="problem-to-solution", why=WHY):
    (work / "flow.json").write_text(json.dumps({"sections": sections, "arc": arc, "why_the_flow_works": why}))


def test_flow_schema_is_fixed_lists_and_one_free_text_field():
    schema = json.loads(flow.SCHEMA_PATH.read_text())
    assert flow.SCHEMA_PATH.name == "flow.v2.json"
    assert set(schema["properties"]) == {"sections", "arc", "why_the_flow_works", "impact", "builds_on"}
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == {"sections", "arc", "why_the_flow_works"}  # v1 flows stay valid
    assert flow.IMPACTS == ["none", "build", "spotlight", "shade_ribbon", "repeat"]
    assert flow.SECTIONS == ["cover", "hook", "executive-summary", "agenda", "situation", "problem-analysis", "customer",
                             "competition", "solution", "how-it-works", "implementation", "financials", "valuation",
                             "transaction", "financing", "returns", "risks", "kpis", "closing", "appendix", "other"]
    assert flow.ARCS == ["problem-to-solution", "pillars", "journey", "options-to-pick", "chronological",
                          "thesis-to-returns", "other"]
    jsonschema.Draft202012Validator.check_schema(schema)


@pytest.mark.parametrize("edit, error", [
    (lambda f: f.update(sections=f["sections"][:-1]), "12"),
    (lambda f: f["sections"].__setitem__(0, "title"), "sections"),
    (lambda f: f.update(arc="hero"), "arc"),
    (lambda f: f.update(why_the_flow_works="too short"), "why_the_flow_works"),
    (lambda f: f.update(why_the_flow_works="x" * 401), "why_the_flow_works"),
    (lambda f: f.update(notes="extra free text"), "notes"),
    (lambda f: f.pop("arc"), "arc"),
])
def test_validate_rejects_anything_off_schema_or_the_wrong_length(edit, error):
    f = {"sections": list(SECTIONS), "arc": "pillars", "why_the_flow_works": WHY}
    flow.validate(f, len(SECTIONS))
    edit(f)
    with pytest.raises(ValueError, match=error):
        flow.validate(f, len(SECTIONS))


# 12 slides: 4-6 a build, 8 a spotlight of 7, 9 the shaded 8 with a ribbon, 12 repeats the cover
IMPACT = ["none", "none", "none", "build", "build", "build", "none", "spotlight", "shade_ribbon", "none", "none",
          "repeat"]
BUILDS_ON = [None, None, None, None, 4, 5, None, 7, 8, None, None, 1]


def test_validate_accepts_v1_and_v2_flows():
    flow.validate({"sections": list(SECTIONS), "arc": "pillars", "why_the_flow_works": WHY}, len(SECTIONS))
    flow.validate({"sections": list(SECTIONS), "arc": "pillars", "why_the_flow_works": WHY, "impact": list(IMPACT),
                   "builds_on": list(BUILDS_ON)}, len(SECTIONS))


@pytest.mark.parametrize("edit, error", [
    (lambda f: f.update(impact=f["impact"][:-1]), "impact: 11 entries for 12"),
    (lambda f: f.update(builds_on=f["builds_on"] + [None]), "builds_on: 13 entries for 12"),
    (lambda f: f["impact"].__setitem__(0, "hero_reveal"), "impact"),
    (lambda f: f.pop("builds_on"), "builds_on"),
    (lambda f: f.pop("impact"), "impact"),
    (lambda f: f["builds_on"].__setitem__(11, 12), "step 12 builds on 12"),  # itself
    (lambda f: f["builds_on"].__setitem__(7, 9), "step 8 builds on 9"),  # a later step
    (lambda f: f["builds_on"].__setitem__(11, 0), "builds_on"),
    (lambda f: f["builds_on"].__setitem__(11, 1.0), "step 12 builds on 1.0"),
    (lambda f: f["builds_on"].__setitem__(11, "1"), "builds_on"),
    (lambda f: f["builds_on"].__setitem__(1, 1), "step 2 is not an impact slide"),
    (lambda f: f["builds_on"].__setitem__(5, 4), "step 6 is a build"),  # a build points to the step before
])
def test_validate_rejects_impact_off_schema_or_builds_on_out_of_range(edit, error):
    f = {"sections": list(SECTIONS), "arc": "pillars", "why_the_flow_works": WHY, "impact": list(IMPACT),
         "builds_on": list(BUILDS_ON)}
    edit(f)
    with pytest.raises(ValueError, match=re.escape(error)):
        flow.validate(f, len(SECTIONS))


@pytest.mark.parametrize("n, bucket", [(6, "short"), (10, "short"), (11, "medium"), (25, "medium"), (26, "long")])
def test_length_buckets(n, bucket):
    assert flow.length_bucket(n) == bucket


def test_build_flow_computes_steps_dividers_pacing_bucket_industry_and_description(lib):
    industries = ["technology"] * 5 + ["consumer-retail"] * 6 + ["cross-industry"]
    work = _deck(lib, industries=industries)
    _flow(work)
    rec = flow.build_flow(DECK, lib)
    assert json.loads((work / "flow-record.json").read_text()) == rec
    assert not (lib / "flows").exists()  # the leak check publishes, never the build
    assert rec["id"] == rec["deck_id"] == DECK and rec["schema_version"] == "deck-flow/v2"
    assert rec["arc"] == "problem-to-solution" and rec["why_the_flow_works"] == WHY
    assert rec["steps"][0] == {"id": f"{DECK}-01", "archetype": "title", "section": "cover", "impact": "none",
                               "builds_on": None}
    assert set(rec) == flow.RECORD_KEYS and all(set(s) == flow.STEP_KEYS for s in rec["steps"])
    assert [s["id"] for s in rec["steps"]] == [f"{DECK}-{n:02d}" for n in range(1, 13)]
    assert [s["section"] for s in rec["steps"]] == SECTIONS
    assert [s["archetype"] for s in rec["steps"]] == ARCHETYPES
    assert rec["dividers"] == [5, 8]
    assert rec["pacing"] == [{"section": "cover", "slides": 1}, {"section": "hook", "slides": 1},
                             {"section": "executive-summary", "slides": 2}, {"section": "situation", "slides": 2},
                             {"section": "problem-analysis", "slides": 1}, {"section": "solution", "slides": 3},
                             {"section": "closing", "slides": 1}, {"section": "appendix", "slides": 1}]
    assert rec["length_bucket"] == "medium" and rec["industry"] == "consumer-retail"
    assert rec["style"] == "consulting-structured"
    d = rec["description"]
    assert "Style: consulting structured." in d
    assert not re.search(r"\d", d)
    assert "problem to solution" in d and WHY in d
    assert "cover, hook, executive summary, situation, problem analysis, solution, closing, appendix" in d
    assert "section divider" in d and "title" in d
    assert "Impact slides: none." in d  # a v1 flow marks no impact slides


def test_build_flow_carries_impact_into_steps_and_summarises_it_in_words(lib):
    work = _deck(lib)
    (work / "flow.json").write_text(json.dumps({"sections": SECTIONS, "arc": "pillars", "why_the_flow_works": WHY,
                                                "impact": IMPACT, "builds_on": BUILDS_ON}))
    rec = flow.build_flow(DECK, lib)
    assert [s["impact"] for s in rec["steps"]] == IMPACT and [s["builds_on"] for s in rec["steps"]] == BUILDS_ON
    assert set(rec) == flow.RECORD_KEYS and all(set(s) == flow.STEP_KEYS for s in rec["steps"])
    d = rec["description"]
    assert "Impact slides: three build, one spotlight, one shade ribbon, one repeat." in d
    assert not re.search(r"\d", d)


def test_industry_tie_goes_to_the_first_in_deck_order(lib):
    work = _deck(lib, ARCHETYPES[:6], industries=["energy-utilities", "technology", "technology", "energy-utilities",
                                                  "automotive", "automotive"])
    _flow(work, SECTIONS[:6])
    assert flow.build_flow(DECK, lib)["industry"] == "energy-utilities"


def test_build_flow_is_deterministic(lib):
    work = _deck(lib)
    _flow(work)
    first = (flow.build_flow(DECK, lib), (work / "flow-record.json").read_bytes())
    assert (flow.build_flow(DECK, lib), (work / "flow-record.json").read_bytes()) == first


def test_decks_under_six_visible_slides_are_skipped(lib, capsys):
    work = _deck(lib, ARCHETYPES[:5], renders=True)
    _flow(work, SECTIONS[:5])
    assert flow.build_flow(DECK, lib) is None and flow.prep(DECK, lib) is None
    assert not (work / "flow-record.json").exists() and not (work / "flow.prompt.txt").exists()
    for stage in ("flow-prep", "flow-build"):
        main([stage, DECK, "--library", str(lib)])
        assert "fewer than 6 visible slides" in capsys.readouterr().out


def test_build_flow_refuses_a_missing_or_invalid_flow_or_labels(lib):
    work = _deck(lib)
    with pytest.raises(SystemExit, match="flow.json"):
        flow.build_flow(DECK, lib)
    _flow(work, SECTIONS[:-1])
    with pytest.raises(SystemExit, match="12"):
        flow.build_flow(DECK, lib)
    _flow(work)
    for bad in ("", '{"style": "neon-brutalist"}'):  # every flow record carries the deck's style
        (work / "style.json").write_text(bad)
        with pytest.raises(SystemExit, match="style.json"):
            flow.build_flow(DECK, lib)
    (work / "labels" / "slide-03.json").unlink()
    with pytest.raises(SystemExit, match="slide-03"):
        flow.build_flow(DECK, lib)
    assert not (work / "flow-record.json").exists()


def test_flow_prep_writes_worksheet_and_contact_sheet(lib, capsys):
    work = _deck(lib, renders=True)
    main(["flow-prep", DECK, "--library", str(lib)])
    assert "flow.prompt.txt" in capsys.readouterr().out
    text = (work / "flow.prompt.txt").read_text()
    sheet = work / "flow-contact-sheet.png"
    assert str(sheet.absolute()) in text and str((work / "flow.json").absolute()) in text
    assert str(flow.SCHEMA_PATH) in text
    assert all(s in text for s in flow.SECTIONS) and all(a in text for a in flow.ARCS)
    for n, a in enumerate(ARCHETYPES, 1):  # each slide's archetype and purpose, from its labels
        assert f"{n:02d}  {a}  Purpose of a {a.replace('-', ' ')} slide" in text
    rules = (flow.HERE / "templates" / "labeling.txt").read_text().split("Hard rules", 1)[1].split("===")[0]
    for line in (ln for ln in rules.splitlines()[1:] if ln.strip().startswith("- ") or ln.startswith("    ")):
        assert line in text, line  # the slide worksheet's leak rules, verbatim
    assert "every slide" in text.lower()
    img = Image.open(sheet)
    assert img.width >= 1000 and img.height >= 3 * 180  # every slide on one sheet, several rows of readable tiles


def test_flow_prep_needs_slide_renders(lib):
    _deck(lib)
    with pytest.raises(SystemExit, match="render"):
        flow.prep(DECK, lib)


def _duplicate_pair(lib, a=8, b=9):
    """Slides a and b share a layout and (solid-colour) renders hash alike, so dedupe drops b as a duplicate of a."""
    lay = lib / "layouts" / DECK
    lay.mkdir(parents=True)
    for n in (a, b):
        (lay / f"slide-{n:02d}.v3.json").write_text(json.dumps(
            {"version": 3, "components": [{"kind": "card_row", "box": [0, 0, 1, 0.5], "n": 3}]}))


def test_flow_prep_worksheet_defines_impact_slides_and_lists_duplicate_hints(lib):
    work = _deck(lib, renders=True)
    _duplicate_pair(lib)
    flow.prep(DECK, lib)
    text = (work / "flow.prompt.txt").read_text()
    for kind in flow.IMPACTS:
        assert kind in text
    for definition in ("reveals elements one by one across consecutive slides", "one element highlighted",
                       "shaded with a ribbon carrying a so-what", "recap or bookend"):
        assert definition in text
    assert "builds_on" in text
    assert "09  duplicate_of 08 (spotlight/build?)" in text


def test_flow_prep_impact_only_asks_to_add_impact_and_change_nothing_else(lib, capsys):
    work = _deck(lib, renders=True)
    with pytest.raises(SystemExit, match="flow.json"):
        flow.prep(DECK, lib, impact_only=True)  # nothing to add to yet
    _flow(work)
    _duplicate_pair(lib)
    main(["flow-prep", DECK, "--impact-only", "--library", str(lib)])
    out = work / "flow-impact.prompt.txt"
    assert str(out) in capsys.readouterr().out
    assert not (work / "flow.prompt.txt").exists()  # the original worksheet is a separate file
    text = out.read_text()
    assert str((work / "flow.json").absolute()) in text and str(flow.SCHEMA_PATH) in text
    assert "ADD" in text and "change nothing else" in text
    assert "reveals elements one by one across consecutive slides" in text and "recap or bookend" in text
    assert "09  duplicate_of 08 (spotlight/build?)" in text
    for n, a in enumerate(ARCHETYPES, 1):
        assert f"{n:02d}  {a}  Purpose of a {a.replace('-', ' ')} slide" in text
    assert "why_the_flow_works  why the order" not in text  # no new free text is asked for
