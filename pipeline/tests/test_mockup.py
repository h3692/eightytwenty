import io
import json
import random
import re
import shutil
import zipfile

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE, XL_TICK_LABEL_POSITION
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE
from pptx.enum.text import PP_ALIGN
from pptx.util import Emu

from pipeline import extract, mockup
from pipeline.__main__ import main

HAS_SOFFICE = bool(shutil.which("soffice") or extract.SOFFICE_APP.exists())
needs_soffice = pytest.mark.skipif(not HAS_SOFFICE, reason="LibreOffice not installed")
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"
W, H = 12192000, 6858000


def _el(kind, box, shape="none", **kw):
    return dict(kind=kind, shape=shape, box=list(box), **kw)


def _lay(*els):
    return {"version": 2, "elements": list(els)}


def _shapes(layout):
    return list(mockup.build_mockup(layout).slides[0].shapes)


def _text(shape):
    return shape.text_frame.text if shape.has_text_frame else ""


def _ln(shape):
    return shape._element.spPr.find(f"{A}ln")


BUSY = _lay(
    _el("band", (0, 0, 1, 0.15), "rect", fill="light"),
    _el("title", (0.05, 0.03, 0.6, 0.09), parent=0),
    _el("strip", (0, 0.15, 0.08, 0.85), "rect", fill="mid"),
    _el("panel", (0.1, 0.2, 0.4, 0.75), "rect", fill="dark"),
    _el("card", (0.12, 0.22, 0.36, 0.3), "rect", parent=3),
    _el("number", (0.14, 0.24, 0.3, 0.2), emphasis="hero", parent=4),
    _el("chart", (0.55, 0.2, 0.2, 0.3), "rect", chart_type="column", series=2, categories=4),
    _el("chart", (0.77, 0.2, 0.2, 0.3), "rect", chart_type="donut", categories=5),
    _el("table", (0.55, 0.55, 0.42, 0.25), "rect", rows=5, cols=4, header_row=True),
    _el("connector", (0.5, 0.3, 0.05, 0.05), "line", **{"from": 4, "to": 6}),
    _el("arrow", (0.6, 0.85, 0.1, 0.06), "arrow_right", arrow_style="block"),
    _el("arrow", (0.72, 0.85, 0.1, 0.06), "chevron", arrow_style="chevron"),
    _el("takeaway", (0.12, 0.6, 0.36, 0.1), framed=True, parent=3),
    _el("bullets", (0.12, 0.72, 0.36, 0.2), parent=3),
    _el("image", (0.84, 0.82, 0.12, 0.15), "ellipse"),
    _el("icon", (0.1, 0.85, 0.05, 0.08), "diamond"),
    _el("logo", (0.9, 0.03, 0.08, 0.06)),
    _el("divider", (0.05, 0.14, 0.9, 0.0), "line", dashed=True),
    _el("step", (0.6, 0.92, 0.1, 0.06), "chevron"),
    _el("callout", (0.3, 0.85, 0.15, 0.1), "round_rect"),
)


# --- shapes ---------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("shape, preset", [
    ("rect", MSO_SHAPE.RECTANGLE), ("none", MSO_SHAPE.RECTANGLE), ("round_rect", MSO_SHAPE.ROUNDED_RECTANGLE),
    ("ellipse", MSO_SHAPE.OVAL), ("chevron", MSO_SHAPE.CHEVRON), ("arrow_right", MSO_SHAPE.RIGHT_ARROW),
    ("arrow_left", MSO_SHAPE.LEFT_ARROW), ("arrow_up", MSO_SHAPE.UP_ARROW), ("arrow_down", MSO_SHAPE.DOWN_ARROW),
    ("triangle", MSO_SHAPE.ISOSCELES_TRIANGLE), ("diamond", MSO_SHAPE.DIAMOND),
])
def test_shapes_map_to_autoshape_presets(shape, preset):
    frame, label = _shapes(_lay(_el("image", (0.2, 0.2, 0.4, 0.4), shape)))
    assert frame.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and frame.auto_shape_type == preset
    assert (frame.left, frame.top, frame.width, frame.height) == (round(0.2 * W), round(0.2 * H), round(0.4 * W), round(0.4 * H))
    assert _text(frame) == "" and _text(label) == "[image]"
    assert label.text_frame.paragraphs[0].alignment == PP_ALIGN.CENTER


def test_cards_have_rounded_corners_and_containers_carry_no_label():
    card, = _shapes(_lay(_el("card", (0.2, 0.2, 0.4, 0.4), "rect")))
    assert card.auto_shape_type == MSO_SHAPE.ROUNDED_RECTANGLE and _text(card) == ""


def test_shapes_carry_no_theme_style_so_no_shadow_or_accent_colour():
    slide = mockup.build_mockup(BUSY).slides[0]
    assert slide._element.findall(".//{http://schemas.openxmlformats.org/presentationml/2006/main}style") == []


def test_polygons_are_freeforms():
    pts = [[0.1, 0.1], [0.5, 0.1], [0.3, 0.6]]
    poly, = _shapes(_lay(_el("panel", (0.1, 0.1, 0.4, 0.5), "polygon", points=pts)))
    assert poly.shape_type == MSO_SHAPE_TYPE.FREEFORM
    path = poly._element.find(f".//{A}path")
    assert len(path.findall(f"{A}lnTo")) == 2 and path.find(f"{A}close") is not None


@pytest.mark.parametrize("fill", ["light", "mid", "dark"])
def test_container_fills_are_greys_that_darken(fill):
    shades = {}
    for f in ("light", "mid", "dark"):
        band, = _shapes(_lay(_el("band", (0, 0, 1, 0.2), "rect", fill=f)))
        rgb = band.fill.fore_color.rgb
        assert rgb[0] == rgb[1] == rgb[2]
        shades[f] = rgb[0]
    assert shades["light"] > shades["mid"] > shades["dark"]
    band, = _shapes(_lay(_el("band", (0, 0, 1, 0.2), "rect", fill="none")))
    assert band.fill.type is None or band._element.spPr.find(f"{A}noFill") is not None


def test_text_kinds_are_unframed_left_aligned_unless_framed():
    label, = _shapes(_lay(_el("text", (0.1, 0.1, 0.5, 0.2), "rect")))
    assert label.shape_type == MSO_SHAPE_TYPE.TEXT_BOX and _text(label) == "[text]"
    assert label.text_frame.paragraphs[0].alignment == PP_ALIGN.LEFT
    frame, label = _shapes(_lay(_el("takeaway", (0.1, 0.1, 0.5, 0.2), framed=True)))
    assert frame.auto_shape_type == MSO_SHAPE.RECTANGLE and _text(label) == "[takeaway]"
    assert label.text_frame.paragraphs[0].alignment == PP_ALIGN.CENTER


def _size(layout):
    label = [s for s in _shapes(layout) if _text(s)][-1]
    return label.text_frame.paragraphs[0].runs[0].font.size


def test_emphasis_drives_real_size():
    box = (0.1, 0.1, 0.6, 0.5)
    normal = _size(_lay(_el("number", box)))
    assert _size(_lay(_el("number", box, emphasis="hero"))) >= 2 * normal
    assert _size(_lay(_el("text", box, emphasis="strong"))) > _size(_lay(_el("text", box)))
    thin, = [s for s in _shapes(_lay(_el("image", box, "rect"))) if not _text(s)]
    thick, = [s for s in _shapes(_lay(_el("image", box, "rect", emphasis="hero"))) if not _text(s)]
    assert thin.line.width == Emu(19050) and thick.line.width > thin.line.width  # 1.5 pt house line


def test_labels_shrink_to_fit_or_are_omitted():
    assert _size(_lay(_el("title", (0.1, 0.1, 0.04, 0.1)))) < _size(_lay(_el("title", (0.1, 0.1, 0.6, 0.1))))
    assert _shapes(_lay(_el("title", (0.1, 0.1, 0.004, 0.004)))) == []


def test_font_is_pinned():
    label, = _shapes(_lay(_el("text", (0.1, 0.1, 0.5, 0.2))))
    assert label.text_frame.paragraphs[0].runs[0].font.name == mockup.FONT


# --- lines ----------------------------------------------------------------------------------------------------

def _ends(shape):
    ln = _ln(shape)
    return [ln.find(f"{A}{t}") is not None for t in ("headEnd", "tailEnd")]


@pytest.mark.parametrize("head, ends", [(None, [False, True]), ("end", [False, True]), ("both", [True, True]),
                                        ("none", [False, False])])
def test_connectors_join_elements_with_arrowheads(head, ends):
    extra = {"head": head} if head else {}
    a, b, line, *_ = _shapes(_lay(_el("image", (0.05, 0.3, 0.2, 0.3), "rect"), _el("image", (0.6, 0.3, 0.2, 0.3), "rect"),
                                  _el("connector", (0.25, 0.4, 0.35, 0.1), "line", **{"from": 0, "to": 1}, **extra)))
    assert line.shape_type == MSO_SHAPE_TYPE.LINE
    assert (line.begin_x, line.end_x) == (a.left + a.width, b.left)  # from edge to edge
    assert _ends(line) == ends
    if ends[1]:
        assert _ln(line).find(f"{A}tailEnd").get("type") == "triangle"


def test_multi_point_connectors_are_open_polylines_and_dividers_have_no_head():
    poly, div = _shapes(_lay(_el("connector", (0.1, 0.1, 0.5, 0.5), "line", points=[[0.1, 0.1], [0.6, 0.1], [0.6, 0.6]]),
                             _el("divider", (0.1, 0.8, 0.8, 0.0), "line", dashed=True)))
    assert poly.shape_type == MSO_SHAPE_TYPE.FREEFORM and poly._element.find(f".//{A}close") is None
    assert _ends(poly) == [False, True] and _ends(div) == [False, False]
    assert _ln(div).find(f"{A}prstDash").get("val") == "dash"


@pytest.mark.parametrize("style, shape, preset", [("block", "arrow_right", MSO_SHAPE.RIGHT_ARROW),
                                                  ("block", "rect", MSO_SHAPE.RIGHT_ARROW),
                                                  ("block", "arrow_up", MSO_SHAPE.UP_ARROW),
                                                  ("chevron", "chevron", MSO_SHAPE.CHEVRON)])
def test_block_and_chevron_arrows_are_autoshapes(style, shape, preset):
    arrow, = _shapes(_lay(_el("arrow", (0.1, 0.4, 0.3, 0.1), shape, arrow_style=style)))
    assert arrow.auto_shape_type == preset and _text(arrow) == ""


def test_line_arrows_point_along_the_box():
    arrow, = _shapes(_lay(_el("arrow", (0.1, 0.4, 0.3, 0.1), "arrow_left", arrow_style="line")))
    assert arrow.shape_type == MSO_SHAPE_TYPE.LINE and arrow.end_x < arrow.begin_x and _ends(arrow) == [False, True]


# --- tables and charts ----------------------------------------------------------------------------------------

def test_tables_are_real_empty_grids():
    frame, = _shapes(_lay(_el("table", (0.1, 0.1, 0.6, 0.5), "rect", rows=7, cols=4, header_row=True)))
    table = frame.table
    assert (len(table.rows), len(table.columns)) == (7, 4) and table.first_row
    cells = [table.cell(r, c) for r in range(7) for c in range(4)]
    assert all(c.text == "" for c in cells)
    head, body = table.cell(0, 0).fill.fore_color.rgb, table.cell(3, 2).fill.fore_color.rgb
    assert head != body and head[0] == head[1] == head[2]
    assert frame.height <= round(0.5 * H) + 1


CHARTS = {"bar": XL_CHART_TYPE.BAR_CLUSTERED, "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
          "stacked_bar": XL_CHART_TYPE.BAR_STACKED, "line": XL_CHART_TYPE.LINE, "pie": XL_CHART_TYPE.PIE,
          "donut": XL_CHART_TYPE.DOUGHNUT, "scatter": XL_CHART_TYPE.XY_SCATTER, "waterfall": XL_CHART_TYPE.COLUMN_STACKED,
          "area": XL_CHART_TYPE.AREA}


def _dummies(index, series, categories):
    rng = random.Random(index)
    return [[rng.randint(10, 100) for _ in range(categories)] for _ in range(series)]


@pytest.mark.parametrize("chart_type", CHARTS)
def test_charts_are_native_with_seeded_dummy_data(chart_type):
    els = [_el("text", (0, 0, 0.3, 0.1)), _el("chart", (0.1, 0.2, 0.5, 0.6), "rect", chart_type=chart_type, series=2, categories=5)]
    frame = next(s for s in _shapes(_lay(*els)) if s.has_chart)
    chart = frame.chart
    assert chart.chart_type == CHARTS[chart_type] and not chart.has_legend
    assert chart.chart_title.text_frame.text == f"[{chart_type.replace('_', ' ')} chart]"
    values = [list(s.values) for s in chart.plots[0].series]
    expected = _dummies(1, 2, 5)
    if chart_type == "waterfall":  # invisible running-total base under the visible steps
        expected = [[sum(expected[0][:k]) for k in range(5)], expected[0]]
    elif chart_type == "pie":  # a pie has one series
        expected = expected[:1]
    assert values == expected
    if chart_type not in ("pie", "donut"):
        assert chart.value_axis.tick_label_position == XL_TICK_LABEL_POSITION.NONE
        assert not chart.value_axis.has_major_gridlines
        assert chart.category_axis.tick_label_position == XL_TICK_LABEL_POSITION.NONE


def test_chart_defaults():
    chart = _shapes(_lay(_el("chart", (0.1, 0.2, 0.5, 0.6), "rect", chart_type="line")))[0].chart
    assert [len(list(s.values)) for s in chart.plots[0].series] == [4]


# --- z-order --------------------------------------------------------------------------------------------------

def test_z_order_strips_cards_frames_connectors_labels():
    shapes = _shapes(_lay(_el("title", (0.05, 0.02, 0.5, 0.1)),
                          _el("arrow", (0.4, 0.5, 0.2, 0.05), "arrow_right", arrow_style="line"),
                          _el("image", (0.6, 0.3, 0.3, 0.4), "rect"),
                          _el("card", (0.05, 0.3, 0.3, 0.4)),
                          _el("chart", (0.05, 0.75, 0.2, 0.2), "rect", chart_type="pie"),
                          _el("strip", (0.9, 0, 0.1, 1), "rect"),
                          _el("band", (0, 0, 1, 0.15), "rect")))
    order = [s.shape_type for s in shapes]
    assert order[:3] == [MSO_SHAPE_TYPE.AUTO_SHAPE] * 3  # strip, band (list order), then card
    assert shapes[2].auto_shape_type == MSO_SHAPE.ROUNDED_RECTANGLE
    assert order[3] == MSO_SHAPE_TYPE.AUTO_SHAPE and order[4] == MSO_SHAPE_TYPE.CHART
    assert order[5] == MSO_SHAPE_TYPE.LINE
    assert [_text(s) for s in shapes[6:]] == ["[title]", "[image]"]


def test_nested_containers_draw_above_their_parent():
    shapes = _shapes(_lay(_el("card", (0.1, 0.1, 0.8, 0.8)),
                          _el("panel", (0.2, 0.2, 0.3, 0.3), "rect", parent=0),
                          _el("card", (0.25, 0.25, 0.1, 0.1), parent=1),
                          _el("band", (0, 0, 1, 0.1), "rect")))
    lefts = [s.left for s in shapes]
    assert lefts == [0, round(0.1 * W), round(0.2 * W), round(0.25 * W)]


# --- leak guard + determinism ---------------------------------------------------------------------------------

def _all_text(blob):
    """Every a:t run in every XML part of a .pptx, and every cached chart string."""
    runs, cached = [], []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if name.endswith(".xml"):
                xml = z.read(name).decode()
                runs += re.findall(r"<a:t>([^<]*)</a:t>", xml)
                if "/charts/" in name:
                    cached += re.findall(r"<c:v>([^<]*)</c:v>", xml)
    return runs, cached


def test_leak_guard(tmp_path):
    path = tmp_path / "m.pptx"
    mockup.save(mockup.build_mockup(BUSY), path)
    blob = path.read_bytes()
    blank = io.BytesIO()
    Presentation().save(blank)
    template_runs = set(_all_text(blank.getvalue())[0])  # master/layout boilerplate shipped with python-pptx
    runs, cached = _all_text(blob)
    labels = set(runs) - template_runs
    assert labels and labels <= mockup.LABELS
    assert all(re.fullmatch(r"\[[a-z ]+\]", lab) for lab in mockup.LABELS)
    assert all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in cached)  # chart caches: numbers only
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        types = z.read("[Content_Types].xml").decode()
    assert not [n for n in names if re.search(r"\.(jpe?g|png|gif|bmp|tiff?|emf|wmf|svg)$", n, re.I)]
    assert "image/" not in types
    props = Presentation(path).core_properties
    assert (props.author, props.last_modified_by, props.title, props.comments) == ("", "", "", "")
    assert props.created == props.modified == mockup.FIXED_TIME
    chart = next(s for s in Presentation(path).slides[0].shapes if s.has_chart).chart
    assert [list(s.values) for s in chart.plots[0].series] == _dummies(6, 2, 4)


def test_saved_mockups_are_byte_identical(tmp_path):
    a, b = tmp_path / "a.pptx", tmp_path / "b.pptx"
    mockup.save(mockup.build_mockup(BUSY), a)
    mockup.save(mockup.build_mockup(BUSY), b)
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as z:
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        xlsx = [n for n in z.namelist() if n.endswith(".xlsx")]
        assert xlsx
        for n in xlsx:
            with zipfile.ZipFile(io.BytesIO(z.read(n))) as x:
                assert {i.date_time for i in x.infolist()} == {(1980, 1, 1, 0, 0, 0)}
                assert "2000-01-01T00:00:00Z" in x.read("docProps/core.xml").decode()


def test_build_validates_its_input():
    with pytest.raises(ValueError, match="text"):
        mockup.build_mockup(_lay(_el("title", (0, 0, 0.5, 0.1), text="Q3 revenue")))


# --- render + command -----------------------------------------------------------------------------------------

@needs_soffice
def test_render_is_small_greyscale_960_and_batched(tmp_path, monkeypatch):
    paths = []
    for name, lay in (("busy", BUSY), ("plain", _lay(_el("title", (0.05, 0.05, 0.6, 0.1))))):
        paths.append(tmp_path / f"{name}.pptx")
        mockup.save(mockup.build_mockup(lay), paths[-1])
    calls, real = [], mockup.subprocess.run
    monkeypatch.setattr(mockup.subprocess, "run", lambda *a, **k: (calls.append(a), real(*a, **k))[1])
    pngs = mockup.render(paths)
    assert len(calls) == 1 and pngs == [p.with_suffix(".png") for p in paths]
    for png in pngs:
        img = Image.open(png)
        assert img.mode == "L" and img.size == (960, 540) and png.stat().st_size <= 30 * 1024
        assert img.getpixel((img.width - 2, img.height - 2)) == 255


@pytest.fixture
def deck_id(deck, lib):
    return extract.run(deck, lib, render=False)


@needs_soffice
def test_mockup_command_upgrades_snaps_and_writes_pptx_and_png(deck_id, lib):
    src = lib / "layouts" / deck_id
    src.mkdir(parents=True)
    slide = json.loads((lib / "work" / deck_id / "slide-02.json").read_text())
    r = slide["regions"][1]
    (src / "slide-02.B.json").write_text(json.dumps({"elements": [_el("image", (0, 0, 0.1, 0.1), "rect", region_ids=[r["i"]])]}))
    (src / "slide-01.B.json").write_text(json.dumps({"version": 2, "elements": [_el("title", (0, 0, 0.5, 0.1))]}))
    (src / "slide-01.A.json").write_text(json.dumps({"elements": [_el("title", (0, 0, 0.5, 0.1))]}))
    main(["mockup", deck_id, "--library", str(lib), "--variant", "B", "--slides", "02"])
    out = lib / "mockups" / deck_id
    assert sorted(p.name for p in out.iterdir()) == ["slide-02.B.png", "slide-02.B.pptx"]
    frame = Presentation(out / "slide-02.B.pptx").slides[0].shapes[0]
    assert frame.left == round(r["box"]["x"] * W) and frame.top == round(r["box"]["y"] * H)
    assert Image.open(out / "slide-02.B.png").size == (960, 540)
    (src / "slide-01.B.json").write_text(json.dumps({"version": 2, "elements": [_el("title", (0, 0, 0.1, 0.1), label="Hi")]}))
    with pytest.raises(ValueError, match="slide-01.B.json"):
        mockup.run(deck_id, lib, variant="B")
