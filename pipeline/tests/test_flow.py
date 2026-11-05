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
    return work


def _flow(work, sections=SECTIONS, arc="problem-to-solution", why=WHY):
    (work / "flow.json").write_text(json.dumps({"sections": sections, "arc": arc, "why_the_flow_works": why}))


def test_flow_schema_is_fixed_lists_and_one_free_text_field():
    schema = json.loads(flow.SCHEMA_PATH.read_text())
    assert set(schema["properties"]) == {"sections", "arc", "why_the_flow_works"}
    assert schema["additionalProperties"] is False and set(schema["required"]) == set(schema["properties"])
    assert flow.SECTIONS == ["cover", "hook", "executive-summary", "agenda", "situation", "problem-analysis", "customer",
                             "competition", "solution", "how-it-works", "implementation", "financials", "risks", "kpis",
                             "closing", "appendix", "other"]
    assert flow.ARCS == ["problem-to-solution", "pillars", "journey", "options-to-pick", "chronological", "other"]
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
    assert rec["id"] == rec["deck_id"] == DECK and rec["schema_version"] == "deck-flow/v1"
    assert rec["arc"] == "problem-to-solution" and rec["why_the_flow_works"] == WHY
    assert rec["steps"][0] == {"id": f"{DECK}-01", "archetype": "title", "section": "cover"}
    assert [s["id"] for s in rec["steps"]] == [f"{DECK}-{n:02d}" for n in range(1, 13)]
    assert [s["section"] for s in rec["steps"]] == SECTIONS
    assert [s["archetype"] for s in rec["steps"]] == ARCHETYPES
    assert rec["dividers"] == [5, 8]
    assert rec["pacing"] == [{"section": "cover", "slides": 1}, {"section": "hook", "slides": 1},
                             {"section": "executive-summary", "slides": 2}, {"section": "situation", "slides": 2},
                             {"section": "problem-analysis", "slides": 1}, {"section": "solution", "slides": 3},
                             {"section": "closing", "slides": 1}, {"section": "appendix", "slides": 1}]
    assert rec["length_bucket"] == "medium" and rec["industry"] == "consumer-retail"
    d = rec["description"]
    assert not re.search(r"\d", d)
    assert "problem to solution" in d and WHY in d
    assert "cover, hook, executive summary, situation, problem analysis, solution, closing, appendix" in d
    assert "section divider" in d and "title" in d


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
