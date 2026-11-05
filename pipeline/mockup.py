"""Mockups: a component layout (v3) drawn as a real PowerPoint slide in a clean greyscale wireframe style with
python-pptx, rendered to a greyscale PNG by LibreOffice.

Every word on the slide is fixed placeholder copy (VOCAB) and charts hold seeded dummy values only. A saved .pptx is
byte-identical for the same layout and doubles as an empty slide template.
"""
import datetime
import io
import json
import math
import random
import re
import shutil
import subprocess
import tempfile
import zipfile
from pathlib import Path

import pypdfium2 as pdfium
from pptx import Presentation
from pptx.chart.data import CategoryChartData, XyChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE, XL_MARKER_STYLE, XL_TICK_LABEL_POSITION, XL_TICK_MARK
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, MSO_AUTO_SIZE, PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.oxml import parse_xml
from pptx.oxml.ns import nsdecls, qn
from pptx.util import Emu, Pt

from pipeline import build, extract, layout as lay

W, H, IN = 12192000, 6858000, 914400  # 13.333 x 7.5 in, renders as a 960 x 540 pt PDF page
FONT = "Arial"  # on every Mac and Windows install, and LibreOffice renders it here
FIXED_TIME, ZIP_TIME = datetime.datetime(2000, 1, 1), (1980, 1, 1, 0, 0, 0)
LIGHT, MID, DARK, WHITE = 0xF3F4F6, 0xE2E5E9, 0x2B2F36, 0xFFFFFF
GREYS = (0x6B7280, 0x8A9099, 0xA9AFB8, 0xC9CDD3)  # secondary text -> hairline
AREA = (0.78, 1.86, 11.78, 4.66)  # content area in inches (x, y, w, h): below the header, above the tracker
GAP = 0.12  # in, between neighbouring components and repeated blocks
MAX_TEXT_LINES = 4  # a text block reads as text at any height; more placeholder lines only add noise
LEFT, MIDDLE, TOP, BOTTOM = PP_ALIGN.LEFT, MSO_ANCHOR.MIDDLE, MSO_ANCHOR.TOP, MSO_ANCHOR.BOTTOM
SECTIONS = ("Executive Summary", "Situation", "Problem Analysis", "Customer", "Competition", "Solution",
            "Implementation", "Financials", "Risks", "Appendix")  # deck order
TRACKER_PICKS = ("Executive Summary", "Problem Analysis", "Solution", "Implementation", "Financials", "Customer",
                 "Situation", "Risks")  # a tracker of n pills shows the first n of these, in deck order
CHARTS = {"bar": XL_CHART_TYPE.BAR_CLUSTERED, "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
          "stacked_bar": XL_CHART_TYPE.BAR_STACKED, "line": XL_CHART_TYPE.LINE, "pie": XL_CHART_TYPE.PIE,
          "donut": XL_CHART_TYPE.DOUGHNUT, "scatter": XL_CHART_TYPE.XY_SCATTER,
          "waterfall": XL_CHART_TYPE.COLUMN_STACKED, "area": XL_CHART_TYPE.AREA}  # waterfall: invisible base series
SERIES = (DARK, GREYS[2], GREYS[0], GREYS[3], GREYS[1], MID)  # chart series / slices
VALUES = ("XX%", "$X.XM")
VOCAB = {"Slide Title Here", "Subtitle text here", "Logo", "Header here", "Text here", *VALUES, "Chart here",
         "Image here", "Product mockup here", "Map here", "Icon", "Step Header", "Phase Header", "Key takeaway:",
         "Section Title Here", "Section overview text here", "Deck Title Here", "Thank You", "Before", "After", "QX",
         "Year X", "Milestones", "“Text here”", "Name here", *SECTIONS,
         *(str(k) for k in range(1, 13)), *(f"{k:02}" for k in range(1, 10))}


def build_mockup_v3(layout):
    """A one-slide 16:9 Presentation of a component layout (validated and grid-snapped here)."""
    comps = lay.validate(layout)["components"]
    prs = Presentation()
    prs.slide_width, prs.slide_height = W, H
    props = prs.core_properties
    props.author = props.last_modified_by = props.title = props.comments = ""  # the stock template names a person
    props.created = props.modified = FIXED_TIME
    props.revision = 1
    pkg = prs.part.package
    for rId, rel in list(pkg._rels.items()):  # the stock template's thumbnail is its only image
        if rel.reltype == RT.THUMBNAIL:
            pkg.drop_rel(rId)
    shapes = prs.slides.add_slide(prs.slide_layouts[6]).shapes
    if not any(c["kind"] in lay.FULL for c in comps):
        _header(shapes)
    for i in sorted(range(len(comps)), key=lambda i: comps[i]["kind"] not in lay.FULL):  # whole-slide kinds first
        c = comps[i]
        DRAW[c["kind"]](shapes, c, *(_place(c["box"]) if "box" in c else ()), random.Random(i))
    for style in shapes._spTree.findall(f".//{qn('p:style')}"):  # theme style: accent colours, a drop shadow
        style.getparent().remove(style)
    return prs


def _place(box):
    """A grid box of the content area in slide inches, inset by half a gap on every side that has a neighbour."""
    bx, by, bw, bh = box
    ax, ay, aw, ah = AREA
    g = GAP / 2
    x0, y0 = ax + bx * aw + g * (bx > 0), ay + by * ah + g * (by > 0)
    x1, y1 = ax + (bx + bw) * aw - g * (bx + bw < 0.999), ay + (by + bh) * ah - g * (by + bh < 0.999)
    return x0, y0, x1 - x0, y1 - y0


def _split(a, size, n, gap=GAP):
    """n equal slots along [a, a + size] with gaps between them: their starts, and the slot size."""
    s = (size - gap * (n - 1)) / n
    return [a + k * (s + gap) for k in range(n)], s


def _rgb(v):
    return RGBColor.from_string(f"{v:06X}")


def _add(shapes, x, y, w, h, fill=None, line=None, text=(), size=12, color=DARK, bold=False, align=PP_ALIGN.CENTER,
         anchor=MIDDLE, preset=MSO_SHAPE.RECTANGLE, dash=False, bullets=False, italic=False):
    """One autoshape at slide inches, optionally holding lines of placeholder text shrunk to fit."""
    w, h = max(w, 0.02), max(h, 0.02)
    s = shapes.add_shape(preset, *(Emu(round(v * IN)) for v in (x, y, w, h)))
    if fill is None:
        s.fill.background()
    else:
        s.fill.solid()
        s.fill.fore_color.rgb = _rgb(fill)
    if line is None:
        s.line.fill.background()
    else:
        s.line.color.rgb, s.line.width = _rgb(line), Pt(1)
        if dash:
            s.line.dash_style = MSO_LINE.DASH
    if preset == MSO_SHAPE.ROUNDED_RECTANGLE:
        s.adjustments[0] = 0.5  # pill ends
    lines = [text] if isinstance(text, str) else list(text)
    if not lines:
        return s
    tf = s.text_frame
    tf.word_wrap, tf.auto_size, tf.vertical_anchor = False, MSO_AUTO_SIZE.NONE, anchor
    tf.margin_left = tf.margin_right = Emu(round(0.06 * IN))
    tf.margin_top = tf.margin_bottom = Emu(round(0.02 * IN))
    indent = 0.2 if bullets else 0
    fit = min((h - 0.04) * 72 / (1.25 * len(lines)), (w - 0.12 - indent) * 72 / (0.6 * max(map(len, lines))))
    for k, t in enumerate(lines):
        p = tf.paragraphs[0] if k == 0 else tf.add_paragraph()
        p.alignment = align
        if bullets:
            pPr = p._p.get_or_add_pPr()
            pPr.set("marL", str(round(indent * IN)))
            pPr.set("indent", str(-round(indent * IN)))
            pPr.append(parse_xml(f'<a:buChar {nsdecls("a")} char="•"/>'))
        r = p.add_run()
        r.text = t
        f = r.font
        f.name, f.size, f.bold, f.italic = FONT, Pt(max(6, int(min(size, fit)))), bold, italic
        f.color.rgb = _rgb(color)
    return s


def _line(shapes, ax, ay, bx, by, arrow=False):
    """A straight connector at slide inches; arrow = a triangle head at the end."""
    ln = shapes.add_connector(MSO_CONNECTOR.STRAIGHT, *(Emu(round(v * IN)) for v in (ax, ay, bx, by)))
    ln.line.color.rgb, ln.line.width = _rgb(GREYS[1] if arrow else GREYS[2]), Pt(1.25 if arrow else 1)
    if arrow:
        ln.line._get_or_add_ln().append(parse_xml(f'<a:tailEnd {nsdecls("a")} type="triangle"/>'))
    return ln


def _path(shapes, pts, color=DARK, width=1.5, smooth=False):
    """An open line through points at slide inches (a tick, a curve); smooth eases between the points."""
    if smooth:
        pts = [(ax + (bx - ax) * t / 8, ay + (by - ay) * (1 - math.cos(math.pi * t / 8)) / 2)
               for (ax, ay), (bx, by) in zip(pts, pts[1:]) for t in range(8)] + pts[-1:]
    ff = shapes.build_freeform(*(Emu(round(v * IN)) for v in pts[0]))
    ff.add_line_segments([(round(px * IN), round(py * IN)) for px, py in pts[1:]], close=False)
    s = ff.convert_to_shape()
    s.fill.background()
    s.line.color.rgb, s.line.width = _rgb(color), Pt(width)
    return s


# --- slide chrome ---------------------------------------------------------------------------------------------

def _header(shapes):
    _add(shapes, 0.46, 0.22, 0.08, 0.74, DARK)
    _add(shapes, 0.65, 0.14, 9.5, 0.44, text="Slide Title Here", size=24, bold=True, align=LEFT)
    _add(shapes, 0.65, 0.56, 9.5, 0.4, text="Subtitle text here", size=17, color=GREYS[0], align=LEFT)


def _logo(shapes, c, rng):
    _add(shapes, 11.31, 0.56, 1.24, 0.49, LIGHT, text="Logo", color=GREYS[0])


def _tracker(shapes, c, rng):
    names = [s for s in SECTIONS if s in TRACKER_PICKS[:c["n"]]]
    xs, pw = _split(0.78, 11.78, c["n"], 0.08)
    for k, (px, name) in enumerate(zip(xs, names)):
        on = k == c["active"] - 1
        _add(shapes, px, 6.82, pw, 0.32, DARK if on else LIGHT, text=name, color=WHITE if on else GREYS[0],
             preset=MSO_SHAPE.ROUNDED_RECTANGLE)


# --- content components (x, y, w, h in slide inches) ----------------------------------------------------------

def _text(shapes, c, x, y, w, h, rng):
    _add(shapes, x, y, w, h, text=["Text here"] * min(c["lines"], MAX_TEXT_LINES), size=14, align=LEFT, anchor=TOP,
         bullets=c.get("bullets", False))


def _kpi_row(shapes, c, x, y, w, h, rng):
    rnd = c.get("tile") == "round"
    if c.get("direction") == "v":  # tiles down the left, captions beside them
        ys, th = _split(y, h, c["n"])
        d = min(th, w * 0.4) if rnd else min(2.2, w * 0.4)
        dh = d if rnd else th
        for k, ty in enumerate(ys):
            _add(shapes, x, ty + (th - dh) / 2, d, dh, LIGHT, text=VALUES[k % 2], size=28, bold=True,
                 preset=MSO_SHAPE.OVAL if rnd else MSO_SHAPE.RECTANGLE)
            _add(shapes, x + d + 0.15, ty, w - d - 0.15, th, text="Text here", size=14, color=GREYS[0], align=LEFT)
        return
    xs, tw = _split(x, w, c["n"])
    if rnd:
        d = min(tw, h * 0.65)
        for k, tx in enumerate(xs):
            _add(shapes, tx + (tw - d) / 2, y, d, d, LIGHT, text=VALUES[k % 2], size=28, bold=True,
                 preset=MSO_SHAPE.OVAL)
            _add(shapes, tx, y + d + 0.06, tw, h - d - 0.06, text="Text here", color=GREYS[0], anchor=TOP)
        return
    for k, tx in enumerate(xs):
        _add(shapes, tx, y, tw, h, LIGHT)
        _add(shapes, tx + 0.1, y, tw - 0.2, h * 0.6, text=VALUES[k % 2], size=28, bold=True, align=LEFT, anchor=BOTTOM)
        _add(shapes, tx + 0.1, y + h * 0.6, tw - 0.2, h * 0.4, text="Text here", color=GREYS[0], align=LEFT,
             anchor=TOP)


def _card_row(shapes, c, x, y, w, h, rng):
    xs, cw = _split(x, w, c["n"])
    sh = min(0.43, h * 0.2) if c.get("header_strip") else 0
    for cx in xs:
        top = y
        if sh:
            _add(shapes, cx, y, cw, sh, MID, text="Header here", size=14, bold=True)
            top += sh + 0.08
        _add(shapes, cx, top, cw, y + h - top, LIGHT)
        top += 0.1
        if c.get("icon"):
            d = min(0.5, (y + h - top) * 0.3)
            _add(shapes, cx + (cw - d) / 2, top, d, d, WHITE, GREYS[3], "Icon", 10, GREYS[0])
            top += d + 0.08
        if not sh:
            hh = min(0.32, (y + h - top) * 0.3)
            _add(shapes, cx + 0.1, top, cw - 0.2, hh, text="Header here", size=14, bold=True, align=LEFT)
            top += hh
        _add(shapes, cx + 0.1, top, cw - 0.2, y + h - top - 0.08, text=["Text here"] * 3, align=LEFT, anchor=TOP,
             bullets=True)


def _label_rows(shapes, c, x, y, w, h, rng):
    lw = min(2.08, w * 0.22)
    ys, rh = _split(y, h, c["rows"], 0.1)
    xs, cw = _split(x + lw + 0.1, w - lw - 0.1, c["cols"], 0.1)
    for ry in ys:
        _add(shapes, x, ry, lw, rh, DARK, text="Header here", size=13, color=WHITE, bold=True)
        for cx in xs:
            _add(shapes, cx, ry, cw, rh, LIGHT, text="Text here", size=13)


def _table(shapes, c, x, y, w, h, rng):
    rows, cols, head = c["rows"], c["cols"], c.get("header_row", False)
    marks = c.get("marks", "harvey" if c.get("harvey") else "none")
    hl = c.get("highlight_col", 0) - 1  # the emphasised column, -1 for none
    table = shapes.add_table(rows, cols, *(Emu(round(v * IN)) for v in (x, y, w, h))).table
    table.first_row, table.horz_banding = head, False
    rh, cw = h / rows, w / cols
    size = Pt(max(6, int(min(12, rh * 72 * 0.45, (cw * 72 - 8) / (0.6 * 11)))))
    rule = f'<a:lnB {nsdecls("a")} w="9525"><a:solidFill><a:srgbClr val="{GREYS[3]:06X}"/></a:solidFill></a:lnB>'
    for r, row in enumerate(table.rows):
        for k, cell in enumerate(row.cells):
            top = head and r == 0
            cell.fill.solid()
            cell.fill.fore_color.rgb = _rgb(DARK if top else MID if k == hl else LIGHT if k == 0 else WHITE)
            cell.margin_left = cell.margin_right = Emu(round(0.06 * IN))
            cell.margin_top = cell.margin_bottom = 0
            cell.vertical_anchor = MIDDLE
            cell._tc.get_or_add_tcPr().insert(0, parse_xml(rule))  # borders precede the cell fill
            p = cell.text_frame.paragraphs[0]
            if marks != "none" and not top and k > 0:
                p._p.get_or_add_endParaRPr().set("sz", "100")  # the mark is drawn over the empty cell
                continue
            p.alignment = LEFT if k == 0 else PP_ALIGN.CENTER
            run = p.add_run()
            run.text = "Header here" if top else "Text here"
            run.font.name, run.font.size, run.font.bold = FONT, size, top
            run.font.color.rgb = _rgb(WHITE if top else DARK)
    if marks == "check":  # mostly ticks, some crosses
        d = min(rh * 0.6, cw * 0.6, 0.22)
        for r in range(int(head), rows):
            for k in range(1, cols):
                bx, by = x + (k + 0.5) * cw - d / 2, y + (r + 0.5) * rh - d / 2
                if rng.random() < 0.7:
                    _path(shapes, [(bx, by + d * 0.55), (bx + d * 0.38, by + d * 0.9), (bx + d, by + d * 0.1)],
                          width=2)
                else:
                    _add(shapes, bx, by, d, d, GREYS[1], preset=MSO_SHAPE.MATH_MULTIPLY)
    if marks == "harvey":
        d = min(rh * 0.6, 0.25)
        for r in range(int(head), rows):
            for k in range(1, cols):
                bx, by, quarters = x + (k + 0.5) * cw - d / 2, y + (r + 0.5) * rh - d / 2, rng.randrange(5)
                _add(shapes, bx, by, d, d, DARK if quarters == 4 else WHITE, DARK, preset=MSO_SHAPE.OVAL)
                if 0 < quarters < 4:
                    pie = _add(shapes, bx, by, d, d, DARK, preset=MSO_SHAPE.PIE)
                    pie.adjustments[0], pie.adjustments[1] = 162.0, (270 + 90 * quarters) % 360 * 0.6  # 60000ths deg


def _chart_area(shapes, c, x, y, w, h, rng):
    kind = c["chart_type"]
    if kind == "other":
        _add(shapes, x, y, w, h, LIGHT, text="Chart here", size=14, color=GREYS[0])
        return
    n = 5
    values = [[rng.randint(10, 100) for _ in range(n)] for _ in range(3 if kind == "stacked_bar" else 2 if kind == "line" else 1)]
    if kind == "scatter":
        data = XyChartData()
        for k, ys in enumerate(values):
            s = data.add_series(str(k + 1))
            for px, py in enumerate(ys, 1):
                s.add_data_point(px, py)
    else:
        data = CategoryChartData()
        data.categories = range(1, n + 1)
        if kind == "waterfall":
            values = [[sum(values[0][:k]) for k in range(n)], values[0]]
        for k, v in enumerate(values):
            data.add_series(str(k + 1), v)
    chart = shapes.add_chart(CHARTS[kind], *(Emu(round(v * IN)) for v in (x, y, w, h)), data).chart
    chart.has_legend, chart.has_title = False, False
    chart.font.name, chart.font.size = FONT, Pt(10)
    plot = chart.plots[0]
    if kind in ("pie", "donut"):
        for s in plot.series:
            for k in range(n):
                s.points[k].format.fill.solid()
                s.points[k].format.fill.fore_color.rgb = _rgb(SERIES[k % len(SERIES)])
        return
    plot.vary_by_categories = False
    for k, s in enumerate(plot.series):
        grey = _rgb(SERIES[k % len(SERIES)])
        if kind in ("line", "scatter"):
            s.smooth = False
            s.marker.style = XL_MARKER_STYLE.CIRCLE if kind == "scatter" else XL_MARKER_STYLE.NONE
            s.marker.format.fill.solid()
            s.marker.format.fill.fore_color.rgb = grey
            if kind == "scatter":
                s.format.line.fill.background()
            else:
                s.format.line.color.rgb, s.format.line.width = grey, Pt(2.25)
        else:
            s.format.fill.solid()
            s.format.fill.fore_color.rgb = grey
    if kind == "waterfall":
        plot.series[0].format.fill.background()
    for ax in (chart.category_axis, chart.value_axis):
        ax.tick_label_position, ax.has_major_gridlines = XL_TICK_LABEL_POSITION.NONE, False
        ax.major_tick_mark = ax.minor_tick_mark = XL_TICK_MARK.NONE
        ax.format.line.color.rgb = _rgb(GREYS[3])
    chart.value_axis.visible = kind == "scatter"


def _image_area(shapes, c, x, y, w, h, rng):
    v = c["variant"]
    if v == "icon":
        d = min(w, h, 1.0) * 0.8
        _add(shapes, x + (w - d) / 2, y + (h - d) / 2, d, d, WHITE, GREYS[3], "Icon", 12, GREYS[0], preset=MSO_SHAPE.OVAL)
        return
    _add(shapes, x, y, w, h, LIGHT, text={"photo": "Image here", "map": "Map here"}.get(v, ()), size=14, color=GREYS[0])
    if v == "device":
        sw = min(w * 0.8, h * 0.8 * 16 / 10)
        _add(shapes, x + (w - sw) / 2, y + (h - sw * 10 / 16) / 2, sw, sw * 10 / 16, WHITE, GREYS[2],
             "Product mockup here", 12, GREYS[0])


def _steps(shapes, c, x, y, w, h, rng):
    n = c["n"]
    if c["direction"] == "h":
        xs, sw = _split(x, w, n)
        d = min(0.39, h * 0.3)
        _add(shapes, x + sw / 2, y + d / 2 - 0.01, w - sw, 0.02, GREYS[3])
        for k, sx in enumerate(xs):
            _add(shapes, sx + (sw - d) / 2, y, d, d, DARK, text=str(k + 1), size=13, color=WHITE, bold=True,
                 preset=MSO_SHAPE.OVAL)
            rest = y + h - (y + d + 0.08)
            _add(shapes, sx, y + d + 0.08, sw, min(0.32, rest * 0.5), text="Step Header", size=14, bold=True)
            _add(shapes, sx, y + d + 0.08 + min(0.32, rest * 0.5), sw, rest - min(0.32, rest * 0.5),
                 text="Text here", color=GREYS[0], anchor=TOP)
        return
    ys, sh = _split(y, h, n, 0.08)
    d = min(0.39, sh * 0.7)
    for k, sy in enumerate(ys):
        _add(shapes, x, sy, w, sh, LIGHT)
        _add(shapes, x + 0.12, sy + (sh - d) / 2, d, d, DARK, text=str(k + 1), size=13, color=WHITE, bold=True,
             preset=MSO_SHAPE.OVAL)
        tx = x + 0.12 + d + 0.12
        _add(shapes, tx, sy, w - (tx - x), sh / 2, text="Step Header", size=14, bold=True, align=LEFT, anchor=BOTTOM)
        _add(shapes, tx, sy + sh / 2, w - (tx - x), sh / 2, text="Text here", color=GREYS[0], align=LEFT, anchor=TOP)


def _timeline(shapes, c, x, y, w, h, rng):
    periods, milestones = c["periods"], c.get("milestones", False)
    lw = min(1.6, w * 0.2)
    xs, pw = _split(x + lw, w - lw, periods, 0.04)
    if c.get("groups"):  # year pills spanning equal runs of periods, above the period headers
        g, gh = c["groups"], min(0.28, h * 0.1)
        ends = [round(k * periods / g) for k in range(g + 1)]
        for a, b in zip(ends, ends[1:]):
            _add(shapes, xs[a], y, xs[b - 1] + pw - xs[a], gh, MID, text="Year X", size=11, bold=True,
                 preset=MSO_SHAPE.ROUNDED_RECTANGLE)
        y, h = y + gh + 0.04, h - gh - 0.04
    hh = min(0.32, h * 0.15)
    for px in xs:
        _add(shapes, px, y, pw, hh, DARK, text="QX", size=11, color=WHITE, bold=True)
    rh = min(0.45, (h - hh - 0.06) / (c["workstreams"] + milestones))
    for r in range(c["workstreams"] + milestones):
        ry = y + hh + 0.06 + r * rh
        _add(shapes, x, ry, lw - 0.08, rh, text="Milestones" if r == c["workstreams"] else "Header here", bold=True,
             align=LEFT)
        _add(shapes, x + lw, ry + 0.03, w - lw, rh - 0.06, LIGHT)
        if r == c["workstreams"]:
            d = min(0.2, rh * 0.5)
            for p in sorted(rng.sample(range(periods), min(3, periods))):
                _add(shapes, xs[p] + (pw - d) / 2, ry + (rh - d) / 2, d, d, DARK, preset=MSO_SHAPE.DIAMOND)
            continue
        start = rng.randrange(periods - 1)
        end = rng.randint(start + 1, periods)
        _add(shapes, xs[start], ry + rh * 0.3, xs[end - 1] + pw - xs[start], rh * 0.4, DARK if r % 2 == 0 else GREYS[2],
             preset=MSO_SHAPE.ROUNDED_RECTANGLE if c.get("rounded") else MSO_SHAPE.RECTANGLE)


def _roadmap(shapes, c, x, y, w, h, rng):
    xs, pw = _split(x, w, c["phases"])
    ph = min(0.32, h * 0.15)
    _add(shapes, x, y + ph / 2 - 0.01, w, 0.02, GREYS[3])
    for px in xs:
        _add(shapes, px + pw * 0.15, y, pw * 0.7, ph, DARK, text="Year X", size=11, color=WHITE, bold=True,
             preset=MSO_SHAPE.ROUNDED_RECTANGLE)
        top = y + ph + 0.12
        _add(shapes, px, top, pw, y + h - top, LIGHT)
        hh = min(0.4, (y + h - top) * 0.25)
        _add(shapes, px + 0.1, top + 0.08, pw - 0.2, hh, text="Phase Header", size=14, bold=True, align=LEFT)
        _add(shapes, px + 0.1, top + 0.08 + hh, pw - 0.2, y + h - top - hh - 0.16, text=["Text here"] * 3,
             align=LEFT, anchor=TOP, bullets=True)


def _matrix(shapes, c, x, y, w, h, rng):
    qw, qh = (w - 0.06) / 2, (h - 0.06) / 2
    for qx, qy in ((0, 0), (1, 0), (0, 1), (1, 1)):
        bx, by = x + qx * (qw + 0.06), y + qy * (qh + 0.06)
        _add(shapes, bx, by, qw, qh, MID if (qx, qy) == (1, 0) else LIGHT)
        _add(shapes, bx + 0.08, by + 0.06, qw - 0.16, min(0.3, qh * 0.3), text="Header here", size=11,
             color=GREYS[0], bold=True, align=LEFT)
    d = min(0.22, qh * 0.3)
    for _ in range(c["dots"]):
        dx, dy = x + 0.15 + rng.random() * (w - 1.3), y + 0.45 + rng.random() * (h - 0.75)
        _add(shapes, dx, dy, d, d, DARK, preset=MSO_SHAPE.OVAL)
        _add(shapes, dx + d + 0.04, dy - 0.04, 0.9, d + 0.08, text="Text here", size=10, align=LEFT)


def _tree(shapes, c, x, y, w, h, rng):
    levels, b = c["levels"], c["branching"]
    xs, cw = _split(x, w, levels, 0.35)
    for lvl in range(levels):
        count = b ** lvl
        slot = h / count
        nh = min(0.45, slot * 0.8)
        for j in range(count):
            cy = y + (j + 0.5) * slot
            if lvl:
                pcy = y + (j // b + 0.5) * slot * b
                line = shapes.add_connector(MSO_CONNECTOR.ELBOW, *(Emu(round(v * IN)) for v in (
                    xs[lvl - 1] + cw, pcy, xs[lvl], cy)))
                line.line.color.rgb, line.line.width = _rgb(GREYS[2]), Pt(1)
            _add(shapes, xs[lvl], cy - nh / 2, cw, nh, DARK if lvl == 0 else LIGHT,
                 text="Header here" if lvl == 0 else "Text here", color=WHITE if lvl == 0 else DARK, bold=lvl == 0)


def _funnel(shapes, c, x, y, w, h, rng):
    n = c["stages"]
    ys, sh = _split(y, h, n, 0.06)
    for k, sy in enumerate(ys):
        bw = w * (1 - 0.6 * k / (n - 1))
        _add(shapes, x + (w - bw) / 2, sy, bw, sh, (DARK, GREYS[0], GREYS[1], GREYS[2], GREYS[3], MID)[k],
             text="Text here", color=WHITE if k < 3 else DARK)


def _hub(shapes, c, x, y, w, h, rng):
    n = c["n"]
    cx, cy, d = x + w / 2, y + h / 2, min(h * 0.38, w * 0.25)
    sw, sh = min(1.9, w * 0.24), min(0.45, h * 0.16)
    rx, ry = (w - sw) / 2, (h - sh) / 2
    pts = [(cx + rx * math.cos(a), cy + ry * math.sin(a)) for a in (math.radians(-90 + 360 * k / n) for k in range(n))]

    if c.get("connectors"):  # drawn first: the nodes cover the ends
        for px, py in pts:
            _line(shapes, cx, cy, px, py)
    if c.get("cycle"):  # clockwise arrows between neighbouring satellites, from pill edge to pill edge
        for (ax, ay), (bx, by) in zip(pts, pts[1:] + pts[:1]):
            dx, dy = bx - ax, by - ay
            t = min(sw / 2 / abs(dx) if abs(dx) > 1e-9 else 1, sh / 2 / abs(dy) if abs(dy) > 1e-9 else 1)
            t = min(t + 0.06 / math.hypot(dx, dy), 0.45)
            _line(shapes, ax + dx * t, ay + dy * t, bx - dx * t, by - dy * t, arrow=True)
    _add(shapes, cx - d / 2, cy - d / 2, d, d, DARK, text="Header here", size=14, color=WHITE, bold=True,
         preset=MSO_SHAPE.OVAL)
    for px, py in pts:
        _add(shapes, px - sw / 2, py - sh / 2, sw, sh, LIGHT, text="Header here", size=12, bold=True,
             preset=MSO_SHAPE.ROUNDED_RECTANGLE)


def _before_after(shapes, c, x, y, w, h, rng):
    aw = 0.5
    cw = (w - aw - 0.24) / 2
    x2 = x + cw + aw + 0.24
    hh = min(0.43, h * 0.2)
    _add(shapes, x, y, cw, hh, MID, text="Before", size=14, bold=True)
    _add(shapes, x2, y, cw, hh, DARK, text="After", size=14, color=WHITE, bold=True)
    ys, rh = _split(y + hh + 0.1, h - hh - 0.1, c["rows"], 0.08)
    for ry in ys:
        _add(shapes, x, ry, cw, rh, LIGHT, text="Text here", size=13)
        _add(shapes, x2, ry, cw, rh, WHITE, DARK, "Text here", 13)
    _add(shapes, x + cw + 0.12, y + h / 2 - 0.2, aw, 0.4, GREYS[2], preset=MSO_SHAPE.RIGHT_ARROW)


def _takeaway(shapes, c, x, y, w, h, rng):
    bh = min(h, 0.52)
    by = y + (h - bh) / 2
    _add(shapes, x, by, w, bh, line=GREYS[0], dash=True)
    _add(shapes, x + 0.12, by, 1.6, bh, text="Key takeaway:", size=13, bold=True, align=LEFT)
    _add(shapes, x + 1.72, by, w - 1.84, bh, text="Text here", size=13, align=LEFT)


def _quote(shapes, c, x, y, w, h, rng):
    _add(shapes, x, y, 0.08, h, DARK)
    _add(shapes, x + 0.25, y, w - 0.25, h * 0.65, text="“Text here”", size=24, italic=True, align=LEFT, anchor=BOTTOM)
    _add(shapes, x + 0.25, y + h * 0.68, w - 0.25, h * 0.3, text="Name here", color=GREYS[0], align=LEFT, anchor=TOP)


def _hero_number(shapes, c, x, y, w, h, rng):
    _add(shapes, x, y, w, h * 0.65, text="XX%", size=72, bold=True, anchor=BOTTOM)
    _add(shapes, x, y + h * 0.65, w, h * 0.35, text="Text here", size=14, color=GREYS[0], anchor=TOP)


def _card_stack(shapes, c, x, y, w, h, rng):
    ys, ch = _split(y, h, c["n"], 0.08)
    sw = min(2.08, w * 0.22) if c.get("header_strip") else 0
    for cy in ys:
        left = x
        if sw:
            _add(shapes, x, cy, sw, ch, MID, text="Header here", size=13, bold=True)
            left += sw + 0.08
        _add(shapes, left, cy, x + w - left, ch, LIGHT)
        left += 0.12
        if c.get("icon"):
            d = min(0.5, ch * 0.7)
            _add(shapes, left, cy + (ch - d) / 2, d, d, WHITE, GREYS[3], "Icon", 10, GREYS[0], preset=MSO_SHAPE.OVAL)
            left += d + 0.12
        if not sw:
            hw = min(2.4, (x + w - left) * 0.35)
            _add(shapes, left, cy, hw, ch, text="Header here", size=14, bold=True, align=LEFT)
            left += hw
        _add(shapes, left, cy, x + w - left - 0.1, ch, text="Text here", color=GREYS[0], align=LEFT)


def _swimlane(shapes, c, x, y, w, h, rng):
    lw = min(1.6, w * 0.18)
    xs, sw = _split(x + lw + 0.08, w - lw - 0.08, c["stages"], 0.08)
    hh = min(0.36, h * 0.12)
    for sx in xs:
        _add(shapes, sx, y, sw, hh, DARK, text="Header here", size=12, color=WHITE, bold=True)
    top = y + hh + 0.08
    if c.get("curve"):  # a sentiment line over the stages, one dot per stage
        ch, d = min(1.0, (h - hh) * 0.25), 0.14
        pts = [(sx + sw / 2, top + d / 2 + rng.random() * (ch - d)) for sx in xs]
        _path(shapes, pts, color=GREYS[1], smooth=True)
        for px, py in pts:
            _add(shapes, px - d / 2, py - d / 2, d, d, DARK, preset=MSO_SHAPE.OVAL)
        top += ch + 0.08
    ys, rh = _split(top, y + h - top, c["lanes"], 0.08)
    for ry in ys:
        _add(shapes, x, ry, lw, rh, MID, text="Header here", size=12, bold=True)
        for sx in xs:
            _add(shapes, sx, ry, sw, rh, LIGHT, text="Text here", size=11)


def _journey(shapes, c, x, y, w, h, rng):
    n = c["n"]
    if c.get("persona"):  # a profile slot at the left
        pw = min(2.2, w * 0.22)
        d = min(0.9, pw * 0.5, h * 0.35)
        _add(shapes, x, y, pw, h, LIGHT)
        _add(shapes, x + (pw - d) / 2, y + 0.15, d, d, WHITE, GREYS[3], "Icon", 10, GREYS[0], preset=MSO_SHAPE.OVAL)
        _add(shapes, x + 0.1, y + 0.2 + d, pw - 0.2, 0.3, text="Name here", size=13, bold=True)
        _add(shapes, x + 0.1, y + 0.55 + d, pw - 0.2, max(h - d - 0.65, 0.02), text=["Text here"] * 3, align=LEFT,
             anchor=TOP, color=GREYS[0], bullets=True)
        x, w = x + pw + 0.2, w - pw - 0.2
    xs, sw = _split(x, w, n)
    cy, d = y + h / 2, min(0.39, h * 0.12)
    wave = h * 0.08 if c.get("curve") else 0
    pts = [(sx + sw / 2, cy + (wave if k % 2 else -wave)) for k, sx in enumerate(xs)]
    if wave:
        _path(shapes, [(x, cy)] + pts + [(x + w, cy)], color=GREYS[2], width=2, smooth=True)
    else:
        _line(shapes, x, cy, x + w, cy)
    hb = min(0.3, (h / 2 - wave - d / 2 - 0.3) / 2)
    for k, (sx, (px, py)) in enumerate(zip(xs, pts)):
        above = k % 2 == 0
        edge = py - d / 2 if above else py + d / 2
        label = cy - wave - d / 2 - 0.25 if above else cy + wave + d / 2 + 0.25  # the label edge near the axis
        _line(shapes, px, edge, px, label)
        top = label - 2 * hb if above else label
        _add(shapes, sx, top, sw, hb, text="Header here", size=13, bold=True)
        _add(shapes, sx, top + hb, sw, hb, text="Text here", color=GREYS[0])
        _add(shapes, px - d / 2, py - d / 2, d, d, DARK, text=str(k + 1), size=12, color=WHITE, bold=True,
             preset=MSO_SHAPE.OVAL)


def _flow_diagram(shapes, c, x, y, w, h, rng):
    n, icon = c["n"], c.get("icon", False)
    rows = 1 if c["arrangement"] == "row" else 2 if n <= 8 else 3
    cols = math.ceil(n / rows)
    xs, nw = _split(x, w, cols, 0.45)
    ys, sh = _split(y, h, rows, 0.4)
    nh = min(sh, 1.6 if icon else 1.1)
    boxes = []
    for k in range(n):  # rows wind back and forth, so every arrow is short
        r, j = divmod(k, cols)
        boxes.append((xs[j if r % 2 == 0 else cols - 1 - j], ys[r] + (sh - nh) / 2))
    for (ax, ay), (bx, by) in zip(boxes, boxes[1:]):
        if ay == by:
            sx, ex = (ax + nw + 0.05, bx - 0.05) if bx > ax else (ax - 0.05, bx + nw + 0.05)
            _line(shapes, sx, ay + nh / 2, ex, by + nh / 2, arrow=True)
        else:
            _line(shapes, ax + nw / 2, ay + nh + 0.05, bx + nw / 2, by - 0.05, arrow=True)
    for bx, by in boxes:
        _add(shapes, bx, by, nw, nh, LIGHT, text="Header here", size=13, bold=True, anchor=BOTTOM if icon else MIDDLE)
        if icon:
            d = min(0.5, nh * 0.4, nw * 0.6)
            _add(shapes, bx + (nw - d) / 2, by + nh * 0.12, d, d, WHITE, GREYS[3], "Icon", 10, GREYS[0],
                 preset=MSO_SHAPE.OVAL)


def _device_row(shapes, c, x, y, w, h, rng):
    xs, dw = _split(x, w, c["n"], 0.3)
    for dx in xs:
        if c["device"] == "phone":
            fw = min(dw, h / 2)
            fx, fy, fh = dx + (dw - fw) / 2, y + (h - 2 * fw) / 2, 2 * fw
            frame = _add(shapes, fx, fy, fw, fh, WHITE, GREYS[2], preset=MSO_SHAPE.ROUNDED_RECTANGLE)
            frame.adjustments[0] = 0.15
            _add(shapes, fx + fw * 0.08, fy + fw * 0.2, fw * 0.84, fh - fw * 0.4, LIGHT, text="Image here",
                 color=GREYS[0])
            continue
        sh = min(h / 1.1, dw * 0.85 * 10 / 16)
        sw, bh = sh * 1.6, sh * 0.1
        fy = y + (h - sh - bh) / 2
        _add(shapes, dx + (dw - sw) / 2, fy, sw, sh, WHITE, GREYS[2])
        _add(shapes, dx + (dw - sw) / 2 + sh * 0.05, fy + sh * 0.05, sw - sh * 0.1, sh * 0.9, LIGHT, text="Image here",
             color=GREYS[0])
        bw = min(dw, sw * 1.18)
        _add(shapes, dx + (dw - bw) / 2, fy + sh, bw, bh, MID, preset=MSO_SHAPE.TRAPEZOID)


def _stage_strip(shapes, c, x, y, w, h, rng):
    xs, cw = _split(x, w, c["n"], 0.04)
    ch = min(h, 0.5)
    for k, cx in enumerate(xs):
        on = k == c["active"] - 1
        _add(shapes, cx, y + (h - ch) / 2, cw, ch, DARK if on else LIGHT, text="Step Header", size=12,
             color=WHITE if on else DARK, bold=True, preset=MSO_SHAPE.PENTAGON if k == 0 else MSO_SHAPE.CHEVRON)


def _gauge_row(shapes, c, x, y, w, h, rng):
    vertical = c.get("direction") == "v"
    starts, size = _split(y if vertical else x, h if vertical else w, c["n"])
    d = min(size, w * 0.35, 2.0) if vertical else min(size, h * 0.7, 2.0)
    for s0 in starts:
        gx, gy = (x, s0 + (size - d) / 2) if vertical else (s0 + (size - d) / 2, y)
        ring = _add(shapes, gx, gy, d, d, MID, preset=MSO_SHAPE.DONUT)
        ring.adjustments[0] = 0.18
        arc = _add(shapes, gx, gy, d, d, DARK, preset=MSO_SHAPE.BLOCK_ARC)  # from 12 o'clock, clockwise
        end = (270 + 360 * rng.uniform(0.25, 0.9)) % 360 * 0.6  # 60000ths deg, as for the Harvey balls
        arc.adjustments[0], arc.adjustments[1], arc.adjustments[2] = 162.0, end, 0.18
        _add(shapes, gx + d * 0.2, gy + d * 0.3, d * 0.6, d * 0.4, text="XX%", size=16, bold=True)
        if vertical:
            _add(shapes, gx + d + 0.15, s0, w - d - 0.15, size, text="Text here", size=14, color=GREYS[0], align=LEFT)
        else:
            _add(shapes, s0, gy + d + 0.06, size, h - d - 0.06, text="Text here", color=GREYS[0], anchor=TOP)


def _network(shapes, c, x, y, w, h, rng):
    n = c["n"]
    cols = max(1, min(n, round(math.sqrt(n * 1.6 * w / h))))
    rows = math.ceil(n * 1.6 / cols)  # about 60% of the cells hold a node
    cw, ch = w / cols, h / rows
    nw, nh = min(1.6, cw * 0.8), min(0.42, ch * 0.6)
    pts = []
    for cell in sorted(rng.sample(range(cols * rows), n)):  # one node per cell, jittered inside it: no overlaps
        r, k = divmod(cell, cols)
        pts.append((x + (k + 0.5) * cw + rng.uniform(-1, 1) * (cw - nw) / 2,
                    y + (r + 0.5) * ch + rng.uniform(-1, 1) * (ch - nh) / 2))
    near = lambda k, among: sorted(among, key=lambda j: math.dist(pts[k], pts[j]))
    edges = {(near(k, range(k))[0], k) for k in range(1, n)}  # each node to its nearest earlier one: connected
    for k in rng.sample(range(n), n // 3):  # a few cross links
        j = near(k, [j for j in range(n) if j != k])[min(1, n - 2)]
        edges.add((min(j, k), max(j, k)))
    for a, b in sorted(edges):
        _line(shapes, *pts[a], *pts[b])
    hub = max(range(n), key=lambda k: sum(k in e for e in edges))
    for k, (px, py) in enumerate(pts):
        _add(shapes, px - nw / 2, py - nh / 2, nw, nh, DARK if k == hub else LIGHT, text="Header here", size=11,
             color=WHITE if k == hub else DARK, bold=True, preset=MSO_SHAPE.ROUNDED_RECTANGLE)


def _map_callouts(shapes, c, x, y, w, h, rng):
    n, mw = c["n"], w * 0.6
    _add(shapes, x, y, mw, h, LIGHT, text="Map here", size=14, color=GREYS[0], align=LEFT, anchor=TOP)
    ys, lh = _split(y, h, n, 0.08)
    lx, d = x + mw + 0.35, min(0.3, lh * 0.8)
    cw, ch = (mw - 0.4) / 4, (h - 0.5) / 3
    cells = rng.sample(range(12), n)  # markers in distinct cells of a 4 x 3 grid over the map
    marks = sorted((y + 0.4 + (k // 4 + 0.5 + rng.uniform(-0.3, 0.3)) * ch,
                    x + 0.2 + (k % 4 + 0.5 + rng.uniform(-0.3, 0.3)) * cw) for k in cells)  # top first
    marks = [(mx, my) for my, mx in marks]  # numbered top to bottom like the labels, so few leader lines cross
    for (mx, my), ly in zip(marks, ys):
        _line(shapes, mx, my, lx, ly + lh / 2)
    for k, ((mx, my), ly) in enumerate(zip(marks, ys)):
        _add(shapes, mx - d / 2, my - d / 2, d, d, DARK, text=str(k + 1), size=11, color=WHITE, bold=True,
             preset=MSO_SHAPE.OVAL)
        _add(shapes, lx, ly + (lh - d) / 2, d, d, DARK, text=str(k + 1), size=11, color=WHITE, bold=True,
             preset=MSO_SHAPE.OVAL)
        _add(shapes, lx + d + 0.1, ly, x + w - lx - d - 0.1, lh / 2, text="Header here", size=13, bold=True,
             align=LEFT, anchor=BOTTOM)
        _add(shapes, lx + d + 0.1, ly + lh / 2, x + w - lx - d - 0.1, lh / 2, text="Text here", color=GREYS[0],
             align=LEFT, anchor=TOP)


def _bar_list(shapes, c, x, y, w, h, rng):
    n, g = c["n"], c.get("groups", 1)
    heads = g > 1
    starts, rh = _split(y, h, n + g * heads, 0.06)
    ys = iter(starts)
    lw, vw = min(2.2, w * 0.25), 0.8
    full = w - lw - vw - 0.1
    ends = [round(k * n / g) for k in range(g + 1)]
    for a, b in zip(ends, ends[1:]):
        for item in range(a - heads, b):  # a group header row first, then its items
            ry, head = next(ys), item < a
            ind = 0.2 * (heads and not head)
            bl = full * (rng.uniform(0.7, 1) if head else rng.uniform(0.2, 0.9))
            _add(shapes, x + ind, ry, lw - ind, rh, text="Header here" if head else "Text here", size=13, bold=head,
                 align=LEFT)
            _add(shapes, x + lw, ry + rh * 0.2, bl, rh * 0.6, DARK if head else GREYS[2],
                 preset=MSO_SHAPE.ROUNDED_RECTANGLE)
            _add(shapes, x + lw + bl + 0.06, ry, vw, rh, text="$X.XM", size=12, bold=head, align=LEFT)


def _nested_circles(shapes, c, x, y, w, h, rng):
    """n circles shrinking inwards (TAM/SAM/SOM): resting on one bottom point, or sharing a centre (concentric);
    each labelled in the band between its top and the next circle's top."""
    n, d = c["n"], min(w, h)
    ds = [d * (n - k) / n for k in range(n)]
    cx, cy = x + w / 2, y + (h - d) / 2
    tops = [cy + ((d - dk) / 2 if c["arrangement"] == "concentric" else d - dk) for dk in ds]
    for k, (dk, top) in enumerate(zip(ds, tops)):
        _add(shapes, cx - dk / 2, top, dk, dk, (LIGHT, MID, GREYS[3], GREYS[2])[k], GREYS[2], preset=MSO_SHAPE.OVAL)
    for k, (dk, top) in enumerate(zip(ds, tops)):
        band = (tops[k + 1] if k + 1 < n else top + dk) - top
        t = band / 2 if k + 1 < n else dk / 2  # chord at the middle of the band
        _add(shapes, cx - math.sqrt(t * (dk - t)) * 0.8, top, 2 * math.sqrt(t * (dk - t)) * 0.8, band,
             text=["XX%", "Header here"], size=13, bold=True)


def _link_list(shapes, c, x, y, w, h, rng):
    """n entries (appendix or contents) down 1-3 columns, each a number or bullet dot, a header and a hairline."""
    n, cols, numbered = c["n"], c.get("cols", 1), c.get("numbered", True)
    xs, cw = _split(x, w, cols, 0.3)
    rows = -(-n // cols)
    ys, rh = _split(y, h, rows, 0.06)
    rh, d = min(rh, 0.6), min(0.32, rh * 0.8)
    for k in range(n):
        ex, ey = xs[k // rows], ys[k % rows]
        if numbered:
            _add(shapes, ex, ey + (rh - d) / 2, d, d, DARK, text=str(k + 1), size=11, color=WHITE, bold=True,
                 preset=MSO_SHAPE.OVAL)
        else:
            _add(shapes, ex + d / 3, ey + rh / 2 - d / 6, d / 3, d / 3, DARK, preset=MSO_SHAPE.OVAL)
        _add(shapes, ex + d + 0.12, ey, cw - d - 0.12, rh, text="Header here", size=14, bold=True, align=LEFT)
        _add(shapes, ex, ey + rh - 0.02, cw, 0.02, GREYS[3])


# --- whole-slide components (slide inches) --------------------------------------------------------------------

def _section_divider(shapes, c, rng):
    _add(shapes, 7.0, 0, 6.333, 7.5, LIGHT, text="Image here", size=14, color=GREYS[0])
    _add(shapes, 0.78, 1.9, 5.8, 1.5, text=f"{c['number']:02}", size=80, color=GREYS[2], bold=True, align=LEFT,
         anchor=BOTTOM)
    _add(shapes, 0.78, 3.45, 5.8, 0.65, text="Section Title Here", size=32, bold=True, align=LEFT)
    _add(shapes, 0.78, 4.15, 5.8, 0.4, text="Section overview text here", size=14, color=GREYS[0], align=LEFT)


def _cover(shapes, c, rng):
    _add(shapes, 0.78, 0.4, 11.78, 3.9, LIGHT, text="Image here", size=14, color=GREYS[0])
    _add(shapes, 0.78, 4.8, 9.0, 0.8, text="Deck Title Here", size=40, bold=True, align=LEFT)
    _add(shapes, 0.78, 5.6, 9.0, 0.45, text="Subtitle text here", size=17, color=GREYS[0], align=LEFT)


def _closing(shapes, c, rng):
    _add(shapes, 7.6, 0.8, 4.96, 5.9, LIGHT, text="Image here", size=14, color=GREYS[0])
    _add(shapes, 0.78, 2.9, 6.4, 1.0, text="Thank You", size=44, bold=True, align=LEFT)
    _add(shapes, 0.78, 3.9, 6.4, 0.45, text="Subtitle text here", size=17, color=GREYS[0], align=LEFT)


DRAW = {k: globals()[f"_{k}"] for k in lay.KINDS}


def save(prs, path):
    """Write the .pptx with fixed zip times and pinned workbook dates: the same layout gives the same bytes."""
    out = io.BytesIO()
    prs.save(out)
    Path(path).write_bytes(_pinned(out.getvalue()))


def _pinned(blob):
    out = io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(blob)) as src, zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as dst:
        for name in src.namelist():
            data = src.read(name)
            if name.endswith(".xlsx"):  # chart workbooks: XlsxWriter stamps the current time
                data = _pinned(data)
            elif name == "docProps/core.xml":
                data = re.sub(rb"(<dcterms:(?:created|modified)[^>]*>)[^<]*", rb"\g<1>2000-01-01T00:00:00Z", data)
            dst.writestr(zipfile.ZipInfo(name, ZIP_TIME), data, zipfile.ZIP_DEFLATED)
    return out.getvalue()


def render(paths):
    """One LibreOffice call for all the .pptx files; write a greyscale 960x540 PNG next to each and return their paths."""
    soffice = shutil.which("soffice") or (str(extract.SOFFICE_APP) if extract.SOFFICE_APP.exists() else None)
    if not soffice:
        raise SystemExit(f"Mockup PNGs need LibreOffice: no soffice on PATH or at {extract.SOFFICE_APP}.")
    with tempfile.TemporaryDirectory() as tmp:
        srcs = [shutil.copyfile(p, Path(tmp) / f"{k}.pptx") for k, p in enumerate(paths)]
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, *map(str, srcs)],
                       check=True, capture_output=True)
        for k, p in enumerate(paths):
            Path(p).with_suffix(".png").write_bytes(_png(Path(tmp) / f"{k}.pdf"))
    return [Path(p).with_suffix(".png") for p in paths]


def _png(pdf_path):
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        img = pdf[0].render(scale=960 / pdf[0].get_size()[0]).to_pil().convert("L").resize((960, 540))
    finally:
        pdf.close()
    for levels in (256, 16, 8):  # quantise grey levels only when the PNG is over the cap
        step = 255 / (levels - 1)
        out = io.BytesIO()
        img.point(lambda v: round(round(v / step) * step)).save(out, "PNG", optimize=True)
        if len(out.getvalue()) <= build.MAX_WIREFRAME:
            return out.getvalue()
    raise ValueError(f"mockup PNG exceeds {build.MAX_WIREFRAME} bytes")


def run(deck_id, library, slides=None):
    """Build every layouts/<deck>/slide-NN.v3.json into mockups/<deck>/slide-NN.pptx and .png; return the PNG paths."""
    src, out = (Path(library) / d / deck_id for d in ("layouts", "mockups"))
    layouts, errors = {}, []
    for f in sorted(src.glob("slide-??.v3.json")):
        if slides and f.name[6:8] not in slides:
            continue
        try:
            layouts[f] = build_mockup_v3(json.loads(f.read_text()))
        except ValueError as e:
            errors.append(f"{f.name}: {e}")
    if errors:
        raise ValueError("\n".join(errors))
    out.mkdir(parents=True, exist_ok=True)
    paths = [out / f"{f.name[:8]}.pptx" for f in layouts]
    for path, prs in zip(paths, layouts.values()):
        save(prs, path)
    return render(paths) if paths else []
