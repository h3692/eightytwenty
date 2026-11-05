import json
import os
import shutil

import pytest
from PIL import Image

from pipeline import build, extract, flow, label_prep, leak_check, mockup
from pipeline.tests.conftest import CLIENT, EXCLUDED, fixture_labels, fixture_style
from pipeline.tests.test_mockup import SLIDES

LAYOUT = {"version": 3, "components": [{"kind": "logo"}, {"kind": "text", "box": [0, 0, 1, 1], "lines": 3}]}


def mockups(lib, deck_id, slides=(1, 2), plant=lambda prs: None):
    """A v3 layout per slide and its mockup: the .pptx built for real, a stand-in PNG (no LibreOffice needed)."""
    for n in slides:
        lay, out = lib / "layouts" / deck_id, lib / "mockups" / deck_id
        lay.mkdir(parents=True, exist_ok=True)
        out.mkdir(parents=True, exist_ok=True)
        (lay / f"slide-{n:02d}.v3.json").write_text(json.dumps(LAYOUT))
        prs = mockup.build_mockup_v3(LAYOUT)
        plant(prs)
        mockup.save(prs, out / f"slide-{n:02d}.pptx")
        Image.new("L", (96, 54), 200 + n).save(out / f"slide-{n:02d}.png")


def _pipeline(deck, lib, edit=lambda n, labels: None):
    deck_id = extract.run(deck, lib, render=False)
    work = label_prep.run(deck_id, lib)
    for f in sorted(work.glob("slide-??.json")):
        labels = fixture_labels(json.loads(f.read_text()))
        edit(int(f.stem[-2:]), labels)
        (work / "labels" / f.name).write_text(json.dumps(labels))
    fixture_style(work)
    ids = build.run(deck_id, lib)
    mockups(lib, deck_id)
    return deck_id, ids


def _judge(lib, deck_id, rid, identified):
    v = lib / "judge" / deck_id / "verdicts"
    if not (v.parent / f"{rid}.json").exists():  # a judge only ever sees copies a leak-check run wrote
        leak_check.run(deck_id, lib)
    v.mkdir(parents=True, exist_ok=True)
    (v / f"{rid}.json").write_text(json.dumps({"identified": identified, "guess": "none"}))


def test_clean_records_wait_for_judge_then_promote(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    report = leak_check.run(deck_id, lib)
    assert {r["auto"] for r in report.values()} == {"pass"} and {r["judge"] for r in report.values()} == {"pending"}
    assert not (lib / "records").exists() or not list((lib / "records").iterdir())
    judge = lib / "judge" / deck_id
    assert (judge / "JUDGE.txt").exists() and all((judge / f"{i}.json").exists() and (judge / f"{i}.png").exists() for i in ids)
    for rid in ids:
        _judge(lib, deck_id, rid, False)
    report = leak_check.run(deck_id, lib)
    assert {r["judge"] for r in report.values()} == {"pass"}
    assert sorted(p.name for p in (lib / "records").iterdir()) == sorted(f"{i}.json" for i in ids)
    assert sorted(p.name for p in (lib / "wireframes").iterdir()) == sorted(f"{i}.png" for i in ids)
    for n, rid in enumerate(ids, 1):  # the mockup, not the old wireframe, is the record's picture
        pic = (lib / "mockups" / deck_id / f"slide-{n:02d}.png").read_bytes()
        assert (lib / "wireframes" / f"{rid}.png").read_bytes() == pic == (judge / f"{rid}.png").read_bytes()
    for sub in ("records", "wireframes", "judge"):
        for p in (lib / sub).rglob("*"):
            if p.is_file():
                data = p.read_bytes().lower()
                assert CLIENT.lower().encode() not in data, p
                assert not any(m.lower().encode() in data for m in EXCLUDED.values()), p


@pytest.mark.parametrize("field, value, problem", [
    ("why_it_works", f"Feels like the {CLIENT} brand book: bold band, one promise", "name"),
    ("why_it_works", "Borrowed from the Toronto subway map that Sarah Lee designed", "name"),
    ("purpose", "Show 3 reasons members stay longer", "digit"),
    ("purpose", "Show the ranking in a 3 column grid", "digit"),
    ("pattern", "points expire too fast then the fix", "shared words"),
])
def test_leaks_in_free_text_fail_closed_even_with_judge_pass(deck, lib, field, value, problem):
    def edit(n, labels):
        if n == 2:
            if field == "pattern":
                labels["text_patterns"][0]["pattern"] = value
            else:
                labels[field] = value
    deck_id, ids = _pipeline(deck, lib, edit)
    for rid in ids:
        _judge(lib, deck_id, rid, False)
    report = leak_check.run(deck_id, lib)
    bad = report[ids[1]]
    assert bad["auto"] == "fail" and any(problem in p for p in bad["problems"]), bad
    assert report[ids[0]]["auto"] == "pass"
    assert not (lib / "records" / f"{ids[1]}.json").exists()
    assert not (lib / "wireframes" / f"{ids[1]}.png").exists()
    assert not (lib / "judge" / deck_id / f"{ids[1]}.json").exists()


def test_design_vocabulary_is_not_a_name():
    assert leak_check.problems_in("Gantt bars and a SWOT grid with KPI tiles and Harvey balls", "", set()) == []
    # plurals too, even when the deck's text tags the word as a name somewhere
    assert leak_check.problems_in("Two Personas side by side", "Personas", {"personas"}) == []


def test_names_from_the_slide_text_are_blocked_even_if_ner_misses_them():
    source = "Zorblax Foods grew loyalty in Ontario"
    tokens = leak_check.source_names(source)
    assert {"zorblax", "ontario"} <= tokens
    assert leak_check.problems_in("A zorblax style promise", source, tokens)


def test_numeric_dna_fields_are_exempt(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    report = leak_check.run(deck_id, lib)
    assert all(r["problems"] == [] for r in report.values())


def test_judge_identification_blocks_and_unpromotes(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    for rid in ids:
        _judge(lib, deck_id, rid, False)
    leak_check.run(deck_id, lib)
    assert (lib / "records" / f"{ids[0]}.json").exists()
    _judge(lib, deck_id, ids[0], True)
    report = leak_check.run(deck_id, lib)
    assert report[ids[0]]["judge"] == "fail"
    assert not (lib / "records" / f"{ids[0]}.json").exists()
    assert not (lib / "wireframes" / f"{ids[0]}.png").exists()


def test_malformed_verdict_counts_as_fail(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    leak_check.run(deck_id, lib)
    v = lib / "judge" / deck_id / "verdicts"
    v.mkdir(exist_ok=True)
    (v / f"{ids[0]}.json").write_text('{"identified": "no"}')
    assert leak_check.run(deck_id, lib)[ids[0]]["judge"] == "fail"


@pytest.mark.parametrize("text", [
    "Summarises financial outcomes with a revenue bar chart and a highlighted growth callout on the left, two "
    "ring-framed headline metrics below, and an assumptions list on the right.",
    "Screenshots are annotated with an accent circle and leader line to the key figure.",
    "A chevron strip with boxed percentages under each stage gives the data story at a glance.",
    "Appendix mosaic of competitor creatives illustrating a shared tactic.",
    "Coloured vertical stage tabs and coloured column headers form a clear matrix.",
    "Why it works: Labels with leader lines point to small objects threaded along one large curved band.",
    "Shows a contribution waterfall, space allocation, breakeven figures and returns.",
    "italic persona descriptor with age range",
])
def test_ordinary_words_ner_mislabels_are_not_names(text):
    assert leak_check.problems_in(text, "", set()) == []


def test_common_words_from_slide_entities_are_not_names():
    names = {"channels", "business", "vision", "metrics", "research", "purchase", "data", "customer", "company",
             "challenges", "breakeven", "short", "question", "plan", "overview"}
    text = ("a short overview of the business plan: channels, vision, metrics, research and purchase data per "
            "customer, then company challenges, breakeven and the question")
    assert leak_check.problems_in(text, "", names) == []


CASE_TERMS = ["financials", "Financials", "deliverables", "storyboard", "Storyboard", "FAQ", "KPI", "KPIs", "roadmap",
              "Gantt", "persona", "agenda", "appendix", "takeaway", "benchmark", "playbook", "scorecard", "dashboard",
              "wireframe", "mockup", "timeline", "pillar", "pillars", "workstream", "workstreams", "milestone",
              "milestones", "synergy", "synergies", "CAGR", "ROI", "NPV", "EBITDA", "TAM", "SAM", "SOM", "B2B", "B2C",
              "D2C", "SKU", "SKUs", "go-to-market", "Go-to-Market", "GTM"]


def _schema_values():
    s = {n: json.loads((leak_check.Path(leak_check.__file__).parent / "schema" / f"{n}.json").read_text())
         for n in ("labels.v1", "flow.v1", "layout.v3", "style.v1")}
    p = s["labels.v1"]["properties"]
    return sorted({v for vs in [*(p[k]["enum"] for k in ("archetype", "argument_shape", "insight_device", "data_type")),
                                s["labels.v1"]["$defs"]["role"]["enum"], s["style.v1"]["properties"]["style"]["enum"],
                                s["flow.v1"]["properties"]["sections"]["items"]["enum"],
                                s["layout.v3"]["$defs"]["component"]["properties"]["kind"]["enum"]] for v in vs})


@pytest.mark.parametrize("word", CASE_TERMS + _schema_values()
                         + ["Situational / company analysis", "KPIs, Risks & Mitigations", "Hook / opener"])
def test_our_own_vocabulary_is_never_a_name_even_when_the_slide_uses_it(word):
    plain = word.replace("_", " ") if "_" in word else word  # component kinds are snake_case ids
    source = f"Quillmoor {plain} review\n{plain.upper()}"
    names = leak_check.source_names(source) | set(leak_check._words(plain))
    assert leak_check.problems_in(f"A calm {plain} band carries one promise", source, names) == []


@pytest.mark.parametrize("text, source", [
    ("a four-column strengths, weaknesses, opportunities and threats band", "STRENGTHS\nWEAKNESSES\nOPPORTUNITIES\nTHREATS"),
    ("a political, economic, social, technological, legal, environmental grid", "Political Economic Social Technological Legal Environmental"),
    ("nested total addressable market rings", "Total addressable market"),
])
def test_standard_framework_phrases_are_not_copied_text(text, source):
    assert leak_check.problems_in(text, source, set()) == []


@pytest.mark.parametrize("heading", ["Why it works", "WHY IT WORKS\nPurpose\nLayout", "Why it works: the plan",
                                     "When to use: the plan"])
def test_our_description_template_phrases_are_not_copied_text(heading):
    dna = {"archetype": "situational-analysis", "argument_shape": "evidence-stack", "insight_device": "big-number",
           "data_type": "kpi-numbers", "industry": "travel-hospitality", "purpose": "Open with one bold promise",
           "why_it_works": "A single dominant statement makes the promise unmissable", "style": "data-led",
           "when_to_use": "Opening a pitch on one promise", "effect": "The promise lands first",
           "regions": [{"role": "title", "text": {"pattern": "outcome promise as a short noun phrase"}}]}
    assert ["why", "it", "works"] in leak_check.FRAMEWORKS  # computed from build.describe, not retyped
    assert leak_check.problems_in(build.describe(dna), heading, set()) == []
    assert leak_check.problems_in(build.describe(dna), "Open with one bold promise", set())  # real copies still fail


@pytest.mark.parametrize("text, source, problem", [
    ("Echoes the Quillmoor Analytics house style with a dark band", "", "name"),
    ("Styled after the London Underground map with coloured lines", "", "name"),
    ("A layout that Priya Raman sketched on a whiteboard", "", "name"),
    ("A quillmoor style promise band", "Quillmoor Analytics grew loyalty in Ontario", "name"),
    ("A loyalty band in the Ontario style", "Quillmoor Analytics grew loyalty in Ontario", "name"),
    ("A LOYALTY band", "Quillmoor Analytics grew LOYALTY in Ontario", "name"),
    ("A band in 2 tones", "", "digit"),
    ("A B2B band in 2 tones", "", "digit"),
    ("A calm FAQ band in the Quillmoor style", "Quillmoor Analytics FAQ", "name"),
    ("A roadmap that Priya Raman sketched", "", "name"),
    ("A Toronto storyboard with one band", "Toronto storyboard", "name"),
    ("bands for financials storyboard deliverables", "Financials storyboard deliverables", "shared words"),
    ("bands for secondary research, primary research and objective", "Secondary research and objective", "shared words"),
    ("headline urging a focus on untapped segments", "Focus on untapped segments", "shared words"),
])
def test_real_names_numbers_and_copies_still_fail(text, source, problem):
    found = leak_check.problems_in(text, source, leak_check.source_names(source))
    assert any(problem in p for p in found), found


@pytest.mark.parametrize("text, words", [
    ("A coral wordmark with a smiling mascot letter", "coral, mascot, wordmark"),
    ("A blue field with world-map dot texture and a colourful ribbon swoosh", "blue, swoosh, world map"),
    ("Three sponsor logos inside a thin red frame", "red, sponsor"),
    ("A bespoke botanical illustration and logo lockup on a green watercolour wash", "botanical, green, lockup"),
    ("A team affiliation list under the title", "affiliation"),
    ("A row of portraits, two corner logos and a domain banner", "domain, portraits"),
    ("A reddish band and a bluish tint behind the title", "bluish, reddish"),
    ("Teal, navy and gold blocks with a crimson accent", "crimson, gold, navy, teal"),
    ("A monogram, an emblem, a crest and a watermark", "crest, emblem, monogram, watermark"),
    ("A logomark beside the signature", "logomark, signature"),
    ("Brand art and a brand motif frame the brand illustration", "brand art, brand illustration, brand motif"),
    ("Footer carries the acme.com address", "acme.com"),
    ("A skyline and a landmark behind a cartoon character", "character, landmark, skyline"),
    ("An owl illustration next to the title", "owl"),
])
def test_brand_identity_words_fail_closed(text, words):
    assert f"brand identity: {words}" in leak_check.problems_in(text, "", set())


@pytest.mark.parametrize("text", [
    "Primary fill with an accent rule, a brand-colour fill band, dark and light panels, mid-grey text, black on white",
    "A greyscale photo with a tint, a shade, saturated headers and muted labels",
    "logo top right, a title band and two headshot slots below",
    "An illustration, a photo, an icon row, an image and a map",
    "The chart sits left and leaves quiet space around it",
])
def test_role_and_placement_words_are_not_brand_identity(text):
    assert leak_check.problems_in(text, "", set()) == []


@pytest.mark.parametrize("missing, problem", [("layouts/{d}/slide-02.v3.json", "no v3 layout"),
                                              ("mockups/{d}/slide-02.png", "no mockup"),
                                              ("mockups/{d}/slide-02.pptx", "no mockup")])
def test_records_without_a_layout_or_mockup_fail_closed(deck, lib, missing, problem):
    deck_id, ids = _pipeline(deck, lib)
    for rid in ids:
        _judge(lib, deck_id, rid, False)
    leak_check.run(deck_id, lib)
    assert (lib / "records" / f"{ids[1]}.json").exists()  # published while complete
    (lib / missing.format(d=deck_id)).unlink()
    report = leak_check.run(deck_id, lib)
    assert report[ids[1]]["auto"] == "fail" and any(problem in p for p in report[ids[1]]["problems"])
    assert report[ids[0]]["auto"] == "pass" and (lib / "records" / f"{ids[0]}.json").exists()
    for p in (lib / "records" / f"{ids[1]}.json", lib / "wireframes" / f"{ids[1]}.png",
              lib / "judge" / deck_id / f"{ids[1]}.json", lib / "judge" / deck_id / f"{ids[1]}.png"):
        assert not p.exists(), p


def _picture(prs, tmp_path):
    Image.new("RGB", (8, 8), (200, 30, 30)).save(tmp_path / "p.png")
    prs.slides[0].shapes.add_picture(str(tmp_path / "p.png"), 0, 0)


@pytest.mark.parametrize("plant, problem", [
    (lambda prs, t: setattr(prs.slides[0].shapes.add_textbox(0, 0, 9, 9).text_frame, "text", f"{CLIENT} Foods"),
     "text"),
    (lambda prs, t: setattr(prs.slides[0].shapes.add_textbox(0, 0, 9, 9).text_frame, "text", "Text here!"), "text"),
    (lambda prs, t: setattr(prs.core_properties, "author", "Sarah Lee"), "properties"),
    (lambda prs, t: setattr(prs.core_properties, "keywords", CLIENT), "properties"),
    (_picture, "image"),
])
def test_mockup_pptx_outside_the_whitelist_fails_the_record(deck, lib, tmp_path, plant, problem):
    deck_id, ids = _pipeline(deck, lib)
    mockups(lib, deck_id, slides=(2,), plant=lambda prs: plant(prs, tmp_path))
    for rid in ids:
        _judge(lib, deck_id, rid, False)
    report = leak_check.run(deck_id, lib)
    assert report[ids[1]]["auto"] == "fail" and any(p.startswith("mockup") and problem in p
                                                    for p in report[ids[1]]["problems"]), report[ids[1]]
    assert report[ids[0]]["auto"] == "pass"
    assert not (lib / "records" / f"{ids[1]}.json").exists() and not (lib / "wireframes" / f"{ids[1]}.png").exists()


@pytest.mark.parametrize("name", SLIDES)
def test_clean_mockups_of_every_kind_pass_the_whitelist(tmp_path, name):
    mockup.save(mockup.build_mockup_v3(SLIDES[name]), tmp_path / "m.pptx")
    assert leak_check.mockup_problems(tmp_path / "m.pptx") == []


def test_judge_worksheet_is_about_mockups(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    leak_check.run(deck_id, lib)
    text = (lib / "judge" / deck_id / "JUDGE.txt").read_text()
    assert "mockup" in text and all(i in text for i in ids)
    assert not any(w in text.lower() for w in ("outline", "path", "trace"))
    assert ("Specific brand colours, mascots, wordmarks, sponsor logos, what an illustration depicts and a highly\n"
            "specific operating model (named site types, routes or steps) count as identifying too.") in text


def _app_xml(old, new):
    def plant(prs, t):
        part = next(p for p in prs.part.package.iter_parts() if p.partname == "/docProps/app.xml")
        assert old.encode() in part._blob
        part._blob = part._blob.replace(old.encode(), new.encode())
    return plant


@pytest.mark.parametrize("plant, problem", [
    (_app_xml("<Company></Company>", f"<Company>{CLIENT} Foods</Company>"), "app properties"),
    (_app_xml("<Manager></Manager>", "<Manager>Sarah Lee</Manager>"), "app properties"),
    (_app_xml("<HyperlinkBase></HyperlinkBase>", f"<HyperlinkBase>https://{CLIENT}.example/</HyperlinkBase>"),
     "app properties"),
    (_app_xml("<vt:lpstr>Office Theme</vt:lpstr>", f"<vt:lpstr>{CLIENT} Theme</vt:lpstr>"), "app properties"),
    (lambda prs, t: setattr(prs.slides[0].shapes.add_textbox(0, 0, 9, 9).text_frame, "text",
                            "Click to edit Master title style"), "text"),  # stock boilerplate outside the master
])
def test_mockup_app_properties_and_slide_boilerplate_fail_the_record(deck, lib, plant, problem):
    assert "Click to edit Master title style" in leak_check._stock_text()
    test_mockup_pptx_outside_the_whitelist_fails_the_record(deck, lib, None, plant, problem)


def test_stale_mockup_older_than_its_layout_fails_closed(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    for rid in ids:
        _judge(lib, deck_id, rid, False)
    leak_check.run(deck_id, lib)
    assert (lib / "records" / f"{ids[1]}.json").exists()
    layout = lib / "layouts" / deck_id / "slide-02.v3.json"
    later = (lib / "mockups" / deck_id / "slide-02.png").stat().st_mtime + 60
    os.utime(layout, (later, later))
    report = leak_check.run(deck_id, lib)
    assert report[ids[1]]["auto"] == "fail" and any("stale" in p for p in report[ids[1]]["problems"])
    assert report[ids[0]]["auto"] == "pass"
    assert not (lib / "records" / f"{ids[1]}.json").exists() and not (lib / "wireframes" / f"{ids[1]}.png").exists()


FLOW_WHY = "Opens on one bold promise, stacks the evidence, then lands the plan before any detail"


def _six_slide_deck(deck, lib, why=FLOW_WHY, with_flow=True):
    """The fixture deck grown to six visible slides (slide 2 repeated; slide 5 names another firm), labelled, built,
    drawn and given a flow record."""
    deck_id = extract.run(deck, lib, render=False)
    work = lib / "work" / deck_id
    for n in range(3, 7):
        s = json.loads((work / "slide-02.json").read_text())
        s["slide"] = n
        (work / f"slide-{n:02d}.json").write_text(json.dumps(s))
        shutil.copyfile(work / "text" / "slide-02.txt", work / "text" / f"slide-{n:02d}.txt")
    (work / "text" / "slide-05.txt").write_text("Quillmoor Analytics backs the plan")
    label_prep.run(deck_id, lib)
    for f in sorted(work.glob("slide-??.json")):
        (work / "labels" / f.name).write_text(json.dumps(fixture_labels(json.loads(f.read_text()))))
    fixture_style(work)
    ids = build.run(deck_id, lib)
    mockups(lib, deck_id, slides=range(1, 7))
    if with_flow:
        (work / "flow.json").write_text(json.dumps({
            "sections": ["cover", "executive-summary", "situation", "situation", "solution", "closing"],
            "arc": "problem-to-solution", "why_the_flow_works": why}))
        flow.build_flow(deck_id, lib)
    return deck_id, ids


def test_flow_waits_for_the_judge_then_publishes_with_its_slides(deck, lib):
    deck_id, ids = _six_slide_deck(deck, lib)
    judge, published = lib / "judge" / deck_id, lib / "flows" / f"{deck_id}.json"
    report = leak_check.run(deck_id, lib)
    assert report["flow"]["auto"] == "pass" and report["flow"]["judge"] == "pending" and not published.exists()
    assert (judge / "flow.json").read_text() == (lib / "work" / deck_id / "flow-record.json").read_text()
    text = (judge / "JUDGE.txt").read_text()
    assert "flow.json" in text and "verdicts/flow.json" in text and "whole deck" in text
    for rid in ids:
        _judge(lib, deck_id, rid, False)
    assert not leak_check.run(deck_id, lib)["flow"]["published"]  # no flow verdict yet
    _judge(lib, deck_id, "flow", False)
    report = leak_check.run(deck_id, lib)
    assert report["flow"] == {"auto": "pass", "problems": [], "judge": "pass", "published": True}
    assert json.loads(published.read_text()) == json.loads((judge / "flow.json").read_text())
    _judge(lib, deck_id, "flow", True)  # identified later: withdrawn
    assert leak_check.run(deck_id, lib)["flow"]["judge"] == "fail" and not published.exists()


@pytest.mark.parametrize("why, problem", [
    ("Builds trust the quillmoor way, then lands the plan before any detail", "name from slide text"),
    ("Opens with members who redeem twice, then lands the plan before any detail", "shared words"),
    ("Opens on one promise, then lands the plan in 2 moves", "digit"),
    ("Opens on a teal cover with the mascot, then lands the plan", "brand identity: mascot, teal"),
])
def test_flow_text_is_checked_against_every_slide_of_the_deck(deck, lib, why, problem):
    deck_id, ids = _six_slide_deck(deck, lib, why=why)
    for rid in [*ids, "flow"]:
        _judge(lib, deck_id, rid, False)
    report = leak_check.run(deck_id, lib)
    assert all(report[rid]["published"] for rid in ids)
    assert report["flow"]["auto"] == "fail" and any(problem in p for p in report["flow"]["problems"]), report["flow"]
    assert not (lib / "flows" / f"{deck_id}.json").exists() and not (lib / "judge" / deck_id / "flow.json").exists()


@pytest.mark.parametrize("withheld, published", [(2, True), (3, False)])
def test_flow_is_withheld_unless_sixty_percent_of_its_slides_are_published(deck, lib, withheld, published):
    deck_id, ids = _six_slide_deck(deck, lib)
    for k, rid in enumerate(ids):
        _judge(lib, deck_id, rid, k < withheld)
    _judge(lib, deck_id, "flow", False)
    report = leak_check.run(deck_id, lib)
    assert report["flow"]["auto"] == "pass" and report["flow"]["judge"] == "pass"
    assert report["flow"]["published"] is published and (lib / "flows" / f"{deck_id}.json").exists() is published
    if not published:
        assert any("60%" in p for p in report["flow"]["problems"])


@pytest.mark.parametrize("withheld, published", [(1, True), (2, False)])
def test_the_sixty_percent_rule_counts_only_slides_not_excluded(deck, lib, withheld, published):
    deck_id, ids = _six_slide_deck(deck, lib)
    (lib / "layouts" / deck_id / "slide-01.v3.json").write_text(json.dumps({"version": 3, "blank": True, "components": []}))
    for n in (3, 4):  # slide 3 duplicates slide 4: four slides left, of which the first `withheld` are identified
        Image.new("L", (64, 36), 128).save(lib / "work" / deck_id / f"slide-{n:02d}.png")
    for k, rid in enumerate((ids[1], *ids[3:])):
        _judge(lib, deck_id, rid, k < withheld)
    _judge(lib, deck_id, "flow", False)
    report = leak_check.run(deck_id, lib)
    assert report["flow"]["published"] is published, report["flow"]
    if not published:
        assert any("of 4 slides" in p for p in report["flow"]["problems"])


def test_a_long_deck_without_a_flow_record_is_reported_and_short_decks_have_none(deck, lib):
    deck_id, ids = _six_slide_deck(deck, lib, with_flow=False)
    report = leak_check.run(deck_id, lib)
    assert report["flow"]["auto"] == "fail" and "flow-prep" in report["flow"]["problems"][0]
    short_id, _ = _pipeline(deck, lib)
    assert "flow" not in leak_check.run(short_id, lib)


def test_flow_record_with_extra_free_text_fails_closed(deck, lib):
    deck_id, ids = _six_slide_deck(deck, lib)
    rec = lib / "work" / deck_id / "flow-record.json"
    rec.write_text(json.dumps(dict(json.loads(rec.read_text()), notes=f"{CLIENT} deck")))
    report = leak_check.run(deck_id, lib)
    assert report["flow"]["auto"] == "fail" and report["flow"]["problems"][0].startswith("schema")


def test_blank_and_duplicate_slides_are_withdrawn_and_never_judged(deck, lib, capsys):
    from pipeline.__main__ import main
    deck_id, ids = _six_slide_deck(deck, lib)
    for rid in [*ids, "flow"]:
        _judge(lib, deck_id, rid, False)
    assert all(r["published"] for r in leak_check.run(deck_id, lib).values())
    (lib / "layouts" / deck_id / "slide-01.v3.json").write_text(json.dumps({"version": 3, "blank": True, "components": []}))
    for n in (3, 4):  # slide 4 repeats slide 3 exactly: the later one is kept
        Image.new("L", (64, 36), 128).save(lib / "work" / deck_id / f"slide-{n:02d}.png")
    report = leak_check.run(deck_id, lib)
    for rid, reason in ((ids[0], "blank"), (ids[2], f"duplicate_of {ids[3]}")):
        assert report[rid] == {"auto": "excluded", "problems": [reason], "judge": "excluded", "published": False,
                               "excluded": reason}
        assert not any((lib / d / f"{rid}{ext}").exists() for d in ("records", "wireframes", f"judge/{deck_id}")
                       for ext in (".json", ".png"))
        assert rid not in (lib / "judge" / deck_id / "JUDGE.txt").read_text()
    assert all(report[rid]["published"] for rid in (ids[1], *ids[3:])) and report["flow"]["published"]
    main(["leak-check", deck_id, "--library", str(lib)])  # exclusions are not failures: no exit 1
    assert f"{ids[0]}  auto=excluded  judge=excluded  blank" in capsys.readouterr().out


def test_flow_record_steps_with_extra_keys_or_bad_impact_fail_closed(deck, lib):
    deck_id, ids = _six_slide_deck(deck, lib)
    rec = lib / "work" / deck_id / "flow-record.json"
    good = json.loads(rec.read_text())
    assert leak_check.check_flow(good, "") == []
    marked = json.loads(json.dumps(good))
    marked["steps"][3].update(impact="spotlight", builds_on=3)
    assert leak_check.check_flow(marked, "") == []
    for edit in (lambda s: s.update(notes=f"{CLIENT} slide"), lambda s: s.pop("impact"),
                 lambda s: s.update(builds_on=5), lambda s: s.update(impact="hero_reveal")):
        bad = json.loads(json.dumps(marked))
        edit(bad["steps"][3])
        assert leak_check.check_flow(bad, "")[0].startswith("schema"), bad["steps"][3]


def test_a_verdict_is_discarded_when_what_it_judged_changed(deck, lib):
    deck_id, ids = _six_slide_deck(deck, lib)
    leak_check.run(deck_id, lib)
    for rid in [*ids, "flow"]:
        _judge(lib, deck_id, rid, False)
    assert all(r["published"] for r in leak_check.run(deck_id, lib).values())
    verdicts = lib / "judge" / deck_id / "verdicts"
    assert all(r["published"] for r in leak_check.run(deck_id, lib).values())  # unchanged: verdicts kept
    record = lib / "work" / deck_id / "build" / f"{ids[0]}.json"
    record.write_text(json.dumps(dict(json.loads(record.read_text()), purpose="Open on one bold promise first")))
    Image.new("L", (96, 54), 17).save(lib / "mockups" / deck_id / "slide-02.png")  # a new mockup picture
    rec = lib / "work" / deck_id / "flow-record.json"
    rec.write_text(json.dumps(dict(json.loads(rec.read_text()), arc="pillars")))
    report = leak_check.run(deck_id, lib)
    for rid in (ids[0], ids[1], "flow"):
        assert report[rid]["auto"] == "pass" and report[rid]["judge"] == "pending", rid
        assert not (verdicts / f"{rid}.json").exists()
    assert (lib / "judge" / deck_id / f"{ids[0]}.json").read_bytes() == record.read_bytes()  # the new copy
    assert (lib / "judge" / deck_id / "flow.json").read_bytes() == rec.read_bytes()
    assert all(report[rid]["published"] for rid in ids[2:])  # the unchanged ones keep theirs
    assert not (lib / "records" / f"{ids[0]}.json").exists() and not (lib / "flows" / f"{deck_id}.json").exists()


def test_a_verdict_without_its_judge_copy_is_discarded(deck, lib):
    deck_id, ids = _six_slide_deck(deck, lib)
    leak_check.run(deck_id, lib)
    for rid in [*ids, "flow"]:
        _judge(lib, deck_id, rid, False)
    judge = lib / "judge" / deck_id
    for p in (judge / f"{ids[0]}.json", judge / "flow.json"):  # what was judged is unknown: judge afresh
        p.unlink()
    report = leak_check.run(deck_id, lib)
    for rid in (ids[0], "flow"):
        assert report[rid]["judge"] == "pending" and not report[rid]["published"], rid
        assert not (judge / "verdicts" / f"{rid}.json").exists()
    assert report[ids[1]]["published"]


def test_a_verdict_is_discarded_when_its_item_fails_the_automated_check(deck, lib):
    deck_id, ids = _six_slide_deck(deck, lib)
    leak_check.run(deck_id, lib)
    for rid in [*ids, "flow"]:
        _judge(lib, deck_id, rid, False)
    leak_check.run(deck_id, lib)
    record = lib / "work" / deck_id / "build" / f"{ids[0]}.json"
    record.write_text(json.dumps(dict(json.loads(record.read_text()), purpose=f"Open the {CLIENT} story")))
    rec = lib / "work" / deck_id / "flow-record.json"
    rec.write_text(json.dumps(dict(json.loads(rec.read_text()), why_the_flow_works=f"Opens the {CLIENT} way, then lands")))
    report = leak_check.run(deck_id, lib)
    verdicts = lib / "judge" / deck_id / "verdicts"
    assert report[ids[0]]["auto"] == report["flow"]["auto"] == "fail"
    # the copies go, and the verdicts with them: whatever text replaces the leak is judged afresh
    assert not (verdicts / f"{ids[0]}.json").exists() and not (verdicts / "flow.json").exists()
    assert (verdicts / f"{ids[1]}.json").exists()


def test_slide_prose_is_checked_for_names_from_anywhere_in_the_deck(deck, lib):
    deck_id, ids = _six_slide_deck(deck, lib)  # only slide 5's text names Quillmoor
    record = lib / "work" / deck_id / "build" / f"{ids[2]}.json"
    record.write_text(json.dumps(dict(json.loads(record.read_text()), purpose="Open on the quillmoor promise first")))
    report = leak_check.run(deck_id, lib)
    assert report[ids[2]]["auto"] == "fail" and any("quillmoor" in p for p in report[ids[2]]["problems"])


def test_a_published_record_whose_build_is_gone_is_withdrawn(deck, lib):
    deck_id, ids = _six_slide_deck(deck, lib)
    for rid in [*ids, "flow"]:
        _judge(lib, deck_id, rid, False)
    leak_check.run(deck_id, lib)
    other = lib / "records" / "ffffffffffffffff-01.json"  # another deck's record is left alone
    other.write_text("{}")
    assert (lib / "records" / f"{ids[1]}.json").exists()
    (lib / "work" / deck_id / "build" / f"{ids[1]}.json").unlink()
    report = leak_check.run(deck_id, lib)
    assert ids[1] not in report
    assert not (lib / "records" / f"{ids[1]}.json").exists() and not (lib / "wireframes" / f"{ids[1]}.png").exists()
    assert (lib / "records" / f"{ids[0]}.json").exists() and other.exists()


@pytest.mark.parametrize("field, value, problem", [
    ("when_to_use", "Open on the quillmoor promise first", "name from slide text: 'quillmoor'"),
    ("when_to_use", "Open with 3 reasons members stay", "digit"),
    ("when_to_use", "Open on a teal band with the mascot", "brand identity: mascot, teal"),
    ("effect", "The quillmoor promise lands first", "name from slide text"),
    ("elements/0/note", "A headline in 2 lines", "digit"),
])
def test_style_notes_are_checked_like_any_free_text(deck, lib, field, value, problem):
    deck_id, ids = _six_slide_deck(deck, lib)  # only slide 5's text names Quillmoor
    record = lib / "work" / deck_id / "build" / f"{ids[2]}.json"
    dna = json.loads(record.read_text())
    if field.startswith("elements"):
        dna["elements"][0]["note"] = value
    else:
        dna[field] = value
    record.write_text(json.dumps(dna))
    report = leak_check.run(deck_id, lib)
    assert report[ids[2]]["auto"] == "fail" and any(p.startswith(f"{field}: ") and problem in p
                                                    for p in report[ids[2]]["problems"]), report[ids[2]]
    assert report[ids[1]]["auto"] == "pass"


def test_a_record_without_style_notes_fails_closed(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    record = lib / "work" / deck_id / "build" / f"{ids[1]}.json"
    record.write_text(json.dumps({k: v for k, v in json.loads(record.read_text()).items() if k != "when_to_use"}))
    report = leak_check.run(deck_id, lib)
    assert report[ids[1]]["auto"] == "fail" and report[ids[1]]["problems"][0].startswith("schema")


@pytest.mark.parametrize("with_style", [True, False])
def test_blank_or_duplicate_slides_need_no_style_notes_and_are_still_reported_excluded(deck, lib, with_style):
    def edit(n, labels):
        if n == 1:
            for k in ("when_to_use", "effect", "elements"):
                labels.pop(k)
    deck_id = extract.run(deck, lib, render=False)
    work = label_prep.run(deck_id, lib)
    for f in sorted(work.glob("slide-??.json")):
        labels = fixture_labels(json.loads(f.read_text()))
        edit(int(f.stem[-2:]), labels)
        (work / "labels" / f.name).write_text(json.dumps(labels))
    (lib / "layouts" / deck_id / "slide-01.v3.json").write_text(json.dumps({"version": 3, "blank": True, "components": []}))
    if not with_style:  # a publishable slide still needs the deck style
        with pytest.raises(SystemExit, match="style.json"):
            build.run(deck_id, lib)
        return
    fixture_style(work)
    ids = build.run(deck_id, lib)
    mockups(lib, deck_id, slides=(2,))
    report = leak_check.run(deck_id, lib)
    assert report[ids[0]] == {"auto": "excluded", "problems": ["blank"], "judge": "excluded", "published": False,
                              "excluded": "blank"}
    assert report[ids[1]]["auto"] == "pass"


def test_flow_record_without_a_valid_style_fails_closed(deck, lib):
    deck_id, ids = _six_slide_deck(deck, lib)
    good = json.loads((lib / "work" / deck_id / "flow-record.json").read_text())
    assert good["style"] == "bold-pitch" and leak_check.check_flow(good, "") == []
    for bad in (dict(good, style="neon-brutalist"), {k: v for k, v in good.items() if k != "style"}):
        assert leak_check.check_flow(bad, "")[0].startswith("schema"), bad
