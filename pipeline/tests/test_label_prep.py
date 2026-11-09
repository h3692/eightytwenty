import json
import re
from pathlib import Path

import pytest

from pipeline import build, extract, label_prep, layout
from pipeline.__main__ import main
from pipeline.tests.conftest import STYLE, fixture_labels, fixture_style

PLAYBOOK = Path(__file__).resolve().parents[2] / "playbook" / "archetypes.md"


@pytest.fixture
def work(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    label_prep.run(deck_id, lib)
    return lib / "work" / deck_id


def _slide(work, n):
    return json.loads((work / f"slide-{n:02d}.json").read_text())


def test_archetype_enum_matches_playbook_ids():
    ids = re.findall(r"^\| `([a-z-]+)` \|", PLAYBOOK.read_text(), re.M)
    assert len(ids) == 21
    assert ids[-5:] == ["valuation", "comps", "lbo-returns", "transaction-overview", "other"]
    assert label_prep.SCHEMA["properties"]["archetype"]["enum"] == ids


def test_industry_is_a_fixed_list_of_at_most_15():
    assert 2 <= len(label_prep.SCHEMA["properties"]["industry"]["enum"]) <= 15


LEAK_RULES = (  # verbatim: the labeling agent sees exactly these rules
    "Hard rules for every free-text field (purpose, why_it_works, pattern). A leak check rejects the record otherwise:",
    "  - Describe the design, never the content. No client, competition, team, school, year, person, company,\n"
    "    brand, product or place names, and no hint that identifies them.",
    '  - No digits at all (write "one big number", not "3x").',
    "  - Never copy three or more consecutive words from the slide's text.",
    "  - No other fields than the ones above.",
    '  - No brand identity. No specific colour names (red, blue, coral, teal, navy, gold ... or "-ish" forms): use\n'
    "    roles (primary, accent, brand-colour fill, dark, light, mid-grey, black, white, greyscale, tint, shade,\n"
    "    saturated, muted).",
    "  - No mascot, wordmark, lockup, logomark, monogram, emblem, crest, watermark, signature, sponsor, affiliation,\n"
    '    portrait, domain or URL, and no "brand art", "brand illustration", "brand motif" or "brand swoosh". Write\n'
    '    "headshot slots" for portraits; "logo" is fine as a placement ("logo top right").',
    "  - Never say what an illustration depicts (botanical, an animal, a character, a landmark, a skyline, a world\n"
    '    map): write "illustration", "photo", "icon", "image" or "map".',
    "  - No words from the slide and no fields other than the ones above: the mockup only ever shows fixed placeholder\n"
    '    copy ("Header here", "Text here", "XX%" ...).',
)


def _listed(text):
    """Region indices a worksheet lists, one JSON object per line."""
    return [json.loads(line)["i"] for line in text.splitlines() if line.startswith('{"i":')]


def test_writes_one_combined_worksheet_per_slide(work):
    prompts = sorted(work.glob("slide-*.prompt.txt"))
    assert [p.name for p in prompts] == ["slide-01.prompt.txt", "slide-02.prompt.txt"]
    text = prompts[1].read_text()
    lib, deck_id = work.parents[1], work.name
    for needed in (str(work.absolute() / "slide-02.png"), str(work.absolute() / "labels" / "slide-02.json"),
                   str(lib.absolute() / "layouts" / deck_id / "slide-02.v3.json"), "ONCE", "BOTH",
                   "labels.v1.json", "layout.v3.json", '"version": 3', "zoomed out", "12 x 8", "situational-analysis",
                   "why_it_works", "text_patterns", "claim + mechanism + number", "stacked_bar", *layout.KINDS,
                   *LEAK_RULES):
        assert needed in text, needed
    assert _listed(text) == [r["i"] for r in _slide(work, 2)["regions"]]
    assert '"path"' not in text  # outlines are heavy and useless to a labeler
    assert (work / "labels").is_dir() and (lib / "layouts" / deck_id).is_dir()


def _busy(slide, n=60):
    """The slide with n regions whose areas repeat every 25 indices (ties), alternating shape and text, apart (no cluster)."""
    text = next(r for r in slide["regions"] if r["type"] == "text")
    shape = next(r for r in slide["regions"] if r["type"] == "shape")
    return dict(slide, regions=[dict(text if i % 2 else shape, i=i, parent=None,
                                     box={"x": 0, "y": 0.016 * i, "w": 0.01 * (1 + i % 25), "h": 0.01}) for i in range(n)])


def _capped_labels(slide):
    labels = fixture_labels(slide)
    keep = {str(r["i"]) for r in label_prep.worksheet_regions(slide)}
    labels["regions"] = {k: v for k, v in labels["regions"].items() if k in keep}
    labels["text_patterns"][0]["region"] = 49  # a listed text region
    return labels


def test_worksheet_regions_are_the_40_largest_ties_by_index(work):
    slide = _busy(_slide(work, 2))
    picked = [r["i"] for r in label_prep.worksheet_regions(slide)]
    assert label_prep.MAX_REGIONS == 40 and len(picked) == 40 and picked == sorted(picked)
    assert set(picked) == set(sorted(range(60), key=lambda i: (-(1 + i % 25), i))[:40])
    assert 6 in picked and 31 not in picked and 56 not in picked  # the last tie goes to the lowest index
    small = _slide(work, 2)
    assert label_prep.worksheet_regions(small) == small["regions"]


@pytest.mark.parametrize("layouts_only", [False, True])
def test_worksheets_list_only_the_capped_regions(work, layouts_only):
    slide = _busy(_slide(work, 2))
    (work / "slide-02.json").write_text(json.dumps(slide))
    out = label_prep.run(work.name, work.parents[1], layouts_only=layouts_only)
    text = (out / "slide-02.prompt.txt").read_text()
    assert _listed(text) == [r["i"] for r in label_prep.worksheet_regions(slide)]
    assert "40 largest" in text and "of 60" in text


def test_labels_cover_exactly_the_listed_regions_or_every_region(work):
    slide = _busy(_slide(work, 2))
    labels = _capped_labels(slide)
    label_prep.validate(labels, slide)
    legacy = fixture_labels(slide)  # labelled before the cap: every region
    legacy["text_patterns"][0]["region"] = 49
    label_prep.validate(legacy, slide)
    for broken in ({**labels["regions"], "31": "body"}, {k: v for k, v in labels["regions"].items() if k != "6"}):
        with pytest.raises(ValueError, match="region"):
            label_prep.validate({**labels, "regions": broken}, slide)
    labels["text_patterns"][0]["region"] = 31  # a text region that is not listed
    with pytest.raises(ValueError, match="non-text region"):
        label_prep.validate(labels, slide)


def test_unlisted_regions_build_as_other(work):
    slide = _busy(_slide(work, 2))
    dna = build.merge(slide, _capped_labels(slide), STYLE)
    build.check_schema(dna)
    listed = {r["i"] for r in label_prep.worksheet_regions(slide)}
    assert {r["role"] for r in dna["regions"] if r["i"] not in listed} == {"other"}
    assert "other" not in {r["role"] for r in dna["regions"] if r["i"] in listed}


def test_valid_labels_pass(work):
    label_prep.validate(fixture_labels(_slide(work, 2)), _slide(work, 2))


def test_style_notes_are_optional_in_labels_written_before_them(work):
    labels = fixture_labels(_slide(work, 2))
    for k in ("when_to_use", "effect", "elements"):
        labels.pop(k)
    label_prep.validate(labels, _slide(work, 2))


@pytest.mark.parametrize("mutate, message", [
    (lambda l: l.update(archetype="hero-slide"), "archetype"),
    (lambda l: l.update(industry="aerospace-defense-and-space"), "industry"),
    (lambda l: l.update(client="Somebody"), "client"),
    (lambda l: l["regions"].pop("0"), "region"),
    (lambda l: l["regions"].update({"99": "body"}), "region"),
    (lambda l: l["text_patterns"].append({"region": 99, "pattern": "short claim", "words": 3}), "non-text region"),
    (lambda l: l.update(when_to_use="x" * 161), "when_to_use"),
    (lambda l: l.update(effect=""), "effect"),
    (lambda l: l.update(elements=[]), "elements"),
    (lambda l: l.update(elements=l["elements"] * 4), "elements"),
    (lambda l: l["elements"][0].update(component=-1), "elements"),
    (lambda l: l["elements"][0].update(note="x" * 121), "elements"),
    (lambda l: l["elements"][0].update(colour="navy"), "elements"),
])
def test_invalid_labels_fail(work, mutate, message):
    labels = fixture_labels(_slide(work, 2))
    mutate(labels)
    with pytest.raises(ValueError, match=message):
        label_prep.validate(labels, _slide(work, 2))


# --- style notes worksheet and check ------------------------------------------------------------------------------

BLANK = {"version": 3, "blank": True, "components": []}
TWO = {"version": 3, "components": [{"kind": "card_row", "box": [0, 0, 1, 0.5], "n": 3},
                                    {"kind": "table", "box": [0, 0.5, 1, 0.5], "rows": 4, "cols": 3}]}


@pytest.fixture
def styled(work):
    """The fixture deck labelled with style notes and drawn: slide 1 blank (never published), slide 2 two components."""
    layouts = work.parents[1] / "layouts" / work.name
    for n, lay in ((1, BLANK), (2, TWO)):
        (work / "labels" / f"slide-{n:02d}.json").write_text(json.dumps(fixture_labels(_slide(work, n))))
        (layouts / f"slide-{n:02d}.v3.json").write_text(json.dumps(lay))
    fixture_style(work)
    return work


def _style_check(work, capsys):
    try:
        main(["label-prep", work.name, "--style-check", "--library", str(work.parents[1])])
        code = 0
    except SystemExit as e:
        code = e.code
    return code, capsys.readouterr().out


def _set_elements(work, n, elements):
    lf = work / "labels" / f"slide-{n:02d}.json"
    lf.write_text(json.dumps(dict(json.loads(lf.read_text()), elements=elements)))


def test_style_worksheet_lists_publishable_slides_and_asks_for_the_deck_style(styled, capsys):
    lib = styled.parents[1]
    main(["label-prep", styled.name, "--style", "--library", str(lib)])
    out = styled.absolute() / "style.prompt.txt"
    assert str(out) in capsys.readouterr().out
    text = out.read_text()
    for needed in (str(styled.absolute() / "slide-02.png"), str(styled.absolute() / "labels" / "slide-02.json"),
                   str(styled.absolute() / "style.json"), "situational-analysis", fixture_labels(_slide(styled, 2))["purpose"],
                   "0 card_row", "1 table", "when_to_use", "effect", "elements", "160", "120", "changing nothing else",
                   "--style-check", "action titles, labelled rows, dense logic, tight grids",
                   "big type, one idea per slide, high contrast", "imagery-led, emotional, customer moments",
                   "charts and numbers carry each slide", "generous white space, restrained colour, typographic hierarchy",
                   "dense tables, football fields, returns charts, action titles", "one of the six below",
                   '"buy-side audience"', '"lender"', '"committee"',
                   *build.STYLES, *LEAK_RULES[1:4], *LEAK_RULES[5:8]):
        assert needed in text, needed
    assert "slide-01" not in text  # blank: never published, so no notes
    assert "contact-sheet" not in text
    (styled / "flow-contact-sheet.png").write_bytes(b"")
    label_prep.run(styled.name, lib, style=True)
    assert str(styled.absolute() / "flow-contact-sheet.png") in out.read_text()


def test_style_worksheet_refuses_a_publishable_slide_without_a_layout(styled):
    (styled.parents[1] / "layouts" / styled.name / "slide-02.v3.json").unlink()
    with pytest.raises(SystemExit, match="slide-02"):
        label_prep.run(styled.name, styled.parents[1], style=True)


def test_elements_must_name_distinct_components_of_the_layout(work):
    labels, slide = fixture_labels(_slide(work, 2)), _slide(work, 2)
    labels["elements"] = [{"component": 1, "note": "The table"}, {"component": 0, "note": "The cards"}]
    label_prep.validate(labels, slide, TWO["components"])
    for elements, message in (([{"component": 2, "note": "Past the last"}], "outside"),
                              ([{"component": 1, "note": "One"}, {"component": 1, "note": "Again"}], "once")):
        with pytest.raises(ValueError, match=message):
            label_prep.validate(dict(labels, elements=elements), slide, TWO["components"])


def test_style_check_passes_a_clean_deck(styled, capsys):
    code, out = _style_check(styled, capsys)
    assert code == 0 and "clean" in out


@pytest.mark.parametrize("elements, message", [
    ([{"component": 2, "note": "Past the last component"}], "outside"),
    ([{"component": 0, "note": "Cards"}, {"component": 0, "note": "Cards again"}], "once"),
])
def test_style_check_reports_bad_elements_one_line_each(styled, capsys, elements, message):
    _set_elements(styled, 2, elements)
    code, out = _style_check(styled, capsys)
    assert code == 1 and len(out.splitlines()) == 1 and "slide-02" in out and message in out
    with pytest.raises(SystemExit, match=message):  # build refuses it too
        build.run(styled.name, styled.parents[1])


def test_style_check_skips_excluded_slides(styled, capsys):
    _set_elements(styled, 1, [{"component": 5, "note": "A blank slide has no components"}])
    code, out = _style_check(styled, capsys)
    assert code == 0 and "clean" in out


def test_style_check_reports_a_missing_deck_style(styled, capsys):
    (styled / "style.json").unlink()
    code, out = _style_check(styled, capsys)
    assert code == 1 and "style.json" in out and "slide-" not in out
