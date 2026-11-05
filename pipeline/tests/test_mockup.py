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
B, FULL_BOX = [0, 0, 0.5, 0.5], [0, 0, 1, 1]
MAXED = {  # every count at its upper limit, on the whole content area
    "table_check": {**EXAMPLES["table"], "box": FULL_BOX, "rows": 12, "cols": 12, "harvey": False, "marks": "check",
                    "highlight_col": 12},
    "timeline_24": {**EXAMPLES["timeline"], "box": FULL_BOX, "workstreams": 10, "periods": 24, "groups": 6},
    "kpi_square_v": {**EXAMPLES["kpi_row"], "box": FULL_BOX, "n": 6, "tile": "square"},
    "card_stack_8": {**EXAMPLES["card_stack"], "box": FULL_BOX, "n": 8},
    "swimlane_max": {**EXAMPLES["swimlane"], "box": FULL_BOX, "lanes": 6, "stages": 8},
    "journey_8": {**EXAMPLES["journey"], "box": FULL_BOX, "n": 8},
    "flow_10": {**EXAMPLES["flow_diagram"], "box": FULL_BOX, "n": 10},
    "laptops_6": {**EXAMPLES["device_row"], "box": FULL_BOX, "n": 6, "device": "laptop"},
    "gauges_v_6": {**EXAMPLES["gauge_row"], "box": FULL_BOX, "n": 6, "direction": "v"},
    "network_12": {**EXAMPLES["network"], "box": FULL_BOX, "n": 12},
    "map_8": {**EXAMPLES["map_callouts"], "box": FULL_BOX, "n": 8},
    "bar_list_12": {**EXAMPLES["bar_list"], "box": FULL_BOX, "n": 12, "groups": 4},
    "circles_4": {**EXAMPLES["nested_circles"], "box": FULL_BOX, "n": 4, "arrangement": "concentric"},
    "link_list_12": {**EXAMPLES["link_list"], "box": FULL_BOX, "n": 12, "cols": 3},
}
NEW_KINDS = ("card_stack", "swimlane", "journey", "flow_diagram", "device_row", "stage_strip", "gauge_row", "network",
             "map_callouts", "bar_list")
NEW_BUSY = _lay(*(dict(EXAMPLES[k], box=[(i % 2) / 2, (i // 2) / 4, 0.5, 0.25]) for i, k in enumerate(NEW_KINDS[:8])))
RIBBON = _lay(*BUSY["components"][:7], {"kind": "impact_overlay", "position": "bottom"})  # BUSY shaded, 8 in all
SLIDES = {kind: _lay(EXAMPLES[kind]) for kind in EXAMPLES} | {"busy": BUSY, "new_busy": NEW_BUSY, "ribbon": RIBBON} | \
    {name: _lay(c) for name, c in MAXED.items()}


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


@pytest.mark.parametrize("lines, drawn", [(2, 2), (4, 4), (5, 4), (8, 4)])
def test_text_blocks_draw_at_most_four_lines(lines, drawn):
    for bullets in (True, False):
        box = {**EXAMPLES["text"], "box": [0, 0, 0.5, 1], "lines": lines, "bullets": bullets}
        assert _texts(_shapes(_lay(box))).count("Text here") == drawn


def test_text_lines_and_bullets():
    shape = next(s for s in _shapes(_lay({**EXAMPLES["text"], "lines": 3})) if _texts([s])[:1] == ["Text here"])
    paras = shape.text_frame.paragraphs
    assert len(paras) == 3 and all(p._pPr.find(f"{{{A}}}buChar") is not None for p in paras)
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
    plain = _shapes(_lay({**EXAMPLES["table"], "harvey": False, "marks": "none", "header_row": False}))
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


def _lines(shapes):
    """Straight connectors, split into plain lines and arrows (a tail-end arrowhead)."""
    lines = [s for s in shapes if s.shape_type == MSO_SHAPE_TYPE.LINE]
    arrows = [s for s in lines if s._element.find(f".//{{{A}}}tailEnd") is not None]
    return len(lines) - len(arrows), len(arrows)


@pytest.mark.parametrize("n", [3, 5, 8])
@pytest.mark.parametrize("connectors, cycle", [(False, False), (True, False), (False, True), (True, True)])
def test_hub_draws_a_centre_and_n_satellites_with_optional_spokes_and_cycle_arrows(n, connectors, cycle):
    box = [0, 0, 1, 0.75]
    shapes = _shapes(_lay({"kind": "hub", "box": box, "n": n, "connectors": connectors, "cycle": cycle}))
    body = [s for s in shapes if s.top > H * 0.2]
    assert _texts(body).count("Header here") == n + 1
    centre = next(s for s in body if s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and s.auto_shape_type == MSO_SHAPE.OVAL)
    assert _fill(centre) == "2B2F36"
    assert _lines(body) == (n * connectors, n * cycle)
    area_l, area_t, area_w, area_h = (round(v * 914400) for v in mockup.AREA)
    assert all(s.left >= area_l - 1 and s.left + s.width <= area_l + area_w + 1 and s.top >= area_t - 1
               and s.top + s.height <= area_t + area_h * 0.75 + 1 for s in body)
    nodes = [s for s in body if s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE]
    for a in nodes:  # satellites never sit on each other or on the centre
        for b in nodes:
            if a is not b:
                assert (a.left + a.width <= b.left or b.left + b.width <= a.left or a.top + a.height <= b.top
                        or b.top + b.height <= a.top), (a.name, b.name)


# --- Z1b kinds -------------------------------------------------------------------------------------------------

def _auto(shapes, *types):
    return [s for s in shapes if s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE and s.auto_shape_type in types]


def _freeforms(shapes):
    return [s for s in shapes if s.shape_type == MSO_SHAPE_TYPE.FREEFORM]


def _body(layout):
    return [s for s in _shapes(layout) if s.top > H * 0.2]


@pytest.mark.parametrize("kind", NEW_KINDS + ("kpi_row", "table", "timeline", "nested_circles", "link_list"))
def test_new_and_extended_kinds_stay_inside_their_box(kind):
    box = [0.5, 0.25, 0.5, 0.5]
    for c in [EXAMPLES[kind]] + [m for m in MAXED.values() if m["kind"] == kind]:
        x, y, w, h = (round(v * 914400) for v in mockup._place(box))
        for s in _body(_lay({**c, "box": box})):
            assert s.left >= x - 2 and s.top >= y - 2, s.name
            assert s.left + s.width <= x + w + 2 and s.top + s.height <= y + h + 2, s.name


@pytest.mark.parametrize("n", [2, 5, 8])
@pytest.mark.parametrize("strip, icon", [(False, False), (True, True)])
def test_card_stack_stacks_n_cards_vertically(n, strip, icon):
    body = _body(_lay({"kind": "card_stack", "box": FULL_BOX, "n": n, "header_strip": strip, "icon": icon}))
    heads = [s for s in body if _texts([s]) == ["Header here"]]
    assert len(heads) == n and len({h.left for h in heads}) == 1
    assert [h.top for h in heads] == sorted({h.top for h in heads})
    assert _texts(body).count("Icon") == n * icon


@pytest.mark.parametrize("direction, tile", [("h", "round"), ("v", "round"), ("v", "square"), ("h", "square")])
def test_kpi_row_runs_horizontal_or_vertical_with_round_or_square_tiles(direction, tile):
    body = _body(_lay({"kind": "kpi_row", "box": FULL_BOX, "n": 4, "direction": direction, "tile": tile}))
    values = [s for s in body if _texts([s])[:1] in (["XX%"], ["$X.XM"])]
    assert len(values) == 4
    lead, other = ("left", "top") if direction == "h" else ("top", "left")
    assert len({getattr(v, lead) for v in values}) == 4 and len({getattr(v, other) for v in values}) == 1
    assert len(_auto(body, MSO_SHAPE.OVAL)) == 4 * (tile == "round")


def test_kpi_row_defaults_to_the_old_horizontal_square_tiles():
    old = _shapes(_lay({"kind": "kpi_row", "box": B, "n": 3}))
    assert [(s.left, s.top, s.width, s.height) for s in old] == [
        (s.left, s.top, s.width, s.height) for s in _shapes(_lay({"kind": "kpi_row", "box": B, "n": 3,
                                                                   "direction": "h", "tile": "square"}))]



def test_table_check_marks_and_highlighted_column():
    c = {"kind": "table", "box": FULL_BOX, "rows": 5, "cols": 4, "header_row": True, "marks": "check",
         "highlight_col": 2}
    shapes = _shapes(_lay(c))
    table = next(s for s in shapes if s.has_table).table
    assert table.cell(2, 1).text == "" and table.cell(0, 1).text == "Header here"
    ticks, crosses = _freeforms(shapes), _auto(shapes, MSO_SHAPE.MATH_MULTIPLY)
    assert len(ticks) + len(crosses) == 4 * 3 and ticks and crosses
    assert not _auto(shapes, MSO_SHAPE.OVAL)
    fills = [[str(table.cell(r, k).fill.fore_color.rgb) for k in range(4)] for r in range(5)]
    assert all(row[1] == "E2E5E9" and "E2E5E9" not in row[2:] for row in fills[1:])
    assert fills[0][1] == "2B2F36"


def test_table_marks_harvey_is_the_old_harvey_flag_and_twelve_columns_fit():
    old = _shapes(_lay({"kind": "table", "box": B, "rows": 5, "cols": 4, "header_row": True, "harvey": True}))
    new = _shapes(_lay({"kind": "table", "box": B, "rows": 5, "cols": 4, "header_row": True, "marks": "harvey"}))
    assert len(_auto(new, MSO_SHAPE.OVAL)) == len(_auto(old, MSO_SHAPE.OVAL)) == 4 * 3
    wide = next(s for s in _shapes(_lay(MAXED["table_check"])) if s.has_table).table
    assert len(wide.columns) == 12


def test_timeline_takes_24_periods_rounded_bars_and_group_pills():
    body = _body(_lay({"kind": "timeline", "box": FULL_BOX, "workstreams": 3, "periods": 24, "rounded": True,
                       "groups": 3}))
    texts = _texts(body)
    assert texts.count("QX") == 24 and texts.count("Year X") == 3
    bars = [s for s in _auto(body, MSO_SHAPE.ROUNDED_RECTANGLE) if not _texts([s])]
    assert len(bars) == 3
    plain = _body(_lay({"kind": "timeline", "box": FULL_BOX, "workstreams": 3, "periods": 8}))
    assert "Year X" not in _texts(plain) and not _auto(plain, MSO_SHAPE.ROUNDED_RECTANGLE)


@pytest.mark.parametrize("curve", [False, True])
def test_swimlane_draws_lanes_by_stages_with_an_optional_curve(curve):
    body = _body(_lay({"kind": "swimlane", "box": FULL_BOX, "lanes": 3, "stages": 5, "curve": curve}))
    texts = _texts(body)
    assert texts.count("Text here") == 15 and texts.count("Header here") == 3 + 5
    assert len(_freeforms(body)) == curve and len(_auto(body, MSO_SHAPE.OVAL)) == 5 * curve


@pytest.mark.parametrize("n", [3, 6, 8])
@pytest.mark.parametrize("curve, persona", [(False, False), (True, True)])
def test_journey_alternates_milestones_above_and_below_the_axis(n, curve, persona):
    box = [0, 0, 1, 0.75]
    body = _body(_lay({"kind": "journey", "box": box, "n": n, "curve": curve, "persona": persona}))
    texts = _texts(body)
    assert [t for t in texts if t.isdigit()] == [str(k) for k in range(1, n + 1)]
    assert ("Name here" in texts) == persona
    assert len(_freeforms(body)) == curve
    x, y, w, h = mockup._place(box)
    axis = (y + h / 2) * 914400
    heads = sorted((s for s in body if _texts([s]) == ["Header here"]), key=lambda s: s.left)
    assert len(heads) == n
    assert all((s.top + s.height / 2 < axis) == (k % 2 == 0) for k, s in enumerate(heads))


def _no_overlap(nodes):
    for a in nodes:
        for b in nodes:
            if a is not b:
                assert (a.left + a.width <= b.left or b.left + b.width <= a.left or a.top + a.height <= b.top
                        or b.top + b.height <= a.top), (a.name, b.name)


@pytest.mark.parametrize("n", [3, 7, 10])
@pytest.mark.parametrize("arrangement, icon", [("row", False), ("grid", True)])
def test_flow_diagram_links_n_nodes_with_arrows(n, arrangement, icon):
    body = _body(_lay({"kind": "flow_diagram", "box": FULL_BOX, "n": n, "arrangement": arrangement, "icon": icon}))
    nodes = [s for s in body if _texts([s]) == ["Header here"]]
    assert len(nodes) == n and _lines(body) == (0, n - 1)
    assert (len({s.top for s in nodes}) > 1) == (arrangement == "grid")
    assert _texts(body).count("Icon") == n * icon
    _no_overlap(nodes)


@pytest.mark.parametrize("device", ["phone", "laptop"])
def test_device_row_draws_n_screens(device):
    body = _body(_lay({"kind": "device_row", "box": FULL_BOX, "n": 4, "device": device}))
    assert _texts(body).count("Image here") == 4
    assert len(_auto(body, MSO_SHAPE.TRAPEZOID)) == 4 * (device == "laptop")


@pytest.mark.parametrize("n, active", [(2, 1), (4, 3), (6, 6)])
def test_stage_strip_draws_chevrons_with_the_active_one_dark(n, active):
    body = _body(_lay({"kind": "stage_strip", "box": [0, 0, 1, 0.125], "n": n, "active": active}))
    chevrons = sorted(_auto(body, MSO_SHAPE.PENTAGON, MSO_SHAPE.CHEVRON), key=lambda s: s.left)
    assert len(chevrons) == n and len({s.top for s in chevrons}) == 1
    assert [_fill(s) for s in chevrons] == ["F3F4F6" if k != active - 1 else "2B2F36" for k in range(n)]


def test_stage_strip_sits_alongside_the_tracker():
    layout = _lay(EXAMPLES["tracker"], {"kind": "stage_strip", "box": [0, 0, 1, 0.125], "n": 4, "active": 2})
    assert len(_auto(_shapes(layout), MSO_SHAPE.ROUNDED_RECTANGLE)) == 4  # tracker pills untouched


@pytest.mark.parametrize("direction", ["h", "v"])
def test_gauge_row_draws_n_donut_gauges(direction):
    body = _body(_lay({"kind": "gauge_row", "box": FULL_BOX, "n": 5, "direction": direction}))
    arcs = _auto(body, MSO_SHAPE.BLOCK_ARC)
    assert len(arcs) == 5 and _texts(body).count("XX%") == 5
    assert len({(s.top if direction == "h" else s.left) for s in arcs}) == 1


@pytest.mark.parametrize("n", [3, 7, 12])
def test_network_nodes_are_connected_and_seeded(n):
    layout = _lay({"kind": "network", "box": FULL_BOX, "n": n})
    body = _body(layout)
    nodes = [s for s in body if s.shape_type == MSO_SHAPE_TYPE.AUTO_SHAPE]
    lines = [s for s in body if s.shape_type == MSO_SHAPE_TYPE.LINE]
    assert len(nodes) == n and len(lines) >= n - 1
    _no_overlap(nodes)
    centres = [(s.left + s.width / 2, s.top + s.height / 2) for s in nodes]

    def node(px, py):
        return min(range(n), key=lambda k: abs(centres[k][0] - px) + abs(centres[k][1] - py))

    seen, todo = {0}, [0]
    edges = [(node(ln.begin_x, ln.begin_y), node(ln.end_x, ln.end_y)) for ln in lines]
    while todo:
        k = todo.pop()
        for a, b in edges:
            for u, v in ((a, b), (b, a)):
                if u == k and v not in seen:
                    seen.add(v)
                    todo.append(v)
    assert seen == set(range(n))
    assert [(s.left, s.top) for s in _body(layout)] == [(s.left, s.top) for s in body]


@pytest.mark.parametrize("n", [1, 4, 8])
def test_map_callouts_number_each_marker_and_its_label_with_a_leader_line(n):
    body = _body(_lay({"kind": "map_callouts", "box": FULL_BOX, "n": n}))
    texts = _texts(body)
    assert "Map here" in texts
    assert sorted(t for t in texts if t.isdigit()) == sorted(str(k) for k in range(1, n + 1) for _ in range(2))
    assert _lines(body) == (n, 0)


@pytest.mark.parametrize("groups", [1, 2, 4])
def test_bar_list_draws_n_rounded_bars_under_optional_group_headers(groups):
    body = _body(_lay({"kind": "bar_list", "box": FULL_BOX, "n": 8, "groups": groups}))
    texts = _texts(body)
    heads = groups if groups > 1 else 0
    assert texts.count("Text here") == 8 and texts.count("$X.XM") == 8 + heads
    assert texts.count("Header here") == heads
    assert len(_auto(body, MSO_SHAPE.ROUNDED_RECTANGLE)) == 8 + heads


def test_timeline_takes_ten_workstreams():
    texts = _texts(_body(_lay({"kind": "timeline", "box": FULL_BOX, "workstreams": 10, "periods": 6})))
    assert texts.count("Header here") == 10


@pytest.mark.parametrize("n", [2, 3, 4])
@pytest.mark.parametrize("arrangement", ["nested", "concentric"])
def test_nested_circles_draw_n_shrinking_circles_each_with_a_header_and_a_share(n, arrangement):
    body = _body(_lay({"kind": "nested_circles", "box": FULL_BOX, "n": n, "arrangement": arrangement}))
    rings = _auto(body, MSO_SHAPE.OVAL)
    assert len(rings) == n and [r.width for r in rings] == sorted((r.width for r in rings), reverse=True)
    assert all(r.width == r.height for r in rings)
    centre = {round(r.left + r.width / 2, -3) for r in rings}
    middle, bottom = {round(r.top + r.height / 2, -3) for r in rings}, {round(r.top + r.height, -3) for r in rings}
    assert len(centre) == 1 and len(middle if arrangement == "concentric" else bottom) == 1
    texts = _texts(body)
    assert texts.count("Header here") == n and texts.count("XX%") == n


@pytest.mark.parametrize("n, cols", [(2, 1), (7, 2), (12, 3)])
@pytest.mark.parametrize("numbered", [True, False])
def test_link_list_draws_n_entries_down_its_columns_numbered_or_bulleted(n, cols, numbered):
    body = _body(_lay({"kind": "link_list", "box": FULL_BOX, "n": n, "cols": cols, "numbered": numbered}))
    heads = [s for s in body if _texts([s]) == ["Header here"]]
    assert len(heads) == n and len({h.left for h in heads}) == cols
    first = [h for h in heads if h.left == heads[0].left]
    assert len(first) == -(-n // cols) and [h.top for h in first] == sorted(h.top for h in first)
    digits = [t for t in _texts(body) if t.isdigit()]
    assert digits == ([str(k) for k in range(1, n + 1)] if numbered else [])
    assert len([o for o in _auto(body, MSO_SHAPE.OVAL) if not _texts([o])]) == n * (not numbered)  # bullet dots


def _alpha(shape):
    return [a.get("val") for a in shape._element.iter("{http://schemas.openxmlformats.org/drawingml/2006/main}alpha")]


@pytest.mark.parametrize("position, band", [("top", (0.18, 0.5)), ("middle", (0.35, 0.75)), ("bottom", (0.6, 0.98))])
def test_impact_overlay_shades_the_slide_and_draws_a_ribbon_over_what_precedes_it(position, band):
    shapes = _shapes(_lay(*BUSY["components"][:7], {"kind": "impact_overlay", "position": position}))
    parent = _shapes(_lay(*BUSY["components"][:7]))
    *under, shade, ribbon = shapes
    assert len(under) == len(parent)  # the parent's drawing, unchanged, below the overlay
    assert (shade.left, shade.top, shade.width, shade.height) == (0, 0, W, H) and not _texts([shade])
    assert _fill(shade) == "2B2F36" and _alpha(shade) == ["70000"]  # dark, 70% opaque
    assert _texts([ribbon]) == ["Key message here"] and _fill(ribbon) == "2B2F36" and _alpha(ribbon) == []
    assert ribbon.left == 0 and ribbon.width == W and ribbon.height < H * 0.35
    assert band[0] * H <= ribbon.top and ribbon.top + ribbon.height <= band[1] * H


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
                     "Milestones", "Name", "“Text", "here”", "message", *" ".join(mockup.SECTIONS).split()} | \
        {str(k) for k in range(1, 13)} | {f"{k:02}" for k in range(1, 10)}


def test_saved_mockups_are_byte_identical(tmp_path):
    a, b = tmp_path / "a.pptx", tmp_path / "b.pptx"
    for lay in (NEW_BUSY, RIBBON, *(_lay(c) for c in MAXED.values())):
        mockup.save(mockup.build_mockup_v3(lay), a)
        mockup.save(mockup.build_mockup_v3(lay), b)
        assert a.read_bytes() == b.read_bytes()
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
