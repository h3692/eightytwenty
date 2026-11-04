"""Mockups: a layout list built into a real PowerPoint slide with python-pptx, rendered to a greyscale PNG by LibreOffice.

The builder writes no text but the fixed bracket label of each element's kind (or chart type), and charts hold seeded
dummy values only. A saved .pptx is byte-identical for the same layout and doubles as an empty slide template.
"""
import datetime
import io
import json
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
from pptx.util import Inches, Pt

from pipeline import build, extract, layout as lay

W, H = 12192000, 6858000  # 13.333 x 7.5 in, renders as a 960 x 540 pt PDF page
FONT = "Arial"  # on every Mac and Windows install, and LibreOffice renders it here
FIXED_TIME, ZIP_TIME = datetime.datetime(2000, 1, 1), (1980, 1, 1, 0, 0, 0)
INK, LINE = RGBColor(0x40, 0x40, 0x40), RGBColor(0x80, 0x80, 0x80)
FILLS = {"none": None, "light": 0xF2, "mid": 0xD9, "dark": 0xA6}
GREYS = (0x80, 0xB3, 0x59, 0xCC, 0x99, 0x40)  # chart series / slices
WIDTH = {"normal": 1.5, "strong": 2.25, "hero": 3.0}  # line pt
RADIUS = Inches(0.08)
TEXT = {"title": 28, "subtitle": 20, "text": 14, "bullets": 14, "quote": 18, "number": 28, "label": 12, "logo": 12,
        "takeaway": 18}  # label pt; unframed unless "framed"
FRAMED = {"icon": 14, "image": 14, "callout": 14, "step": 14}  # always outlined
SHAPES = {"rect": MSO_SHAPE.RECTANGLE, "round_rect": MSO_SHAPE.ROUNDED_RECTANGLE, "ellipse": MSO_SHAPE.OVAL,
          "chevron": MSO_SHAPE.CHEVRON, "arrow_right": MSO_SHAPE.RIGHT_ARROW, "arrow_left": MSO_SHAPE.LEFT_ARROW,
          "arrow_up": MSO_SHAPE.UP_ARROW, "arrow_down": MSO_SHAPE.DOWN_ARROW, "triangle": MSO_SHAPE.ISOSCELES_TRIANGLE,
          "diamond": MSO_SHAPE.DIAMOND}  # others: rectangle
CHARTS = {"bar": XL_CHART_TYPE.BAR_CLUSTERED, "column": XL_CHART_TYPE.COLUMN_CLUSTERED,
          "stacked_bar": XL_CHART_TYPE.BAR_STACKED, "line": XL_CHART_TYPE.LINE, "pie": XL_CHART_TYPE.PIE,
          "donut": XL_CHART_TYPE.DOUGHNUT, "scatter": XL_CHART_TYPE.XY_SCATTER,
          "waterfall": XL_CHART_TYPE.COLUMN_STACKED, "area": XL_CHART_TYPE.AREA}  # waterfall: invisible base series
LABELS = {f"[{k}]" for k in (*TEXT, *FRAMED)} | {f"[{t.replace('_', ' ')} chart]" for t in CHARTS}


def _label(e):
    return f"[{e['chart_type'].replace('_', ' ')} chart]" if e["kind"] == "chart" else f"[{e['kind']}]"


def build_mockup(layout):
    """A one-slide 16:9 Presentation of a layout list (v1 or v2; validated here)."""
    els = lay.validate(layout)["elements"]
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
    depth = []
    for e in els:
        depth.append(depth[e["parent"]] + 1 if "parent" in e else 0)  # a parent is always listed first
    ops = []  # z-order: strips/bands/panels -> cards (nested ones above their parent) -> frames -> lines -> labels
    for i, e in enumerate(els):
        k = e["kind"]
        if k in lay.CONTAINERS:
            ops.append(((0, depth[i], k == "card", i), _container))
        elif k in ("divider", "arrow", "connector"):
            ops.append(((2, 0, 0, i), _line))
        elif k in ("chart", "table") or k in FRAMED or e.get("framed"):
            ops.append(((1, 0, 0, i), {"chart": _chart, "table": _table}.get(k, _frame)))
        if k in TEXT or k in FRAMED:
            ops.append(((3, 0, 0, i), _text))
    for key, draw in sorted(ops, key=lambda o: o[0]):
        draw(shapes, els[key[3]], key[3], els)
    for style in shapes._spTree.findall(f".//{qn('p:style')}"):  # theme style: accent colours, a drop shadow
        style.getparent().remove(style)
    return prs


def _box(e):
    x, y, w, h = e["box"]
    return round(x * W), round(y * H), round(w * W), round(h * H)


def _grey(v):
    return RGBColor(v, v, v)


def _fill(shape, v):
    if v is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = _grey(v)


def _stroke(shape, e):
    shape.line.width = Pt(WIDTH[e.get("emphasis", "normal")])
    shape.line.color.rgb = LINE
    if e.get("dashed"):
        shape.line.dash_style = MSO_LINE.DASH


def _poly(shapes, points, close):
    pts = [(round(x * W), round(y * H)) for x, y in points]
    b = shapes.build_freeform(*pts[0])
    b.add_line_segments(pts[1:], close=close)
    return b.convert_to_shape()


def _shape(shapes, e, preset=None):
    if e["shape"] == "polygon" and e.get("points"):
        s = _poly(shapes, e["points"], close=True)
    else:
        x, y, w, h = _box(e)
        preset = preset or SHAPES.get(e["shape"], MSO_SHAPE.RECTANGLE)
        s = shapes.add_shape(preset, x, y, w, h)
        if preset == MSO_SHAPE.ROUNDED_RECTANGLE:
            s.adjustments[0] = min(0.5, RADIUS / max(min(w, h), 1))
    return s


def _container(shapes, e, i, els):
    card = e["kind"] == "card"
    s = _shape(shapes, e, MSO_SHAPE.ROUNDED_RECTANGLE if card and e["shape"] in ("none", "rect") else None)
    _fill(s, FILLS[e.get("fill", "none" if card else "light")])
    if card or e.get("dashed") or e.get("emphasis") in ("strong", "hero"):
        _stroke(s, e)
    else:
        s.line.fill.background()


def _frame(shapes, e, i, els):
    s = _shape(shapes, e)
    _fill(s, None)
    _stroke(s, e)


def _line(shapes, e, i, els):
    style = e.get("arrow_style", "line")
    if e["kind"] == "arrow" and style != "line":
        x, y, w, h = _box(e)
        preset = MSO_SHAPE.CHEVRON if style == "chevron" else SHAPES[e["shape"]] if e["shape"].startswith("arrow_") \
            else MSO_SHAPE.RIGHT_ARROW if w >= h else MSO_SHAPE.DOWN_ARROW
        s = _shape(shapes, e, preset)
        _fill(s, FILLS["light"])
        _stroke(s, e)
        return
    pts = lay._path(e, els)
    if len(pts) == 2:
        (x0, y0), (x1, y1) = pts
        s = shapes.add_connector(MSO_CONNECTOR.STRAIGHT, round(x0 * W), round(y0 * H), round(x1 * W), round(y1 * H))
    else:
        s = _poly(shapes, pts, close=False)
        _fill(s, None)
    _stroke(s, e)
    head = "none" if e["kind"] == "divider" else e.get("head", "end")
    ln = s._element.spPr.get_or_add_ln()
    for end in ("headEnd",) * (head == "both") + ("tailEnd",) * (head != "none"):
        ln.append(parse_xml(f'<a:{end} {nsdecls("a")} type="triangle" w="med" len="med"/>'))


def _text(shapes, e, i, els):
    """The element's bracket label in its own text box: centred in frames, left-aligned for unframed text."""
    label, framed = _label(e), e["kind"] in FRAMED or e.get("framed", False)
    size = (TEXT | FRAMED)[e["kind"]]
    if e.get("emphasis") == "hero":
        size = 72 if e["kind"] == "number" else size * 1.5
    elif e.get("emphasis") == "strong":
        size *= 1.25
    x, y, w, h = _box(e)
    inset = 0.7 if framed and e["shape"] in ("ellipse", "diamond", "triangle") else 1.0
    pad = Pt(4) if framed else 0
    room_w, room_h = (w * inset - 2 * pad) / 12700, h * inset / 12700  # pt
    size = int(min(size, room_h / 1.25, room_w / (0.6 * len(label))))  # 0.6 em: a generous average Arial glyph
    if size < 6:
        return  # too small to read: leave the label out
    tf = shapes.add_textbox(x, y, w, h).text_frame
    tf.word_wrap, tf.auto_size, tf.vertical_anchor = False, MSO_AUTO_SIZE.NONE, MSO_ANCHOR.MIDDLE
    tf.margin_left = tf.margin_right = pad
    tf.margin_top = tf.margin_bottom = 0
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER if framed else PP_ALIGN.LEFT
    r = p.add_run()
    r.text = label
    r.font.name, r.font.size, r.font.color.rgb = FONT, Pt(size), INK
    r.font.bold = e["kind"] == "title" or e.get("emphasis") in ("strong", "hero")


def _table(shapes, e, i, els):
    table = shapes.add_table(e["rows"], e["cols"], *_box(e)).table
    table.first_row, table.horz_banding = e.get("header_row", False), False
    border = "".join(f'<a:{t} {nsdecls("a")} w="12700"><a:solidFill><a:srgbClr val="808080"/></a:solidFill></a:{t}>'
                     for t in ("lnL", "lnR", "lnT", "lnB"))
    for r, row in enumerate(table.rows):
        for cell in row.cells:
            cell.fill.solid()
            cell.fill.fore_color.rgb = _grey(FILLS["mid"] if r == 0 and table.first_row else 0xFF)
            cell.margin_top = cell.margin_bottom = cell.margin_left = cell.margin_right = 0
            cell.text_frame.paragraphs[0]._p.get_or_add_endParaRPr().set("sz", "100")  # empty rows may be thin
            tcPr = cell._tc.get_or_add_tcPr()
            for k, ln in enumerate(parse_xml(f'<x {nsdecls("a")}>{border}</x>')):  # borders precede the cell fill
                tcPr.insert(k, ln)


def _chart(shapes, e, i, els):
    kind, n = e["chart_type"], e.get("categories", 4)
    rng = random.Random(i)  # dummy values seeded by element index: never real data
    values = [[rng.randint(10, 100) for _ in range(n)] for _ in range(e.get("series", 1))]
    if kind == "scatter":
        data = XyChartData()
        for k, ys in enumerate(values):
            s = data.add_series(str(k + 1))
            for x, y in enumerate(ys, 1):
                s.add_data_point(x, y)
    else:
        data = CategoryChartData()
        data.categories = range(1, n + 1)
        if kind == "waterfall":
            values = [[sum(values[0][:k]) for k in range(n)], values[0]]
        for k, v in enumerate(values):
            data.add_series(str(k + 1), v)
    chart = shapes.add_chart(CHARTS[kind], *_box(e), data).chart
    chart.has_legend, chart.has_title = False, True
    chart.font.name, chart.font.size = FONT, Pt(10)
    chart.chart_title.text_frame.text = _label(e)
    title = chart.chart_title.text_frame.paragraphs[0].runs[0].font
    title.size, title.bold, title.color.rgb = Pt(12), False, INK
    plot = chart.plots[0]
    if kind in ("pie", "donut"):
        for s in plot.series:
            for k in range(n):
                s.points[k].format.fill.solid()
                s.points[k].format.fill.fore_color.rgb = _grey(GREYS[k % len(GREYS)])
        return
    plot.vary_by_categories = False
    for k, s in enumerate(plot.series):
        grey = _grey(GREYS[k % len(GREYS)])
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
        ax.format.line.color.rgb = LINE
    chart.value_axis.visible = kind == "scatter"


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


def run(deck_id, library, slides=None, variant="final"):
    """Validate (upgrading v1) and snap every layouts/<deck>/slide-NN.<variant>.json, then write
    mockups/<deck>/slide-NN.<variant>.pptx and .png; return the PNG paths."""
    src, work, out = (Path(library) / d / deck_id for d in ("layouts", "work", "mockups"))
    layouts, errors = {}, []
    for f in sorted(src.glob(f"slide-??.{variant}.json")):
        if slides and f.name[6:8] not in slides:
            continue
        try:
            layout = lay.validate(json.loads(f.read_text()))
            if any("region_ids" in e for e in layout["elements"]):
                layout = lay.snap(layout, json.loads((work / f"{f.name[:8]}.json").read_text()))
            layouts[f] = build_mockup(layout)
        except ValueError as e:
            errors.append(f"{f.name}: {e}")
    if errors:
        raise ValueError("\n".join(errors))
    out.mkdir(parents=True, exist_ok=True)
    paths = [out / f"{f.stem}.pptx" for f in layouts]
    for path, prs in zip(paths, layouts.values()):
        save(prs, path)
    return render(paths) if paths else []
