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
from pipeline.tests.conftest import fixture_labels


def _label(lib, deck_id):
    work = lib / "work" / deck_id
    for f in sorted(work.glob("slide-??.json")):
        (work / "labels" / f.name).write_text(json.dumps(fixture_labels(json.loads(f.read_text()))))
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


def test_description_uses_fixed_template_without_digits(built):
    out, ids = built
    dna = _dna(out, ids[0])
    d = dna["description"]
    assert d.startswith("Title slide. Single claim argument, big number device, kpi numbers data, travel hospitality.")
    assert dna["purpose"] in d and dna["why_it_works"] in d and "outcome promise" in d
    assert not re.search(r"\d", d)


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


def _plan(*regions):
    return build._plan({"id": "0" * 16 + "-01", "regions": list(regions)})


def test_circles_draw_as_ellipses_and_rounded_shapes_as_rounded():
    plan = _plan(_r(0, "card", geom="ellipse", box=(0.1, 0.1, 0.2, 0.2)),
                 _r(1, "card", geom="roundRect", box=(0.5, 0.1, 0.2, 0.2)),
                 _r(2, "card", geom="rect", box=(0.1, 0.5, 0.2, 0.2)),
                 _r(3, "card", box=(0.5, 0.5, 0.2, 0.2)))  # records built before geometry was extracted
    assert [(p["i"], p["kind"]) for p in plan] == [(0, "ellipse"), (1, "round"), (2, "rect"), (3, "rect")]


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
    assert [(p["kind"], p["xy"]) for p in plan] == [
        ("line", (0.1, 0.5, 0.9, 0.5)), ("line", (0.2, 0.2, 0.30000000000000004, 0.5)), ("line", (0.1, 0.802, 0.9, 0.802))]


def test_near_duplicate_boxes_merge_into_the_larger():
    plan = _plan(_r(0, "card", box=(0.1, 0.1, 0.5, 0.2)),
                 _r(1, "title", "text", box=(0.11, 0.1, 0.48, 0.19), text=_txt()),
                 _r(2, "body", "text", box=(0.1, 0.5, 0.3, 0.3), text=_txt()),
                 _r(3, "body", "text", box=(0.1, 0.5, 0.29, 0.29), text=_txt()))
    assert [(p["i"], tuple(round(v, 3) for v in p["box"]), p["label"]) for p in plan] == [
        (0, (0.1, 0.1, 0.5, 0.2), "[title]"), (2, (0.1, 0.5, 0.3, 0.3), "[text]")]


def test_unlabelled_container_holding_other_boxes_is_drawn_without_label():
    plan = _plan(_r(0, "card", box=(0.1, 0.1, 0.6, 0.6)),
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
    assert drawn <= {"rectangle", "rounded_rectangle", "ellipse", "line", "text", "textlength"}, drawn
    texts = [c for c in calls if c[0] == "text"]
    assert sorted(c[1][1] for c in texts) == ["[bar chart]", "[bullets]", "[image]", "[shape]", "[shape]", "[shape]", "[table]", "[text]"]
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
    assert [c[0] for c in calls if c[0] == "text"] == []
    assert [c[0] for c in calls if c[0] == "rectangle"] == ["rectangle"]


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
