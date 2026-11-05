import copy
import io
import json
import re

import jsonschema
import pytest
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData

from pipeline import build, extract, label_prep
from pipeline.tests.conftest import STYLE, fixture_labels, fixture_style


def _label(lib, deck_id):
    work = lib / "work" / deck_id
    for f in sorted(work.glob("slide-??.json")):
        (work / "labels" / f.name).write_text(json.dumps(fixture_labels(json.loads(f.read_text()))))
    fixture_style(work)
    return work


@pytest.fixture
def built(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    label_prep.run(deck_id, lib)
    work = _label(lib, deck_id)
    ids = build.run(deck_id, lib)
    return work / "build", ids


def _dna(out, rid):
    return json.loads((out / f"{rid}.json").read_text())


def test_records_validate_against_versioned_schema(built):
    out, ids = built
    assert len(ids) == 2 and all(re.fullmatch(r"[0-9a-f]{16}-0[12]", i) for i in ids)
    for rid in ids:
        build.check_schema(_dna(out, rid))


@pytest.mark.parametrize("field", ["client", "competition", "year", "team", "source"])
def test_schema_has_no_room_for_identifying_fields(built, field):
    out, ids = built
    dna = _dna(out, ids[0])
    with pytest.raises(jsonschema.ValidationError):
        build.check_schema(dict(dna, **{field: "x"}))
    dna["regions"][0][field] = "x"
    with pytest.raises(jsonschema.ValidationError):
        build.check_schema(dna)


def test_dna_merges_geometry_and_labels(built):
    out, ids = built
    dna = _dna(out, ids[0])
    assert dna["archetype"] == "title" and dna["industry"] == "travel-hospitality"
    assert [r["role"] for r in dna["regions"]][:3] == ["card", "title", "big-number"]
    assert dna["regions"][1]["text"]["pattern"] == "outcome promise as a short noun phrase"
    assert dna["regions"][1]["text"]["pattern_words"] == 6
    assert dna["regions"][0]["box"] == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.2667}
    labels = fixture_labels({"slide": 1, "regions": [{"i": 0, "type": "text"}, {"i": 1, "type": "text"}]})
    assert dna["style"] == STYLE and all(dna[k] == labels[k] for k in ("when_to_use", "effect", "elements"))


def test_style_notes_and_the_deck_style_are_required_so_merge_keeps_them():
    assert {"style", "when_to_use", "effect", "elements"} <= set(build.SCHEMA["required"])
    assert build.STYLES == ["consulting-structured", "bold-pitch", "visual-storytelling", "data-led", "minimal-editorial"]


def test_description_uses_fixed_template_without_digits(built):
    out, ids = built
    dna = _dna(out, ids[0])
    d = dna["description"]
    assert d.startswith("Title slide. Single claim argument, big number device, kpi numbers data, travel hospitality.")
    assert dna["purpose"] in d and dna["why_it_works"] in d and "outcome promise" in d
    assert d.endswith(f"Style: bold pitch. When to use: {dna['when_to_use']}. Effect: {dna['effect']}.")
    assert not re.search(r"\d", d) and build.DESCRIPTION_VERSION == "desc-v3"


def test_build_refuses_missing_or_invalid_labels(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    label_prep.run(deck_id, lib)
    with pytest.raises(SystemExit, match="slide-01"):
        build.run(deck_id, lib)
    work = _label(lib, deck_id)
    bad = json.loads((work / "labels" / "slide-02.json").read_text()) | {"client": "x"}
    (work / "labels" / "slide-02.json").write_text(json.dumps(bad))
    with pytest.raises(SystemExit, match="slide-02"):
        build.run(deck_id, lib)
    assert not list((work / "build").glob("*")) if (work / "build").exists() else True


@pytest.mark.parametrize("edit, problem", [
    (lambda work: (work / "labels" / "slide-02.json").write_text(json.dumps(
        {k: v for k, v in json.loads((work / "labels" / "slide-02.json").read_text()).items() if k != "effect"})),
     r"labels/slide-02.json: no style notes: effect"),
    (lambda work: (work / "style.json").unlink(), r"style.json: missing or invalid"),
    (lambda work: (work / "style.json").write_text('{"style": "neon-brutalist"}'), r"style.json: missing or invalid"),
])
def test_build_refuses_a_publishable_slide_without_style_notes_or_a_deck_without_a_style(deck, lib, edit, problem):
    deck_id = extract.run(deck, lib, render=False)
    label_prep.run(deck_id, lib)
    work = _label(lib, deck_id)
    edit(work)
    with pytest.raises(SystemExit, match=problem):
        build.run(deck_id, lib)
    assert not (work / "build").exists() or not list((work / "build").glob("*"))


def test_wireframe_is_small_greyscale_skeleton(built):
    out, ids = built
    for rid in ids:
        png = (out / f"{rid}.png").read_bytes()
        assert len(png) <= 30 * 1024
        img = Image.open(io.BytesIO(png))
        assert img.mode == "L" and img.size in ((960, 540), (640, 360))


def test_wireframe_ignores_real_chart_values(deck, lib, tmp_path):
    prs = Presentation(str(deck))
    chart = next(s for s in prs.slides[1].shapes if getattr(s, "has_chart", False)).chart
    data = CategoryChartData()
    data.categories = ["A", "B", "C"]
    data.add_series("S", (1, 99, 5))
    chart.replace_data(data)
    other = tmp_path / "other.pptx"
    prs.save(other)
    charts = []
    for src in (deck, other):
        deck_id = extract.run(src, lib, render=False)
        s2 = json.loads((lib / "work" / deck_id / "slide-02.json").read_text())
        charts.append(next(r for r in s2["regions"] if r["type"] == "chart"))
    assert charts[0] == charts[1]


def test_wireframe_is_a_pure_function_of_the_dna(built):
    out, ids = built
    dna = _dna(out, ids[1])
    assert build.wireframe(dna) == build.wireframe(copy.deepcopy(dna)) == (out / f"{ids[1]}.png").read_bytes()
    pie = copy.deepcopy(dna)
    next(r for r in pie["regions"] if r["type"] == "chart")["chart"]["kind"] = "PIE"
    assert build.wireframe(pie) != build.wireframe(dna)


def test_dense_slide_stays_under_size_cap(built):
    out, ids = built
    dna = _dna(out, ids[1])
    base = [r for r in dna["regions"] if r["parent"] is None]
    regions = []
    for k in range(6):
        for r in base:
            r = copy.deepcopy(r)
            r["i"], r["box"] = len(regions), {"x": (k % 3) / 3, "y": (k // 3) / 2, "w": 0.32, "h": 0.48}
            regions.append(r)
    assert len(build.wireframe(dict(dna, regions=regions))) <= 30 * 1024


def test_tiny_text_box_draws_without_error(built):
    out, ids = built
    dna = _dna(out, ids[1])
    r = next(r for r in dna["regions"] if r["text"] and not r["text"]["number"] and r["role"] != "big-number"
             and not r["chart"] and not r["table"])
    r["box"] = {"x": 0.5, "y": 0.5, "w": 0.005, "h": 0.05}
    assert Image.open(io.BytesIO(build.wireframe(dna))).mode == "L"


def _r(i, role, type_="shape", box=(0.1, 0.1, 0.3, 0.3), **kw):
    x, y, w, h = box
    return {"i": i, "parent": None, "type": type_, "role": role, "box": {"x": x, "y": y, "w": w, "h": h},
            "fill": None, "line": None, "dashed": False, "text": None, "chart": None, "table": None} | kw


def _txt(bullets=0, number=None):
    return {"words": 5, "paragraphs": 2, "lines": 2, "bullets": bullets, "align": "left", "size": "body",
            "weight": "regular", "color": None, "number": number, "pattern": None, "pattern_words": None}


@pytest.mark.parametrize("region,label", [
    (_r(0, "title", "text", text=_txt()), "[title]"),
    (_r(0, "subtitle", "text", text=_txt()), "[subtitle]"),
    (_r(0, "tagline", "text", text=_txt()), "[subtitle]"),
    (_r(0, "body", "text", text=_txt()), "[text]"),
    (_r(0, "body", "text", text=_txt(bullets=2)), "[bullets]"),
    (_r(0, "bullet-list", "text", text=_txt(bullets=2)), "[bullets]"),
    (_r(0, "callout", "text", text=_txt()), "[quote]"),
    (_r(0, "big-number", "text", text=_txt(number="percent")), "[number]"),
    (_r(0, "number-label", "text", text=_txt()), "[label]"),
    (_r(0, "section-label", "text", text=_txt()), "[label]"),
    (_r(0, "footer", "text", text=_txt()), "[label]"),
    (_r(0, "image", "picture"), "[image]"),
    (_r(0, "logo", "picture"), "[logo]"),
    (_r(0, "icon", "shape"), "[icon]"),
    (_r(0, "table", "table", table={"rows": 2, "cols": 3}), "[table]"),
    (_r(0, "chart", "chart", chart={"kind": "COLUMN_CLUSTERED", "series": 1, "categories": 3}), "[bar chart]"),
    (_r(0, "chart", "chart", chart={"kind": "BAR_STACKED", "series": 1, "categories": 3}), "[bar chart]"),
    (_r(0, "chart", "chart", chart={"kind": "LINE_MARKERS", "series": 1, "categories": 3}), "[line chart]"),
    (_r(0, "chart", "chart", chart={"kind": "PIE", "series": 1, "categories": 3}), "[pie chart]"),
    (_r(0, "chart", "chart", chart={"kind": "BAR_OF_PIE", "series": 1, "categories": 3}), "[pie chart]"),
    (_r(0, "chart", "chart", chart={"kind": "XY_SCATTER_LINES", "series": 1, "categories": 3}), "[scatter chart]"),
    (_r(0, "chart", "chart", chart={"kind": "FUNNEL", "series": 1, "categories": 3}), "[chart]"),
    (_r(0, "other", "text", text=_txt()), "[text]"),
    (_r(0, "card", "shape"), "[shape]"),
    (_r(0, "other", "shape"), "[shape]"),
])
def test_label_comes_from_role_and_type(region, label):
    assert build._label(region) == label


def test_every_role_maps_to_a_bracket_label():
    for role in label_prep.SCHEMA["$defs"]["role"]["enum"]:
        assert re.fullmatch(r"\[[a-z ]+\]", build._label(_r(0, role))), role


def _plan(*regions, **context):
    return build._plan({"id": "0" * 16 + "-01", "regions": list(regions)} | context)


def test_shapes_keep_their_geometry_in_the_plan():
    plan = _plan(_r(0, "card", geom="ellipse", fill="accent", box=(0.1, 0.1, 0.3, 0.3)),
                 _r(1, "card", geom="roundRect", fill="accent", box=(0.5, 0.1, 0.3, 0.3)),
                 _r(2, "card", geom="rect", fill="accent", box=(0.1, 0.5, 0.3, 0.3)),
                 _r(3, "card", fill="accent", box=(0.5, 0.5, 0.3, 0.3)))  # records built before geometry was extracted
    assert [(p["i"], p["geom"], p["frame"]) for p in plan] == [
        (0, "ellipse", True), (1, "roundRect", True), (2, "rect", True), (3, None, True)]


def test_decoration_and_tiny_regions_are_dropped_unless_number_icon_or_logo():
    tiny = lambda k: (0.1 * k, 0.5, 0.05, 0.05)  # 0.25% of the slide each
    plan = _plan(_r(0, "decoration", box=(0.1, 0.1, 0.1, 0.1), fill="accent"),
                 _r(1, "body", "text", box=tiny(1), text=_txt()),
                 _r(2, "big-number", "text", box=tiny(2), text=_txt(number="plain")),
                 _r(3, "icon", "picture", box=tiny(3)),
                 _r(4, "logo", "picture", box=tiny(4)),
                 _r(5, "group", "group", box=(0.0, 0.0, 0.5, 0.5)),
                 _r(6, "decoration", "line", box=(0.1, 0.9, 0.8, 0.0)))
    assert sorted(p["i"] for p in plan) == [2, 3, 4]


def test_big_background_panels_become_unlabelled_light_fills():
    plan = _plan(_r(0, "decoration", box=(0.0, 0.0, 1.0, 1.0), fill="white"),  # the slide itself: nothing to show
                 _r(1, "decoration", box=(0.0, 0.0, 0.5, 1.0), fill="primary"),
                 _r(2, "background-band", box=(0.0, 0.0, 1.0, 0.2), fill="neutral-light"),
                 _r(3, "decoration", box=(0.5, 0.0, 0.5, 1.0)))  # an outline frame: no fill, no panel
    assert [(p["i"], p["kind"], p["label"]) for p in plan] == [(1, "band", None), (2, "band", None)]


def test_lines_connectors_and_dividers_stay_thin_lines():
    plan = _plan(_r(0, "divider", "line", box=(0.1, 0.5, 0.8, 0.0)),
                 _r(1, "connector", "line", box=(0.2, 0.2, 0.1, 0.3)),
                 _r(2, "divider", "shape", box=(0.1, 0.8, 0.8, 0.004)))
    assert [(p["kind"], p["pts"]) for p in plan] == [
        ("line", [(0.1, 0.5), (0.9, 0.5)]), ("line", [(0.2, 0.2), (0.30000000000000004, 0.5)]), ("line", [(0.1, 0.802), (0.9, 0.802)])]


def test_near_duplicate_boxes_merge_into_the_larger():
    plan = _plan(_r(0, "card", box=(0.1, 0.1, 0.5, 0.2)),
                 _r(1, "title", "text", box=(0.11, 0.1, 0.48, 0.19), text=_txt()),
                 _r(2, "body", "text", box=(0.1, 0.5, 0.3, 0.3), text=_txt()),
                 _r(3, "body", "text", box=(0.1, 0.5, 0.29, 0.29), text=_txt()))
    assert [(p["i"], tuple(round(v, 3) for v in p["box"]), p["label"]) for p in plan] == [
        (0, (0.1, 0.1, 0.5, 0.2), "[title]"), (2, (0.1, 0.5, 0.3, 0.3), "[text]")]


def test_unlabelled_container_holding_other_boxes_is_drawn_without_label():
    plan = _plan(_r(0, "card", box=(0.1, 0.1, 0.6, 0.6), fill="neutral-light"),
                 _r(1, "body", "text", box=(0.2, 0.2, 0.2, 0.1), text=_txt()))
    assert [(p["i"], p["label"]) for p in plan] == [(0, None), (1, "[text]")]


class _Rec:
    """Records every draw call while still drawing."""
    def __init__(self, d, calls):
        self.d, self.calls = d, calls

    def __getattr__(self, name):
        f = getattr(self.d, name)
        return lambda *a, **k: (self.calls.append((name, a, k)), f(*a, **k))[1]


def test_wireframe_draws_only_outlines_lines_and_bracket_labels(built, monkeypatch):
    out, ids = built
    dna = _dna(out, ids[1])  # header, bullets, picture, column chart, table, group of 2 cards, line, OLE box
    calls, real = [], build.ImageDraw.Draw
    monkeypatch.setattr(build.ImageDraw, "Draw", lambda img: _Rec(real(img), calls))
    img = Image.open(io.BytesIO(build.wireframe(dna)))
    W, H = img.size
    drawn = {c[0] for c in calls}
    assert drawn <= {"rectangle", "line", "text", "textlength"}, drawn
    texts = [c for c in calls if c[0] == "text"]
    assert sorted(c[1][1] for c in texts) == ["[bar chart]", "[bullets]", "[image]", "[shape]", "[shape]", "[table]", "[text]"]  # the empty OLE box is dropped
    boxes = [p for p in build._plan(dna) if p["kind"] != "line"]
    for c in texts:  # every label sits inside its own box
        l, t, r_, b = real(img).textbbox(c[1][0], c[1][1], font=c[2]["font"], anchor=c[2]["anchor"])
        assert any(p["box"][0] * W <= l and r_ <= (p["box"][0] + p["box"][2]) * W and p["box"][1] * H <= t
                   and b <= (p["box"][1] + p["box"][3]) * H for p in boxes), c[1][1]
    for name, a, k in calls:  # no filled shapes: no text bars, no fake chart bars
        if name in ("rectangle", "rounded_rectangle", "ellipse"):
            assert k.get("fill") is None, (name, a, k)
    chart = next(r for r in dna["regions"] if r["chart"])["box"]
    strip = [img.getpixel((int((chart["x"] + chart["w"] * f) * W), int((chart["y"] + chart["h"] * 0.85) * H)))
             for f in (0.2, 0.35, 0.5, 0.65, 0.8)]
    assert strip == [255] * 5  # where bars would stand, only white


def test_labels_are_omitted_when_the_box_is_too_small(built, monkeypatch):
    out, ids = built
    dna = dict(_dna(out, ids[1]), regions=[_r(0, "big-number", "text", box=(0.5, 0.5, 0.01, 0.01), text=_txt())])
    calls, real = [], build.ImageDraw.Draw
    monkeypatch.setattr(build.ImageDraw, "Draw", lambda img: _Rec(real(img), calls))
    build.wireframe(dna)
    assert [c[0] for c in calls if c[0] in ("text", "line", "rectangle")] == []  # a number has no frame to fall back on


def test_wireframe_background_is_white(built):
    out, ids = built
    img = Image.open(out / f"{ids[1]}.png")
    assert img.getpixel((img.width - 2, img.height - 2)) == 255


def test_stacked_lines_of_the_same_kind_merge_into_one_block():
    line = lambda i, x, y, w, role="body": _r(i, role, "text", box=(x, y, w, 0.033), text=_txt())
    plan = _plan(line(0, 0.1, 0.3, 0.6), dict(line(1, 0.1, 0.334, 0.5), text=_txt(bullets=1)), line(2, 0.12, 0.367, 0.55),  # one paragraph, a box per line
                 line(3, 0.1, 0.6, 0.6),  # a separate paragraph further down
                 line(4, 0.75, 0.3, 0.2),  # a side column on the same rows
                 line(5, 0.1, 0.4, 0.6, role="title"))  # touching, but a different kind
    assert [(p["i"], tuple(round(v, 3) for v in p["box"]), p["label"]) for p in plan] == [
        (0, (0.1, 0.3, 0.6, 0.1), "[bullets]"), (3, (0.1, 0.6, 0.6, 0.033), "[text]"),
        (4, (0.75, 0.3, 0.2, 0.033), "[text]"), (5, (0.1, 0.4, 0.6, 0.033), "[title]")]


def test_colliding_labels_keep_the_innermost(built, monkeypatch):
    out, ids = built
    dna = dict(_dna(out, ids[1]), regions=[_r(0, "image", "picture", box=(0.5, 0.1, 0.4, 0.8)),
                                           _r(1, "body", "text", box=(0.6, 0.45, 0.2, 0.1), text=_txt())])
    calls, real = [], build.ImageDraw.Draw
    monkeypatch.setattr(build.ImageDraw, "Draw", lambda img: _Rec(real(img), calls))
    build.wireframe(dna)
    assert [c[1][1] for c in calls if c[0] == "text"] == ["[text]"]


def test_tall_blocks_do_not_swallow_the_next_block():
    line = lambda i, y: _r(i, "body", "text", box=(0.1, y, 0.6, 0.033), text=_txt())
    plan = _plan(*[line(k, 0.1 + 0.034 * k) for k in range(6)],  # ends at 0.303
                 *[line(10 + k, 0.343 + 0.034 * k) for k in range(6)])  # one blank line further down
    assert [(p["i"], round(p["box"][3], 3)) for p in plan] == [(0, 0.203), (10, 0.203)]


def test_boxes_are_clipped_to_the_slide():
    plan = _plan(_r(0, "image", "picture", box=(0.716, -0.1, 0.467, 0.641)))
    assert [tuple(round(v, 3) for v in p["box"]) for p in plan] == [(0.716, 0.0, 0.284, 0.541)]


def test_container_label_never_lands_on_a_labelled_box_inside_it(built, monkeypatch):
    out, ids = built
    dna = dict(_dna(out, ids[1]), regions=[_r(0, "image", "picture", box=(0.716, 0.211, 0.467, 0.641)),
                                           _r(1, "body", "text", box=(0.826, 0.514, 0.157, 0.037), text=_txt())])
    calls, real = [], build.ImageDraw.Draw
    monkeypatch.setattr(build.ImageDraw, "Draw", lambda img: _Rec(real(img), calls))
    build.wireframe(dna)
    assert [c[1][1] for c in calls if c[0] == "text"] == ["[text]"]


BOX = (0, 0, 200, 100)
RECT = [[(0, 0), (200, 0), (200, 100), (0, 100), (0, 0)]]


def test_preset_outlines_are_true_polygons():
    assert build._outline("chevron", None, BOX) == [[(0, 0), (150, 0), (200, 50), (150, 100), (0, 100), (50, 50), (0, 0)]]
    assert build._outline("rightArrow", None, BOX) == [
        [(0, 25), (150, 25), (150, 0), (200, 50), (150, 100), (150, 75), (0, 75), (0, 25)]]
    assert build._outline("leftArrow", None, BOX) == [
        [(200, 25), (50, 25), (50, 0), (0, 50), (50, 100), (50, 75), (200, 75), (200, 25)]]
    assert build._outline("diamond", None, BOX) == [[(100, 0), (200, 50), (100, 100), (0, 50), (100, 0)]]
    assert build._outline("triangle", None, BOX) == [[(100, 0), (200, 100), (0, 100), (100, 0)]]
    (ring,) = build._outline("ellipse", None, BOX)
    assert len(ring) >= 32 and ring[0] == ring[-1]
    assert all(abs(((x - 100) / 100) ** 2 + ((y - 50) / 50) ** 2 - 1) < 1e-9 for x, y in ring)
    assert len(build._outline("donut", None, BOX)) == 2  # outer and inner ring
    callout = build._outline("wedgeRectCallout", None, BOX)
    assert callout[0] == RECT[0] and max(y for x, y in callout[1]) > 100  # a box plus a pointer below it
    assert len(build._outline("wedgeRoundRectCallout", None, BOX)) == 2  # rounded body, still with its pointer
    assert build._outline("star5", None, BOX) == build._outline(None, None, BOX) == RECT  # unknown preset: its box
    assert build._outline("rect", None, (10, 20, 30, 40)) == [[(10, 20), (30, 20), (30, 40), (10, 40), (10, 20)]]


def test_freeform_outlines_follow_their_path_inside_the_box():
    tri = [[[0.5, 0.0], [1.0, 1.0], [0.0, 1.0], [0.5, 0.0]]]
    assert build._outline(None, tri, BOX) == [[(100, 0), (200, 100), (0, 100), (100, 0)]]
    assert build._outline("rect", tri, BOX) == build._outline(None, tri, BOX)  # an explicit path wins


SQUIGGLE = [[[round(0.5 + 0.5 * ((-1) ** k) * (k % 5) / 4, 3), round(k / 19, 3)] for k in range(20)]]


def test_logos_and_icons_are_never_traced(built):
    out, ids = built
    dna = _dna(out, ids[1])
    traced = [_r(0, "logo", "picture", geom="ellipse", path=SQUIGGLE, line="primary", box=(0.1, 0.1, 0.3, 0.3)),
              _r(1, "icon", "shape", geom="chevron", path=SQUIGGLE, fill="accent", box=(0.5, 0.1, 0.3, 0.3))]
    bare = [dict(r, geom=None, path=None, line=None, fill=None) for r in traced]
    assert build.wireframe(dict(dna, regions=traced)) == build.wireframe(dict(dna, regions=bare))
    assert [(p["frame"], p["label"]) for p in build._plan(dict(dna, regions=traced))] == [(False, "[logo]"), (False, "[icon]")]


def test_merge_strips_outlines_from_logos_and_icons(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    slide = json.loads((lib / "work" / deck_id / "slide-02.json").read_text())
    labels = fixture_labels(slide)
    pic = next(r for r in slide["regions"] if r["type"] == "picture")
    pic.update(geom="ellipse", path=SQUIGGLE)
    labels["regions"][str(pic["i"])] = "logo"
    dna = build.merge(slide, labels, STYLE)
    build.check_schema(dna)
    assert dna["regions"][pic["i"]]["geom"] is None and "path" not in dna["regions"][pic["i"]]


def test_small_complex_freeforms_are_never_traced():
    tiny = lambda i, x: _r(i, "card", path=SQUIGGLE, fill="accent", box=(x, 0.1, 0.1, 0.1))  # 1% each, 20 points
    plan = _plan(tiny(0, 0.1), tiny(1, 0.3), tiny(2, 0.5))  # a row of three: kept, but only as its box
    assert plan and all(p["path"] is None for p in plan)


def test_schema_forbids_outlines(built):
    out, ids = built
    dna = _dna(out, ids[1])
    dna["regions"][0].update(arrow="end")
    build.check_schema(dna)
    for path in (None, [[[0.0, 0.5], [1.0, 0.25]]]):
        with pytest.raises(jsonschema.ValidationError):
            build.check_schema(copy.deepcopy(dna) | {"regions": [dict(dna["regions"][0], path=path)]})


def _publish(*regions):
    """merge() over a synthetic slide: the published regions and the record."""
    slide = {"deck_id": "0" * 16, "slide": 1, "background": "white",
             "regions": [{k: v for k, v in r.items() if k != "role"} | {"geom": r.get("geom"), "path": r.get("path"),
                                                                        "arrow": r.get("arrow")} for r in regions]}
    labels = fixture_labels({"slide": 2, "regions": [{"i": 0, "type": "text"}]}) | {"regions": {str(r["i"]): r["role"] for r in regions},
                                                           "text_patterns": []}
    dna = build.merge(slide, labels, STYLE)
    build.check_schema(dna)
    return dna["regions"], dna


def _union(regions):
    x0, y0 = min(r["box"]["x"] for r in regions), min(r["box"]["y"] for r in regions)
    return (x0, y0, max(r["box"]["x"] + r["box"]["w"] for r in regions) - x0,
            max(r["box"]["y"] + r["box"]["h"] for r in regions) - y0)


def _box(r):
    return tuple(r["box"][k] for k in "xywh")


TITLE = _r(0, "title", "text", box=(0.3, 0.4, 0.6, 0.1), text=_txt())


def test_a_wordmark_of_letter_shapes_publishes_as_one_logo_box():
    glyphs = [_r(1 + k, "logo", fill="white", path=SQUIGGLE, box=(0.035 + 0.016 * (k % 9), 0.064 + 0.048 * (k // 9), 0.012, 0.027))
              for k in range(18)]
    regions, _ = _publish(TITLE, *glyphs)
    (logo,) = [r for r in regions if r["role"] == "logo"]
    assert len(regions) == 2 and logo["i"] == 1 and logo["fill"] is None
    assert _box(logo) == pytest.approx(_union(glyphs))


def test_logos_and_icons_within_five_percent_merge_into_one_box_per_cluster():
    mark = [_r(1, "logo", "picture", box=(0.8, 0.05, 0.08, 0.06)), _r(2, "icon", box=(0.9, 0.05, 0.05, 0.06))]
    row = [_r(3 + k, "icon", fill="accent", box=(0.1 + 0.2 * k, 0.7, 0.05, 0.08)) for k in range(3)]  # 15% apart
    regions, _ = _publish(TITLE, *mark, *row)
    assert [(r["i"], r["role"]) for r in regions] == [(0, "title"), (1, "logo"), (3, "icon"), (4, "icon"), (5, "icon")]
    assert _box(regions[1]) == pytest.approx(_union(mark))
    assert [_box(r) for r in regions[2:]] == [_box(r) for r in row]


def test_a_map_of_many_small_shapes_publishes_as_one_unshaded_map_box():
    group = _r(1, "image", "group", box=(0.05, 0.2, 0.5, 0.6))
    shaded = {17, 88, 150}
    countries = [_r(2 + k, "other", fill="accent" if k in shaded else "neutral-light", line="white", parent=1, path=SQUIGGLE,
                    box=(0.06 + 0.024 * (k % 20) + 0.004 * (k % 3), 0.22 + 0.055 * (k // 20), 0.024, 0.05)) for k in range(200)]
    pin = _r(202, "other", geom="ellipse", fill="accent", line="accent", parent=1, box=(0.3, 0.4, 0.011, 0.019))
    big = _r(203, "decoration", fill="accent", parent=1, box=(0.1, 0.5, 0.12, 0.1))  # a large shaded country
    caption = _r(204, "label", "text", box=(0.1, 0.85, 0.3, 0.05), text=_txt())
    edge = _r(205, "decoration", fill="accent", box=(0.47, 0.3, 0.12, 0.08))  # a shaded country sticking out of the map
    regions, dna = _publish(TITLE, group, *countries, pin, big, caption, edge)
    assert [(r["i"], r["role"]) for r in regions] == [(0, "title"), (1, "image"), (204, "label")]
    assert _box(regions[1]) == pytest.approx(_union([group, *countries, pin, big, edge]))
    assert (regions[1]["fill"], regions[1]["line"], regions[1]["type"]) == (None, None, "picture")
    assert "accent" not in json.dumps(dna)


def test_paths_never_reach_the_record_and_normal_slides_only_lose_them():
    regions = [TITLE,
               _r(1, "body", "text", box=(0.05, 0.55, 0.4, 0.3), text=_txt(bullets=2), geom="rect"),
               *[_r(2 + k, "card", fill="accent", geom="chevron", path=SQUIGGLE, box=(0.05 + 0.3 * k, 0.2, 0.25, 0.15)) for k in range(3)],
               _r(5, "connector", "line", line="primary", geom="bentConnector3", path=[[[0, 0], [0.5, 0], [0.5, 1], [1, 1]]],
                  arrow="end", box=(0.3, 0.36, 0.3, 0.1)),
               _r(6, "image", "picture", box=(0.55, 0.55, 0.4, 0.35), geom="rect"),
               _r(7, "icon", fill="primary", box=(0.1, 0.05, 0.03, 0.05)),
               _r(8, "icon", fill="primary", box=(0.5, 0.05, 0.03, 0.05)),
               *[_r(9 + k, "decoration", geom="ellipse", fill="neutral-light", box=(0.05 + 0.07 * k, 0.92, 0.012, 0.022)) for k in range(5)]]
    published, _ = _publish(*regions)
    assert all("path" not in r for r in published)
    expect = [{k: v for k, v in r.items() if k != "path"} | {"geom": r.get("geom") if r["role"] not in ("logo", "icon") else None,
                                                            "arrow": r.get("arrow")} for r in regions]
    assert published == expect


def test_every_cluster_and_mark_on_a_slide_collapses_on_its_own():
    dots = lambda i, x: [_r(i + k, "other", fill="accent", box=(x + 0.01 * k, 0.6, 0.012, 0.02)) for k in range(6)]
    marks = lambda i, x: [_r(i + k, "logo", box=(x + 0.016 * k, 0.05, 0.012, 0.027)) for k in range(3)]
    regions, _ = _publish(TITLE, *dots(1, 0.1), *dots(10, 0.6), *marks(20, 0.05), *marks(30, 0.7))
    assert [(r["i"], r["role"]) for r in regions] == [(0, "title"), (1, "image"), (10, "image"), (20, "logo"), (30, "logo")]
    for r, members in zip(regions[1:], (dots(1, 0.1), dots(10, 0.6), marks(20, 0.05), marks(30, 0.7))):
        assert _box(r) == pytest.approx(_union(members))


def test_clusters_whose_boxes_overlap_join_into_one_box():
    sq = lambda i, x, y: _r(i, "other", fill="neutral-light", box=(x, y, 0.02, 0.02))
    ell = [sq(1 + k, 0.1 + 0.02 * k, 0.3) for k in range(6)] + [sq(7 + k, 0.1, 0.32 + 0.02 * k) for k in range(6)]
    row = [sq(20 + k, 0.15 + 0.02 * k, 0.38) for k in range(6)]  # inside the L's box, touching none of its shapes
    regions, _ = _publish(TITLE, *ell, *row)
    assert [(r["i"], r["role"]) for r in regions] == [(0, "title"), (1, "image")]
    assert _box(regions[1]) == pytest.approx(_union(ell + row))


def test_cards_and_callouts_inside_a_cluster_box_keep_their_place():
    photo = _r(1, "image", "picture", box=(0.1, 0.1, 0.6, 0.6))
    bits = [_r(2 + k, "other", fill="accent", box=(0.12 + 0.11 * k, 0.12 + 0.1 * k, 0.02, 0.02)) for k in range(6)]  # icons on it
    card = _r(10, "card", fill="neutral-light", box=(0.3, 0.3, 0.2, 0.1))
    note = _r(11, "callout", line="accent", dashed=True, box=(0.2, 0.5, 0.2, 0.1))
    regions, _ = _publish(TITLE, photo, *bits, card, note)
    assert [(r["i"], r["role"]) for r in regions] == [(0, "title"), (1, "image"), (10, "card"), (11, "callout")]
    assert regions[2:] == [r | {"geom": None, "arrow": None} for r in (card, note)]


def test_lines_and_the_dots_on_them_are_no_cluster():
    timeline = [_r(1, "other", geom="line", line="neutral-light", box=(0.9, 0.17, 0.0, 0.67)),
                _r(2, "other", geom="line", line="accent", box=(0.9, 0.17, 0.0, 0.43)),
                *[_r(3 + k, "other", geom="ellipse", fill="accent", box=(0.895, 0.2 + 0.19 * k, 0.011, 0.019)) for k in range(4)]]
    regions, _ = _publish(TITLE, *timeline)
    assert [r["i"] for r in regions] == [0, 1, 2, 3, 4, 5, 6]
    stripe = _r(2, "decoration", fill="accent", box=(0.898, 0.1, 0.0044, 0.9))  # a rule drawn as a thin freeform
    regions, _ = _publish(TITLE, timeline[0], stripe, *timeline[2:])
    assert [r["i"] for r in regions] == [0, 1, 2, 3, 4, 5, 6]


def test_published_regions_are_deterministic():
    glyphs = [_r(1 + k, "logo", box=(0.035 + 0.016 * (k % 9), 0.064 + 0.048 * (k // 9), 0.012, 0.027)) for k in range(18)]
    dots = [_r(20 + k, "other", fill="accent", box=(0.5 + 0.01 * k, 0.6, 0.012, 0.02)) for k in range(6)]
    first = _publish(TITLE, *glyphs, *dots)[1]
    assert json.dumps(first) == json.dumps(_publish(TITLE, *copy.deepcopy(glyphs), *copy.deepcopy(dots))[1])
    assert [(r["i"], r["role"]) for r in first["regions"]] == [(0, "title"), (1, "logo"), (20, "image")]


def test_text_and_logo_labels_are_unframed_and_keep_their_alignment(built, monkeypatch):
    out, ids = built
    left = _r(0, "title", "text", box=(0.1, 0.05, 0.6, 0.1), text=_txt(), line="primary", fill="accent")
    centre = _r(1, "body", "text", box=(0.2, 0.4, 0.6, 0.1), text=_txt() | {"align": "center"})
    logo = _r(2, "logo", "picture", box=(0.85, 0.05, 0.1, 0.1))
    dna = dict(_dna(out, ids[1]), regions=[left, centre, logo], insight_device="none")  # a filled title is no highlight here
    calls, real = [], build.ImageDraw.Draw
    monkeypatch.setattr(build.ImageDraw, "Draw", lambda img: _Rec(real(img), calls))
    img = Image.open(io.BytesIO(build.wireframe(dna)))
    texts = {c[1][1]: c for c in calls if c[0] == "text"}
    assert set(texts) == {"[title]", "[text]", "[logo]"}
    assert texts["[title]"][2]["anchor"] == "lm" and texts["[title]"][1][0][0] < 0.1 * img.width + 12
    assert texts["[text]"][2]["anchor"] == "mm"
    assert [c for c in calls if c[0] in ("line", "rectangle")] == []  # no frames at all


def test_frames_only_where_the_shape_matters():
    circle = lambda i, x: _r(i, "decoration", geom="ellipse", fill="accent", box=(x, 0.1, 0.08, 0.14))
    plan = _plan(circle(0, 0.1), circle(1, 0.3), circle(2, 0.5),  # a row of three: compositional
                 _r(3, "card", fill="accent", box=(0.1, 0.5, 0.1, 0.1)),  # an isolated small card: dropped
                 _r(4, "decoration", fill="accent", box=(0.9, 0.9, 0.03, 0.03)),  # a speck: dropped
                 _r(5, "card", line="accent", box=(0.5, 0.5, 0.4, 0.3)),  # large: framed
                 _r(6, "card", fill="neutral-light", box=(0.25, 0.45, 0.15, 0.2)),  # holds region 7: framed
                 _r(7, "body", "text", box=(0.27, 0.5, 0.1, 0.05), text=_txt()),
                 _r(8, "card", geom="ellipse", fill="accent", box=(0.02, 0.8, 0.06, 0.1)),  # joined by a connector
                 _r(9, "connector", "line", box=(0.08, 0.85, 0.2, 0.0)),
                 _r(10, "callout", "text", dashed=True, line="accent", box=(0.6, 0.05, 0.2, 0.1), text=_txt()))
    kept = {p["i"]: p for p in plan}
    assert {i for i, p in kept.items() if p.get("frame")} == {0, 1, 2, 5, 6, 8, 10}
    assert 3 not in kept and 4 not in kept and not kept[7]["frame"] and kept[9]["kind"] == "line"
    assert kept[10]["dashed"] and kept[0]["label"] is None and kept[6]["label"] is None


def test_record_context_decides_what_to_keep():
    rows = [_r(k, "decoration", fill="neutral-light", box=(0.05, 0.2 + 0.25 * k, 0.9, 0.08)) for k in range(3)]
    assert [p["kind"] for p in _plan(*rows, archetype="executive-summary")] == ["band"] * 3  # row bands
    assert _plan(*rows[:1], archetype="other") == []
    pair = [_r(k, "card", fill="accent", box=(0.1 + 0.3 * k, 0.3, 0.2, 0.2)) for k in range(2)]
    assert [p["frame"] for p in _plan(*pair, archetype="options")] == [True, True]  # a 2-option grid
    assert _plan(*pair, archetype="other") == []
    path = _r(0, "decoration", "line", box=(0.1, 0.5, 0.8, 0.0))
    assert [p["kind"] for p in _plan(path, archetype="customer-journey")] == ["line"]
    assert _plan(path, archetype="other") == []


def test_hero_numbers_are_drawn_larger_than_text(built, monkeypatch):
    out, ids = built
    dna = dict(_dna(out, ids[1]), regions=[_r(0, "big-number", "text", box=(0.1, 0.3, 0.3, 0.2), text=_txt(number="percent")),
                                           _r(1, "body", "text", box=(0.6, 0.3, 0.3, 0.2), text=_txt())])
    calls, real = [], build.ImageDraw.Draw
    monkeypatch.setattr(build.ImageDraw, "Draw", lambda img: _Rec(real(img), calls))
    build.wireframe(dna)
    size = {c[1][1]: c[2]["font"].size for c in calls if c[0] == "text"}
    assert size["[number]"] >= 1.5 * size["[text]"]


def test_dashed_frames_stay_dashed(built):
    out, ids = built
    card = _r(0, "card", fill="accent", box=(0.1, 0.2, 0.8, 0.6))
    for dashed in (False, True):
        img = Image.open(io.BytesIO(build.wireframe(dict(_dna(out, ids[1]), regions=[dict(card, dashed=dashed)]))))
        edge = {img.getpixel((x, int(0.2 * img.height))) for x in range(int(0.15 * img.width), int(0.85 * img.width))}
        assert (255 in edge) is dashed and min(edge) < 255


def test_lines_follow_their_path_and_draw_arrowheads(built):
    out, ids = built
    line = _r(0, "connector", "line", box=(0.1, 0.1, 0.4, 0.4), path=[[[1.0, 0.0], [0.0, 1.0]]])
    (p,) = _plan(line)
    assert p["pts"] == [(0.5, 0.1), (0.1, 0.5)]
    plain = build.wireframe(dict(_dna(out, ids[1]), regions=[line]))
    assert build.wireframe(dict(_dna(out, ids[1]), regions=[dict(line, arrow="end")])) != plain


def test_shape_heavy_slide_stays_under_size_cap(built):
    out, ids = built
    dna = _dna(out, ids[1])
    regions = []
    for k in range(48):
        x, y = (k % 8) / 8, (k // 8) / 6
        regions.append(_r(len(regions), "card", fill="accent", dashed=k % 2 == 0, box=(x, y, 0.12, 0.16),
                          path=[[[round((j * 7919 % 97) / 96, 3), round((j * 104729 % 89) / 88, 3)] for j in range(31)] + [[0.0, 0.0]]]))
        regions.append(_r(len(regions), "big-number", "text", box=(x + 0.01, y + 0.05, 0.1, 0.06), text=_txt(number="plain")))
    assert len(build.wireframe(dict(dna, regions=regions))) <= 30 * 1024


def test_images_sitting_on_a_framed_shape_draw_as_its_label():
    circle = lambda i, y: _r(i, "decoration", geom="ellipse", fill="accent", box=(0.5, y, 0.09, 0.16))
    photo = lambda i, y: _r(i, "image", "picture", box=(0.47, y - 0.05, 0.16, 0.28))  # a cut-out on its circle
    plan = _plan(circle(0, 0.1), photo(1, 0.1), circle(2, 0.4), photo(3, 0.4), circle(4, 0.7), photo(5, 0.7),
                 _r(6, "image", "picture", box=(0.05, 0.1, 0.3, 0.3)))  # a plain photo keeps its frame
    assert [(p["i"], p["frame"], p["label"]) for p in plan] == [
        (0, True, None), (1, False, "[image]"), (2, True, None), (3, False, "[image]"), (4, True, None),
        (5, False, "[image]"), (6, True, "[image]")]


def test_a_label_blocked_at_its_aligned_spot_moves_to_the_centre(built, monkeypatch):
    out, ids = built
    dna = dict(_dna(out, ids[1]), regions=[_r(0, "title", "text", box=(0.03, 0.05, 0.65, 0.09), text=_txt()),
                                           _r(1, "logo", "picture", box=(0.03, 0.03, 0.12, 0.12))])
    calls, real = [], build.ImageDraw.Draw
    monkeypatch.setattr(build.ImageDraw, "Draw", lambda img: _Rec(real(img), calls))
    build.wireframe(dna)
    texts = {c[1][1]: c[2]["anchor"] for c in calls if c[0] == "text"}
    assert texts == {"[logo]": "lm", "[title]": "mm"}


def test_tiny_ornaments_are_dropped_unless_a_line_runs_through_them():
    dot = lambda i, x, y: _r(i, "decoration", geom="ellipse", fill="neutral-light", box=(x, y, 0.012, 0.022))
    scattered = [dot(k, 0.05 + 0.07 * k, 0.9 - 0.004 * k) for k in range(5)]  # tiny, alike and roughly in a row
    on_line = [dot(10 + k, 0.2 + 0.2 * k, 0.489) for k in range(3)]
    plan = _plan(*scattered, *on_line, _r(20, "connector", "line", box=(0.1, 0.5, 0.8, 0.0)))
    assert [p["i"] for p in plan if p["kind"] == "shape"] == [10, 11, 12]


def test_nested_stacks_are_texture_not_composition():
    stack = lambda i, x: [_r(i + k, "decoration", fill="accent", box=(x + 0.004 * k, 0.7, 0.047 - 0.004 * k, 0.084 - 0.007 * k))
                          for k in range(4)]
    plan = _plan(*stack(0, 0.6), *stack(10, 0.75), *stack(20, 0.9), insight_device="highlight-contrast")
    assert plan == []


def test_stripes_of_any_size_stacked_in_a_card_are_texture_but_venn_circles_are_not():
    stripe = [[[0.96, 1.0], [0.0, 0.04], [0.0, 0.0], [1.0, 1.0], [0.96, 1.0]]]
    stripes = [_r(10 * c + k, "decoration", fill="accent", path=stripe, box=(0.1 + 0.3 * c + 0.01 * k, 0.6, 0.12 - 0.02 * k, 0.2 - 0.03 * k))
               for c in range(3) for k in range(4)]
    texts = [_r(100 + c, "body", "text", box=(0.12 + 0.3 * c, 0.65, 0.08, 0.06), text=_txt()) for c in range(3)]
    assert [p["i"] for p in _plan(*stripes, *texts)] == [100, 101, 102]  # text under the stripes keeps no frame
    panel = [_r(0, "card", fill="neutral-light", box=(0.1, 0.1, 0.5, 0.5))] + [
        _r(1 + k, "card", fill="accent", box=(0.12 + 0.16 * k, 0.2, 0.14, 0.3)) for k in range(3)]
    assert [p["frame"] for p in _plan(*panel)] == [True] * 4  # a panel with its cards is no texture
    venn = [_r(k, "decoration", geom="ellipse", line="accent", box=(0.3 + 0.12 * k, 0.3, 0.2, 0.35)) for k in range(3)]
    assert [p["frame"] for p in _plan(*venn)] == [True, True, True]
