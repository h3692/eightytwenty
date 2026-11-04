import io
import json

import pytest
from PIL import Image

from pipeline import extract, layout
from pipeline.__main__ import main


class _Rec:
    """Records every draw call while still drawing."""
    def __init__(self, d, calls):
        self.d, self.calls = d, calls

    def __getattr__(self, name):
        f = getattr(self.d, name)
        return lambda *a, **k: (self.calls.append((name, a, k)), f(*a, **k))[1]


@pytest.fixture
def calls(monkeypatch):
    calls, real = [], layout.ImageDraw.Draw
    monkeypatch.setattr(layout.ImageDraw, "Draw", lambda img: _Rec(real(img), calls))
    return calls


def _el(kind, box, shape="none", **kw):
    return dict(kind=kind, shape=shape, box=list(box), **kw)


def _texts(calls):
    return [c[1][1] for c in calls if c[0] == "text"]


SAMPLE = {"elements": [
    _el("band", (0, 0, 1, 0.2), "rect"),
    _el("title", (0.05, 0.05, 0.6, 0.1)),
    _el("card", (0.05, 0.3, 0.4, 0.5), "round_rect", region_ids=[1, 2]),
    _el("number", (0.1, 0.35, 0.3, 0.3), emphasis="hero"),
    _el("bar_chart", (0.55, 0.3, 0.4, 0.5), "rect"),
    _el("connector", (0.45, 0.5, 0.1, 0.05), "line", **{"from": 2, "to": 4}, dashed=True),
    _el("panel", (0.5, 0.25, 0.48, 0.6), "polygon", points=[[0.5, 0.25], [0.98, 0.25], [0.98, 0.85]]),
]}


# --- schema ---------------------------------------------------------------------------------------------------

def test_sample_layout_validates():
    layout.validate(SAMPLE)


def _strings_without_enum(node):
    if isinstance(node, dict):
        if node.get("type") == "string" and "enum" not in node:
            yield node
        for v in node.values():
            yield from _strings_without_enum(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings_without_enum(v)


def test_schema_has_no_free_text_fields():
    assert list(_strings_without_enum(layout.SCHEMA)) == []


@pytest.mark.parametrize("mutate, message", [
    (lambda l: l["elements"][1].update(text="Revenue up"), "text"),
    (lambda l: l["elements"][1].update(label="Revenue"), "label"),
    (lambda l: l.update(title="Q3 results"), "title"),
    (lambda l: l["elements"][1].update(kind="headline"), "headline"),
    (lambda l: l["elements"][1].update(shape="star"), "star"),
    (lambda l: l["elements"][1].update(box=[0.1, 0.1, 1.2, 0.1]), "box"),
    (lambda l: l["elements"][1].update(box=[0.1, 0.1, 0.2]), "box"),
    (lambda l: l["elements"][1].update(emphasis="loud"), "loud"),
    (lambda l: l["elements"][6].update(points=[[0.1, 0.1]] * 13), "points"),
    (lambda l: l["elements"].extend([_el("text", (0, 0, 0.1, 0.1))] * 19), "elements"),
    (lambda l: l["elements"][5].update(to=99), "to"),
])
def test_invalid_layouts_fail(mutate, message):
    bad = json.loads(json.dumps(SAMPLE))
    mutate(bad)
    with pytest.raises(ValueError, match=message):
        layout.validate(bad)


# --- renderer -------------------------------------------------------------------------------------------------

def test_render_is_small_greyscale_on_white():
    png = layout.render_layout(SAMPLE)
    img = Image.open(io.BytesIO(png))
    assert len(png) <= 30 * 1024 and img.mode == "L" and img.size == (960, 540)
    assert img.getpixel((img.width - 2, img.height - 2)) == 255


def test_labels_come_from_kind(calls):
    layout.render_layout({"elements": [_el("bar_chart", (0.05, 0.1, 0.4, 0.4), "rect"),
                                       _el("image", (0.5, 0.1, 0.4, 0.4), "rect"),
                                       _el("table", (0.05, 0.55, 0.4, 0.4), "rect"),
                                       _el("pie_chart", (0.5, 0.55, 0.4, 0.4), "ellipse")]})
    assert sorted(_texts(calls)) == ["[bar chart]", "[image]", "[pie chart]", "[table]"]


@pytest.mark.parametrize("kind", ["title", "subtitle", "text", "bullets", "quote", "number", "label", "logo"])
def test_text_kinds_are_unframed_labels(calls, kind):
    layout.render_layout({"elements": [_el(kind, (0.1, 0.1, 0.6, 0.2), "rect", dashed=True)]})
    assert _texts(calls) == [f"[{kind}]"]
    assert [c[0] for c in calls if c[0] not in ("text", "textlength")] == []


def test_framed_kinds_draw_a_frame_and_their_label_inside(calls):
    png = layout.render_layout({"elements": [_el("image", (0.2, 0.2, 0.5, 0.5), "rect")]})
    img = Image.open(io.BytesIO(png))
    assert _texts(calls) == ["[image]"]
    assert img.getpixel((int(0.2 * 960), int(0.45 * 540))) < 255  # left edge of the frame
    t = next(c for c in calls if c[0] == "text")
    x, y = t[1][0]
    assert 0.2 * 960 < x < 0.7 * 960 and 0.2 * 540 < y < 0.7 * 540


def _font_size(calls, label):
    return next(c[2]["font"].size for c in calls if c[0] == "text" and c[1][1] == label)


def test_hero_number_is_drawn_large(calls):
    box = (0.1, 0.1, 0.5, 0.5)
    layout.render_layout({"elements": [_el("number", box)]})
    normal = _font_size(calls, "[number]")
    calls.clear()
    layout.render_layout({"elements": [_el("number", box, emphasis="hero")]})
    assert _font_size(calls, "[number]") >= 2 * normal


def test_labels_shrink_to_fit_or_are_omitted(calls):
    layout.render_layout({"elements": [_el("title", (0.1, 0.1, 0.035, 0.1))]})
    size = _font_size(calls, "[title]")
    calls.clear()
    layout.render_layout({"elements": [_el("title", (0.1, 0.1, 0.6, 0.1))]})
    assert size < _font_size(calls, "[title]")
    calls.clear()
    layout.render_layout({"elements": [_el("title", (0.1, 0.1, 0.005, 0.005))]})
    assert _texts(calls) == []


def _edge(png, y, x0, x1):
    img = Image.open(io.BytesIO(png))
    return [img.getpixel((x, y)) for x in range(x0, x1)]


def test_dashed_frames_have_gaps():
    el = _el("image", (0.2, 0.2, 0.5, 0.5), "rect")
    y = int(0.2 * 540)
    solid = _edge(layout.render_layout({"elements": [el]}), y, 300, 500)
    dashed = _edge(layout.render_layout({"elements": [dict(el, dashed=True)]}), y, 300, 500)
    assert 255 not in solid and 255 in dashed and min(dashed) < 255


def test_arrows_and_connectors_get_filled_arrowheads(calls):
    layout.render_layout({"elements": [_el("arrow", (0.1, 0.4, 0.3, 0.1), "arrow_right")]})
    heads = [c for c in calls if c[0] == "polygon" and c[2].get("fill") is not None]
    assert len(heads) == 1
    tip = max(heads[0][1][0], key=lambda p: p[0])
    assert tip == pytest.approx((0.4 * 960, 0.45 * 540), abs=1)
    calls.clear()
    layout.render_layout({"elements": [_el("card", (0.05, 0.3, 0.2, 0.3)), _el("card", (0.6, 0.3, 0.2, 0.3)),
                                       _el("connector", (0.25, 0.4, 0.35, 0.1), "line", **{"from": 0, "to": 1})]})
    heads = [c for c in calls if c[0] == "polygon" and c[2].get("fill") == layout.build.INK]
    assert len(heads) == 1
    assert max(p[0] for p in heads[0][1][0]) == pytest.approx(0.6 * 960, abs=1)  # stops at the target card's edge


def test_dividers_have_no_arrowhead(calls):
    layout.render_layout({"elements": [_el("divider", (0.1, 0.5, 0.8, 0.01), "line")]})
    assert [c for c in calls if c[0] == "polygon"] == [] and [c for c in calls if c[0] == "line"]


def test_draw_order_containers_cards_frames_lines_labels(calls):
    layout.render_layout({"elements": [_el("title", (0.05, 0.02, 0.5, 0.1)),
                                       _el("arrow", (0.4, 0.5, 0.2, 0.05), "arrow_right"),
                                       _el("image", (0.6, 0.3, 0.3, 0.4), "rect"),
                                       _el("card", (0.05, 0.3, 0.3, 0.4)),
                                       _el("band", (0, 0, 1, 0.15), "rect")]})
    fills = [c[2]["fill"] for c in calls if c[0] == "polygon" and c[2].get("fill") not in (None, layout.build.INK)]
    first = {name: next(i for i, c in enumerate(calls) if pred(c)) for name, pred in (
        ("band", lambda c: c[0] == "polygon" and c[2].get("fill") == layout.BAND),
        ("card", lambda c: c[0] == "polygon" and c[2].get("fill") == layout.CARD),
        ("frame", lambda c: c[0] == "line"),
        ("head", lambda c: c[0] == "polygon" and c[2].get("fill") == layout.build.INK),
        ("label", lambda c: c[0] == "text"))}
    assert fills == [layout.BAND, layout.CARD]
    assert first["band"] < first["card"] < first["frame"] < first["head"] < first["label"]


def test_busy_layout_stays_under_the_size_cap():
    els = [_el(k, ((i % 5) * 0.2, (i // 5) * 0.2, 0.18, 0.18), s, dashed=i % 2 == 0)
           for i, (k, s) in enumerate([("card", "round_rect"), ("image", "rect"), ("line_chart", "rect"),
                                       ("step", "chevron"), ("icon", "ellipse")] * 5)]
    png = layout.render_layout({"elements": els})
    assert len(png) <= 30 * 1024


# --- snap -----------------------------------------------------------------------------------------------------

SLIDE = {"regions": [{"i": 0, "box": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}},
                     {"i": 1, "box": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.1}},
                     {"i": 2, "box": {"x": 0.25, "y": 0.4, "w": 0.3, "h": 0.2}}]}


def test_snap_replaces_box_with_union_of_regions():
    out = layout.snap(SAMPLE, SLIDE)
    assert out["elements"][2]["box"] == pytest.approx([0.1, 0.2, 0.45, 0.4])
    assert out["elements"][1]["box"] == SAMPLE["elements"][1]["box"]  # no region_ids: the agent's box stays
    assert SAMPLE["elements"][2]["box"] == [0.05, 0.3, 0.4, 0.5]  # input untouched


def test_snap_rejects_unknown_regions():
    with pytest.raises(ValueError, match="9"):
        layout.snap({"elements": [_el("text", (0, 0, 0.1, 0.1), region_ids=[9])]}, SLIDE)


# --- worksheet + render command -------------------------------------------------------------------------------

@pytest.fixture
def deck_id(deck, lib):
    return extract.run(deck, lib, render=False)


def test_worksheet_variant_a_is_picture_only(deck_id, lib):
    main(["layout-prep", deck_id, "--library", str(lib)])
    out = lib / "layouts" / deck_id
    prompts = sorted(p.name for p in out.glob("*.prompt.txt"))
    assert prompts == ["slide-01.A.prompt.txt", "slide-02.A.prompt.txt"]
    text = (out / "slide-02.A.prompt.txt").read_text()
    for needed in ("slide-02.png", str(out / "slide-02.A.json"), "layout.v1.json", "5-20", "bar_chart", "chevron",
                   "Merge stacked text lines", "decoration", "background texture", "connectors", "insight device"):
        assert needed in text, needed
    assert "slide-02.json" not in text and "region_ids" not in text
    assert (out / "slide-01.A.prompt.txt").read_text().replace("slide-01", "slide-02") == text


def test_worksheet_variant_b_adds_regions_and_slide_filter(deck_id, lib):
    main(["layout-prep", deck_id, "--library", str(lib), "--slides", "02", "--variant", "B"])
    out = lib / "layouts" / deck_id
    assert sorted(p.name for p in out.glob("*.prompt.txt")) == ["slide-02.B.prompt.txt"]
    text = (out / "slide-02.B.prompt.txt").read_text()
    for needed in ("slide-02.png", str(lib / "work" / deck_id / "slide-02.json"), str(out / "slide-02.B.json"),
                   "region_ids", "union"):
        assert needed in text, needed


def test_render_command_validates_snaps_and_writes_pngs(deck_id, lib):
    out = lib / "layouts" / deck_id
    out.mkdir(parents=True)
    slide = json.loads((lib / "work" / deck_id / "slide-02.json").read_text())
    r = slide["regions"][1]
    (out / "slide-02.B.json").write_text(json.dumps({"elements": [_el("image", (0, 0, 0.1, 0.1), "rect", region_ids=[r["i"]])]}))
    main(["layout-render", deck_id, "--library", str(lib), "--variant", "B"])
    img = Image.open(out / "slide-02.B.png")
    assert img.mode == "L"
    x0 = int(r["box"]["x"] * img.width)
    assert img.getpixel((x0, int((r["box"]["y"] + r["box"]["h"] / 2) * img.height))) < 255  # frame at the snapped box
    (out / "slide-01.B.json").write_text(json.dumps({"elements": [_el("text", (0, 0, 0.1, 0.1), label="Hi")]}))
    with pytest.raises(ValueError, match="slide-01.B.json"):
        layout.render(deck_id, lib, "B")
