import json

import pytest
from PIL import Image

from pipeline import build, extract, label_prep, leak_check, mockup
from pipeline.tests.conftest import CLIENT, EXCLUDED, fixture_labels
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
    ids = build.run(deck_id, lib)
    mockups(lib, deck_id)
    return deck_id, ids


def _judge(lib, deck_id, rid, identified):
    v = lib / "judge" / deck_id / "verdicts"
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
    "Screenshots are annotated with a red circle and leader line to the key figure.",
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


@pytest.mark.parametrize("text, source", [
    ("a four-column strengths, weaknesses, opportunities and threats band", "STRENGTHS\nWEAKNESSES\nOPPORTUNITIES\nTHREATS"),
    ("a political, economic, social, technological, legal, environmental grid", "Political Economic Social Technological Legal Environmental"),
    ("nested total addressable market rings", "Total addressable market"),
])
def test_standard_framework_phrases_are_not_copied_text(text, source):
    assert leak_check.problems_in(text, source, set()) == []


@pytest.mark.parametrize("text, source, problem", [
    ("Echoes the Quillmoor Analytics house style with a dark band", "", "name"),
    ("Styled after the London Underground map with coloured lines", "", "name"),
    ("A layout that Priya Raman sketched on a whiteboard", "", "name"),
    ("A quillmoor style promise band", "Quillmoor Analytics grew loyalty in Ontario", "name"),
    ("A loyalty band in the Ontario style", "Quillmoor Analytics grew loyalty in Ontario", "name"),
    ("A LOYALTY band", "Quillmoor Analytics grew LOYALTY in Ontario", "name"),
    ("A band in 2 tones", "", "digit"),
    ("bands for secondary research, primary research and objective", "Secondary research and objective", "shared words"),
    ("headline urging a focus on untapped segments", "Focus on untapped segments", "shared words"),
])
def test_real_names_numbers_and_copies_still_fail(text, source, problem):
    found = leak_check.problems_in(text, source, leak_check.source_names(source))
    assert any(problem in p for p in found), found


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
