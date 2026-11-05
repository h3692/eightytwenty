import io
import json
import random
import re
import shutil
import zipfile

import pytest
from PIL import Image
from pptx import Presentation
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.shapes import MSO_SHAPE, MSO_SHAPE_TYPE

from pipeline import extract, mockup
from pipeline.__main__ import main
from pipeline.tests.test_layout import EXAMPLES

HAS_SOFFICE = bool(shutil.which("soffice") or extract.SOFFICE_APP.exists())
needs_soffice = pytest.mark.skipif(not HAS_SOFFICE, reason="LibreOffice not installed")
W, H = 12192000, 6858000
FULL = ("cover", "section_divider", "closing")


def _lay(*components):
    return {"version": 3, "components": list(components)}


BUSY = _lay(
    EXAMPLES["tracker"], EXAMPLES["logo"],
    {"kind": "kpi_row", "box": [0, 0, 1, 0.25], "n": 4},
    {"kind": "chart_area", "box": [0, 0.25, 0.5, 0.5], "chart_type": "stacked_bar"},
    {"kind": "table", "box": [0.5, 0.25, 0.5, 0.5], "rows": 6, "cols": 5, "header_row": True, "harvey": True},
    {"kind": "steps", "box": [0, 0.75, 0.75, 0.125], "n": 5, "direction": "h"},
    {"kind": "image_area", "box": [0.75, 0.75, 0.25, 0.125], "variant": "map"},
    {"kind": "takeaway", "box": [0, 0.875, 1, 0.125]},
)
SLIDES = {kind: _lay(EXAMPLES[kind]) for kind in EXAMPLES} | {"busy": BUSY}


def _shapes(layout):
    return list(mockup.build_mockup_v3(layout).slides[0].shapes)


def _texts(shapes):
    out = []
    for s in shapes:
        if s.has_text_frame:
            out += [r.text for p in s.text_frame.paragraphs for r in p.runs]
        elif s.has_table:
            out += [r.text for row in s.table.rows for c in row.cells for p in c.text_frame.paragraphs for r in p.runs]
    return out


def _fill(shape):
    return str(shape.fill.fore_color.rgb) if shape.fill.type == 1 else None


# --- chrome: header, logo, tracker ----------------------------------------------------------------------------

@pytest.mark.parametrize("kind", EXAMPLES)
def test_header_is_implied_except_on_full_slide_kinds(kind):
    texts = _texts(_shapes(SLIDES[kind]))
    if kind in FULL:
        assert "Slide Title Here" not in texts
    else:
        assert texts[:2] == ["Slide Title Here", "Subtitle text here"]


def test_header_sits_top_left_and_logo_top_right():
    shapes = _shapes(_lay(EXAMPLES["logo"], EXAMPLES["quote"]))
    title = next(s for s in shapes if _texts([s]) == ["Slide Title Here"])
    logo = next(s for s in shapes if _texts([s]) == ["Logo"])
    assert title.left < W * 0.1 and title.top < H * 0.1
    assert logo.left + logo.width > W * 0.9 and logo.top < H * 0.15
    assert "Logo" not in _texts(_shapes(_lay(EXAMPLES["quote"])))


@pytest.mark.parametrize("n, active", [(2, 1), (4, 2), (8, 8)])
def test_tracker_draws_n_pills_along_the_bottom_with_the_active_one_dark(n, active):
    pills = [s for s in _shapes(_lay({"kind": "tracker", "n": n, "active": active})) if s.top > H * 0.85]
    assert len(pills) == n
    assert [_texts([p])[0] for p in pills] == [s for s in mockup.SECTIONS if s in mockup.TRACKER_PICKS[:n]]
    assert [_fill(p) for p in pills] == ["F3F4F6" if k != active - 1 else "2B2F36" for k in range(n)]
    assert [p.left for p in pills] == sorted(p.left for p in pills)


def test_sections_are_generic_and_enough():
    assert len(mockup.SECTIONS) >= 8 and set(mockup.TRACKER_PICKS) <= set(mockup.SECTIONS)


# --- components -----------------------------------------------------------------------------------------------

@pytest.mark.parametrize("kind", EXAMPLES)
def test_each_kind_draws_only_vocabulary(kind):
    shapes = _shapes(SLIDES[kind])
    assert shapes
    assert set(_texts(shapes)) <= mockup.VOCAB
    assert all(r.font.name == mockup.FONT for s in shapes if s.has_text_frame
               for p in s.text_frame.paragraphs for r in p.runs)


def test_components_stay_inside_their_box():
    shapes = _shapes(_lay({"kind": "card_row", "box": [0.5, 0.25, 0.5, 0.5], "n": 3, "header_strip": True, "icon": True}))
    body = [s for s in shapes if s.top > H * 0.15 and s.top < H * 0.9]
    left, right = min(s.left for s in body), max(s.left + s.width for s in body)
    top, bottom = min(s.top for s in body), max(s.top + s.height for s in body)
    area_l, area_t, area_w, area_h = (round(v * 914400) for v in mockup.AREA)
    assert left >= area_l + area_w * 0.5 and right <= area_l + area_w + 1
    assert top >= area_t + area_h * 0.25 and bottom <= area_t + area_h * 0.75 + 1


def test_numbered_steps_and_card_counts():
    texts = _texts(_shapes(_lay({**EXAMPLES["steps"], "n": 6, "direction": "v"})))
    assert [t for t in texts if t.isdigit()] == ["1", "2", "3", "4", "5", "6"]
    assert texts.count("Step Header") == 6
    assert _texts(_shapes(_lay({**EXAMPLES["card_row"], "n": 5}))).count("Header here") == 5
    assert _texts(_shapes(_lay({**EXAMPLES["kpi_row"], "n": 6}))).count("Text here") == 6
    assert _texts(_shapes(_lay({**EXAMPLES["roadmap"], "phases": 5}))).count("Phase Header") == 5


def test_text_lines_and_bullets():
    shape = next(s for s in _shapes(_lay({**EXAMPLES["text"], "lines": 5})) if _texts([s])[:1] == ["Text here"])
    paras = shape.text_frame.paragraphs
    assert len(paras) == 5 and all(p._pPr.find(f"{{{A}}}buChar") is not None for p in paras)
    shape = next(s for s in _shapes(_lay({**EXAMPLES["text"], "bullets": False})) if _texts([s])[:1] == ["Text here"])
    assert all(p._pPr is None or p._pPr.find(f"{{{A}}}buChar") is None for p in shape.text_frame.paragraphs)


A = "http://schemas.openxmlformats.org/drawingml/2006/main"


def test_tables_are_real_and_harvey_balls_are_drawn():
    shapes = _shapes(_lay({**EXAMPLES["table"], "rows": 7, "cols": 4}))
    table = next(s for s in shapes if s.has_table).table
    assert (len(table.rows), len(table.columns)) == (7, 4)
    assert table.cell(0, 1).text == "Header here" and table.cell(3, 0).text == "Text here"
    assert table.cell(3, 2).text == ""  # Harvey ball cells
    balls = [s for s in shapes if s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and s.auto_shape_type == MSO_SHAPE.OVAL]
    assert len(balls) == 6 * 3
    plain = _shapes(_lay({**EXAMPLES["table"], "harvey": False, "header_row": False}))
    assert next(s for s in plain if s.has_table).table.cell(0, 1).text == "Text here"


def _dummies(seed, series, categories):
    rng = random.Random(seed)
    return [[rng.randint(10, 100) for _ in range(categories)] for _ in range(series)]


@pytest.mark.parametrize("chart_type, expected", [("bar", XL_CHART_TYPE.BAR_CLUSTERED), ("line", XL_CHART_TYPE.LINE),
                                                  ("donut", XL_CHART_TYPE.DOUGHNUT),
                                                  ("waterfall", XL_CHART_TYPE.COLUMN_STACKED),
                                                  ("scatter", XL_CHART_TYPE.XY_SCATTER)])
def test_charts_are_native_with_seeded_dummy_data(chart_type, expected):
    shapes = _shapes(_lay(EXAMPLES["quote"], {**EXAMPLES["chart_area"], "chart_type": chart_type}))
    chart = next(s for s in shapes if s.has_chart).chart
    assert chart.chart_type == expected and not chart.has_legend and not chart.has_title
    expected = _dummies(1, 2 if chart_type == "line" else 1, 5)  # seeded by component index, 5 categories
    if chart_type == "waterfall":  # invisible running-total base under the visible steps
        expected = [[sum(expected[0][:k]) for k in range(5)], expected[0]]
    assert [list(s.values) for s in chart.plots[0].series] == expected


def test_other_charts_are_a_placeholder_panel():
    shapes = _shapes(_lay({**EXAMPLES["chart_area"], "chart_type": "other"}))
    assert not any(s.has_chart for s in shapes) and "Chart here" in _texts(shapes)


@pytest.mark.parametrize("variant, label", [("photo", "Image here"), ("device", "Product mockup here"),
                                            ("map", "Map here"), ("icon", "Icon")])
def test_image_areas_name_their_variant(variant, label):
    assert label in _texts(_shapes(_lay({**EXAMPLES["image_area"], "variant": variant})))


def test_section_divider_shows_its_number():
    texts = _texts(_shapes(_lay({"kind": "section_divider", "number": 3})))
    assert "03" in texts and "Section overview text here" in texts


def test_shapes_carry_no_theme_style():
    slide = mockup.build_mockup_v3(BUSY).slides[0]
    assert slide._element.findall(".//{http://schemas.openxmlformats.org/presentationml/2006/main}style") == []


def test_build_validates_its_input():
    with pytest.raises(ValueError, match="text"):
        mockup.build_mockup_v3(_lay({**EXAMPLES["quote"], "text": "Q3 revenue"}))


# --- whitelist, anonymity, determinism ------------------------------------------------------------------------

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


@pytest.mark.parametrize("name", SLIDES)
def test_saved_pptx_holds_only_placeholder_words_no_images_and_no_author(tmp_path, name):
    path = tmp_path / "m.pptx"
    mockup.save(mockup.build_mockup_v3(SLIDES[name]), path)
    blank = io.BytesIO()
    Presentation().save(blank)
    template_runs = set(_all_text(blank.getvalue())[0])  # master/layout boilerplate shipped with python-pptx
    runs, cached = _all_text(path.read_bytes())
    assert set(runs) - template_runs <= mockup.VOCAB
    assert all(re.fullmatch(r"-?\d+(\.\d+)?", v) for v in cached)  # chart caches: numbers only
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        types = z.read("[Content_Types].xml").decode()
    assert not [n for n in names if re.search(r"\.(jpe?g|png|gif|bmp|tiff?|emf|wmf|svg)$", n, re.I)]
    assert "image/" not in types
    props = Presentation(path).core_properties
    assert (props.author, props.last_modified_by, props.title, props.comments) == ("", "", "", "")
    assert props.created == props.modified == mockup.FIXED_TIME


def test_vocabulary_is_placeholder_copy_only():
    words = set(" ".join(mockup.VOCAB).replace(":", " ").split())
    assert words <= {"Slide", "Title", "Here", "here", "Subtitle", "text", "Logo", "Header", "Text", "XX%", "$X.XM",
                     "Chart", "Image", "Product", "mockup", "Map", "Icon", "Step", "Phase", "Key", "takeaway",
                     "Section", "overview", "Deck", "Thank", "You", "Before", "After", "QX", "Year", "X",
                     "Milestones", "Name", "“Text", "here”", *" ".join(mockup.SECTIONS).split()} | \
        {str(k) for k in range(1, 9)} | {f"{k:02}" for k in range(1, 10)}


def test_saved_mockups_are_byte_identical(tmp_path):
    a, b = tmp_path / "a.pptx", tmp_path / "b.pptx"
    mockup.save(mockup.build_mockup_v3(BUSY), a)
    mockup.save(mockup.build_mockup_v3(BUSY), b)
    assert a.read_bytes() == b.read_bytes()
    with zipfile.ZipFile(a) as z:
        assert {i.date_time for i in z.infolist()} == {(1980, 1, 1, 0, 0, 0)}
        xlsx = [n for n in z.namelist() if n.endswith(".xlsx")]
        assert xlsx
        for n in xlsx:
            with zipfile.ZipFile(io.BytesIO(z.read(n))) as x:
                assert {i.date_time for i in x.infolist()} == {(1980, 1, 1, 0, 0, 0)}
                assert "2000-01-01T00:00:00Z" in x.read("docProps/core.xml").decode()


# --- render + command -----------------------------------------------------------------------------------------

@needs_soffice
def test_every_kind_renders_small_greyscale_960_in_one_batch(tmp_path, monkeypatch):
    paths = []
    for name, lay in SLIDES.items():
        paths.append(tmp_path / f"{name}.pptx")
        mockup.save(mockup.build_mockup_v3(lay), paths[-1])
    calls, real = [], mockup.subprocess.run
    monkeypatch.setattr(mockup.subprocess, "run", lambda *a, **k: (calls.append(a), real(*a, **k))[1])
    pngs = mockup.render(paths)
    assert len(calls) == 1 and pngs == [p.with_suffix(".png") for p in paths]
    for png in pngs:
        img = Image.open(png)
        assert img.mode == "L" and img.size == (960, 540) and png.stat().st_size <= 30 * 1024, png.name


@pytest.fixture
def deck_id(deck, lib):
    return extract.run(deck, lib, render=False)


@needs_soffice
def test_mockup_command_writes_pptx_and_png_from_v3_layouts(deck_id, lib):
    src = lib / "layouts" / deck_id
    src.mkdir(parents=True)
    (src / "slide-02.v3.json").write_text(json.dumps(BUSY))
    (src / "slide-01.v3.json").write_text(json.dumps(_lay(EXAMPLES["cover"])))
    (src / "slide-01.final.json").write_text(json.dumps({"version": 2, "elements": []}))  # old layouts are ignored
    main(["mockup", deck_id, "--library", str(lib), "--slides", "02"])
    out = lib / "mockups" / deck_id
    assert sorted(p.name for p in out.iterdir()) == ["slide-02.png", "slide-02.pptx"]
    assert Image.open(out / "slide-02.png").size == (960, 540)
    assert "Slide Title Here" in _texts(Presentation(out / "slide-02.pptx").slides[0].shapes)
    (src / "slide-01.v3.json").write_text(json.dumps(_lay({**EXAMPLES["quote"], "label": "Hi"})))
    with pytest.raises(ValueError, match="slide-01.v3.json"):
        mockup.run(deck_id, lib)
