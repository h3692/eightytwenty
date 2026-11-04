"""Stage 1: render visible slides to PNG and extract layout structure (never words) from a .pptx.

Only geometry, shape types, z-order, colour/type roles and text counts are read. Speaker notes, review
annotations, alt text, links, document properties, hidden slides, shape/image/embedded file names are never
touched (see test_extractor_never_touches_excluded_channels).
"""
import json
import math
import re
import secrets
import shutil
import subprocess
import tempfile
from collections import Counter
from pathlib import Path

import pypdfium2 as pdfium
from pptx import Presentation
from pptx.enum.dml import MSO_COLOR_TYPE, MSO_FILL
from pptx.enum.shapes import MSO_AUTO_SHAPE_TYPE, MSO_SHAPE_TYPE, PP_PLACEHOLDER
from pptx.enum.text import PP_ALIGN

SOFFICE_APP = Path("/Applications/LibreOffice.app/Contents/MacOS/soffice")
SCHEME_ROLES = {"accent1": "primary", "dk1": "neutral-dark", "dk2": "neutral-dark", "tx1": "neutral-dark",
                "tx2": "neutral-dark", "lt1": "white", "bg1": "white", "lt2": "neutral-light", "bg2": "neutral-light"}
ALIGN = {PP_ALIGN.CENTER: "center", PP_ALIGN.RIGHT: "right", PP_ALIGN.JUSTIFY: "justify"}
NUMBER = re.compile(r"[\s+\-~<>≈]*([$€£¥])?\s*\d[\d.,]*\s*(%|x|×|k|m|bn|b)?\s*\+?", re.I)
EMU_PER_PT = 12700
# Line presets as polylines in the unit box (curved connectors drawn straight).
LINE_PATHS = {"line": [(0, 0), (1, 1)], "straightConnector1": [(0, 0), (1, 1)], "bentConnector2": [(0, 0), (1, 0), (1, 1)],
              **{f"bentConnector{n}": [(0, 0), (0.5, 0), (0.5, 1), (1, 1)] for n in (3, 4, 5)},
              **{f"curvedConnector{n}": [(0, 0), (1, 1)] for n in (2, 3, 4, 5)}}
MAX_PATH_POINTS = 32
# Safety: a small freeform with many points may be a brand mark; its outline is never stored.
SMALL_AREA, MAX_SMALL_POINTS = 0.03, 12
A = "{http://schemas.openxmlformats.org/drawingml/2006/main}"


def run(pptx_path, library, render=True, deck_id=None):
    """Extract one deck into library/work/<deck_id>/ and return the new opaque deck_id.

    With deck_id, re-extract into that existing deck, keeping its labels (and renders unless render is set)."""
    work = Path(library) / "work" / (deck_id or "")
    if deck_id and not (work / "text").is_dir():
        raise SystemExit(f"no extracted deck {deck_id} under {Path(library) / 'work'}")
    deck_id = deck_id or secrets.token_hex(8)  # random, never derived from the file name
    work = Path(library) / "work" / deck_id
    (work / "text").mkdir(parents=True, exist_ok=True)
    prs = Presentation(str(pptx_path))
    visible = [s for s in prs.slides if s._element.get("show") != "0"]
    raw = [_slide(s, prs.slide_width, prs.slide_height) for s in visible]
    palette = _palette(raw)
    for n, (regions, background, text) in enumerate(raw, 1):
        doc = {"deck_id": deck_id, "slide": n, "background": _role(background, palette),
               "regions": [_resolve(r, palette) for r in regions]}
        (work / f"slide-{n:02d}.json").write_text(json.dumps(doc, indent=1))
        (work / "text" / f"slide-{n:02d}.txt").write_text("\n".join(text))  # local only, for the leak check
    if render:
        _render(pptx_path, work, len(visible))
    return deck_id


def _render(pptx_path, work, count):
    soffice = shutil.which("soffice") or (str(SOFFICE_APP) if SOFFICE_APP.exists() else None)
    if not soffice:
        raise SystemExit(f"Rendering needs LibreOffice: no soffice on PATH or at {SOFFICE_APP}; "
                         "install it or pass --skip-render.")
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "deck.pptx"  # neutral name: the original file name never reaches a render
        shutil.copyfile(pptx_path, src)
        subprocess.run([soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)], check=True, capture_output=True)
        _pdf_to_png(Path(tmp) / "deck.pdf", work, count)


def _pdf_to_png(pdf_path, work, count):
    # LibreOffice's PDF export leaves hidden slides out, so page n is the n-th visible slide.
    pdf = pdfium.PdfDocument(pdf_path)
    try:
        for n in range(1, count + 1):
            page = pdf[n - 1]
            page.render(scale=1280 / max(page.get_size())).to_pil().save(work / f"slide-{n:02d}.png")
    finally:
        pdf.close()


def _slide(slide, width, height):
    regions, text = [], []
    try:
        bg = _color(slide.background.fill.fore_color) if slide.background.fill.type == MSO_FILL.SOLID else None
    except (TypeError, AttributeError):
        bg = None
    xf = lambda x, y, w, h: (x, y, w, h)
    _walk(slide.shapes, xf, None, regions, text, width, height)
    return regions, bg, text


def _walk(shapes, xf, parent, regions, text, width, height):
    for shape in shapes:
        # shortcut: boxes are fractions of the slide, so 4:3 decks stretch to the 16:9 unit box.
        x, y, w, h = xf(shape.left or 0, shape.top or 0, shape.width or 0, shape.height or 0)
        r = {"i": len(regions), "parent": parent, "type": _type(shape),
             "box": {"x": round(x / width, 4), "y": round(y / height, 4), "w": round(w / width, 4), "h": round(h / height, 4)},
             "fill": _fill(shape), "line": _line(shape), "dashed": _dashed(shape), "geom": _geom(shape),
             "path": None, "arrow": _arrow(shape), "text": None, "chart": None, "table": None}
        r["geom"], r["path"] = _outline(shape, r["geom"], w, h, r["box"]["w"] * r["box"]["h"])
        regions.append(r)
        if r["type"] == "group":
            g = shape._element.grpSpPr.xfrm
            sx, sy = (g.ext.cx / g.chExt.cx if g.chExt.cx else 1), (g.ext.cy / g.chExt.cy if g.chExt.cy else 1)
            child = lambda cx, cy, cw, ch, g=g, sx=sx, sy=sy, outer=xf: outer(
                g.off.x + (cx - g.chOff.x) * sx, g.off.y + (cy - g.chOff.y) * sy, cw * sx, ch * sy)
            _walk(shape.shapes, child, r["i"], regions, text, width, height)
        elif r["type"] == "chart":
            chart = shape.chart
            cats = list(chart.plots[0].categories) if len(chart.plots) else []
            r["chart"] = {"kind": chart.chart_type.name, "series": len(list(chart.series)), "categories": len(cats)}
            text += [str(c) for c in cats] + [s_.name for s_ in chart.series]
        elif r["type"] == "table":
            rows = shape.table.rows
            r["table"] = {"rows": len(rows), "cols": len(shape.table.columns)}
            text += [cell.text for row in rows for cell in row.cells if cell.text]
        elif shape.has_text_frame and shape.text_frame.text.strip():
            r["text"] = _text(shape, w)
            text += [p.text for p in shape.text_frame.paragraphs if p.text.strip()]


def _type(shape):
    t = shape.shape_type
    if t == MSO_SHAPE_TYPE.GROUP:
        return "group"
    if t == MSO_SHAPE_TYPE.PICTURE or (shape.is_placeholder and hasattr(shape, "image")):
        return "picture"
    if getattr(shape, "has_chart", False):
        return "chart"
    if getattr(shape, "has_table", False):
        return "table"
    if t == MSO_SHAPE_TYPE.LINE:
        return "line"
    if shape.has_text_frame and shape.text_frame.text.strip():
        return "text"
    return "shape"


def _text(shape, width_emu):
    paras = [p for p in shape.text_frame.paragraphs if p.text.strip()]
    runs = [r for p in paras for r in p.runs]
    sizes = [r.font.size.pt for r in runs if r.font.size]
    title_ph = shape.is_placeholder and shape.placeholder_format.type in (PP_PLACEHOLDER.TITLE, PP_PLACEHOLDER.CENTER_TITLE)
    body_ph = shape.is_placeholder and shape.placeholder_format.type in (PP_PLACEHOLDER.BODY, PP_PLACEHOLDER.OBJECT)
    # shortcut: inherited sizes are not resolved from layout/master; assume title 40pt, body 18pt.
    pt = max(sizes) if sizes else (40 if title_ph else 18)
    cpl = max(1, (width_emu / EMU_PER_PT - 14.4) / (0.5 * pt))  # rough chars per line at ~0.5 em average width
    full = shape.text_frame.text.strip()
    m = NUMBER.fullmatch(full)
    return {
        "words": len(full.split()),
        "paragraphs": len(paras),
        "lines": sum(max(1, math.ceil(len(p.text.strip()) / cpl)) for p in paras),
        "bullets": sum(1 for p in paras if _bulleted(p, body_ph)),
        "align": ALIGN.get(paras[0].alignment, "left"),
        "size_pt": max(sizes) if sizes else None, "title_ph": title_ph,
        "weight": "bold" if any(r.font.bold for r in runs) else "regular",
        "color": next((c for c in (_color(r.font.color) for r in runs) if c), None),
        "number": None if not m else ("percent" if m.group(2) == "%" else "currency" if m.group(1)
                                      else "multiple" if (m.group(2) or "").lower() in ("x", "×") else "plain"),
    }


def _bulleted(p, body_ph):
    if p._p.xpath("./a:pPr/a:buNone"):
        return False
    # shortcut: master-inherited bullets are assumed only for body placeholders; parse the master if counts look off.
    return p.level > 0 or bool(p._p.xpath("./a:pPr/a:buChar|./a:pPr/a:buAutoNum")) or body_ph


def _color(cf):
    try:
        if cf.type == MSO_COLOR_TYPE.RGB:
            return ("rgb", str(cf.rgb))
        if cf.type == MSO_COLOR_TYPE.SCHEME:
            return ("scheme", cf.theme_color.xml_value)
    except (AttributeError, TypeError, ValueError):
        pass
    return None  # shortcut: brightness/tint modifiers are ignored, so tinted brand colours map to the base slot


def _style_ref(shape, ref):
    vals = shape._element.xpath(f"./p:style/a:{ref}/a:schemeClr/@val")
    return ("scheme", vals[0]) if vals else None


def _fill(shape):
    try:
        f = shape.fill
        if f.type == MSO_FILL.SOLID:
            return _color(f.fore_color)
        if f.type == MSO_FILL.GRADIENT:
            return _color(f.gradient_stops[0].color)
        return _style_ref(shape, "fillRef") if f.type is None else None
    except (AttributeError, TypeError, NotImplementedError):
        return None


def _line(shape):
    try:
        f = shape.line.fill
        if f.type == MSO_FILL.SOLID:
            return _color(shape.line.color)
        return _style_ref(shape, "lnRef") if f.type is None else None
    except (AttributeError, TypeError, NotImplementedError):
        return None


def _dashed(shape):
    # Raw XML, not line.dash_style: python-pptx's enum has no mapping for presets like "dot" and raises.
    return (any(v != "solid" for v in shape._element.xpath("./p:spPr/a:ln/a:prstDash/@val"))
            or bool(shape._element.xpath("./p:spPr/a:ln/a:custDash")))


def _geom(shape):
    """Preset geometry name (ellipse, roundRect, ...), kept only if it is a known OOXML autoshape preset."""
    for v in shape._element.xpath("./p:spPr/a:prstGeom/@prst"):
        if v in LINE_PATHS:
            return v
        try:
            MSO_AUTO_SHAPE_TYPE.from_xml(v)
            return v
        except ValueError:
            pass
    return None


def _chromatic(hexrgb):
    r, g, b = (int(hexrgb[i:i + 2], 16) for i in (0, 2, 4))
    hi, lo = max(r, g, b), min(r, g, b)
    return lo < 240 and hi - lo >= 20 and (hi - lo) / hi >= 0.15


def _palette(raw):
    colours, sizes = Counter(), Counter()
    for regions, bg, _ in raw:
        for r in regions:
            t = r["text"] or {}
            for c in (r["fill"], r["line"], t.get("color"), bg):
                if c and c[0] == "rgb" and _chromatic(c[1]):
                    colours[c[1]] += 1
            if t.get("size_pt"):
                sizes[t["size_pt"]] += 1
    primary = min(colours, key=lambda k: (-colours[k], k)) if colours else None
    body = min(sizes, key=lambda k: (-sizes[k], k)) if sizes else 18
    return {"primary": primary, "body": body}


def _role(c, palette):
    if not c:
        return None
    kind, v = c
    if kind == "scheme":
        return SCHEME_ROLES.get(v, "accent")
    r, g, b = (int(v[i:i + 2], 16) for i in (0, 2, 4))
    if min(r, g, b) >= 240:
        return "white"
    if not _chromatic(v):
        return "neutral-dark" if (0.299 * r + 0.587 * g + 0.114 * b) / 255 < 0.5 else "neutral-light"
    return "primary" if v == palette["primary"] else "accent"


def _resolve(r, palette):
    r = dict(r, fill=_role(r["fill"], palette), line=_role(r["line"], palette))
    if r["text"]:
        t = dict(r["text"])
        pt, title_ph = t.pop("size_pt"), t.pop("title_ph")
        ratio = pt / palette["body"] if pt else None
        t["size"] = ("heading" if title_ph else "body") if ratio is None else (
            "display" if ratio >= 2.5 else "heading" if ratio >= 1.4 else "body" if ratio >= 0.85 else "caption")
        t["color"] = _role(t["color"], palette)
        r["text"] = t
    return r


def _arrow(shape):
    ends = [bool(shape._element.xpath(f"./p:spPr/a:ln/a:{e}[@type and @type != 'none']")) for e in ("headEnd", "tailEnd")]
    return {(True, False): "start", (False, True): "end", (True, True): "both"}.get(tuple(ends))


def _outline(shape, geom, w, h, area):
    """(geom, path): the outline normalised to the shape's own box, flips applied, simplified to <= MAX_PATH_POINTS.

    A near-circular freeform in a roughly square box becomes geom "ellipse"; small complex freeforms get no path.
    shortcut: rotation is ignored, so rotated freeforms draw unrotated; read a:xfrm/@rot if that shows up wrong."""
    if geom in LINE_PATHS:
        subs = [[(float(x), float(y)) for x, y in LINE_PATHS[geom]]]
    else:
        subs = _custom_path(shape, w, h)
        if not subs:
            return geom, None
        pts = [p for sub in subs for p in sub]
        if len(subs) == 1 and w and h and 0.85 <= w / h <= 1.18 and len(pts) >= 12 and all(
                0.42 <= math.dist(p, (0.5, 0.5)) <= 0.58 for p in pts):
            return "ellipse", None
        if area < SMALL_AREA and len(pts) > MAX_SMALL_POINTS:
            return geom, None
    xf = shape._element.xpath("./p:spPr/a:xfrm") or shape._element.xpath("./p:xfrm")
    fh, fv = (xf[0].get("flipH") in ("1", "true"), xf[0].get("flipV") in ("1", "true")) if xf else (False, False)
    subs = [[(1 - x if fh else x, 1 - y if fv else y) for x, y in sub] for sub in subs]
    eps = 0.005
    while True:
        out = [s for s in (_rdp(sub, eps) for sub in subs) if len(s) >= 2]
        if sum(map(len, out)) <= MAX_PATH_POINTS:
            return geom, [[[round(x, 3), round(y, 3)] for x, y in s] for s in out] or None
        if eps > 1:
            return geom, None  # too many separate pieces to outline
        eps *= 2


def _custom_path(shape, w, h):
    """Flatten a:custGeom into unit-box polylines (closed ones repeat their start); None if a point uses a guide name."""
    subs = []
    for path in shape._element.xpath("./p:spPr/a:custGeom/a:pathLst/a:path"):
        pw, ph = float(path.get("w") or w or 1) or 1, float(path.get("h") or h or 1) or 1
        cur = None
        for cmd in path:
            tag = cmd.tag.replace(A, "")
            try:
                pts = [(int(p.get("x")) / pw, int(p.get("y")) / ph) for p in cmd.findall(f"{A}pt")]
            except (TypeError, ValueError):
                return None
            if tag == "moveTo":
                cur = [pts[0]]
                subs.append(cur)
            elif cur is None:
                continue
            elif tag == "lnTo":
                cur.append(pts[0])
            elif tag in ("cubicBezTo", "quadBezTo"):
                ctrl = [cur[-1], *pts]
                cur += [_bezier(ctrl, k / 12) for k in range(1, 13)]
            elif tag == "arcTo":
                try:
                    wr, hr = int(cmd.get("wR")) / pw, int(cmd.get("hR")) / ph
                    st, sw = math.radians(int(cmd.get("stAng")) / 60000), math.radians(int(cmd.get("swAng")) / 60000)
                except (TypeError, ValueError):
                    return None
                cx, cy = cur[-1][0] - wr * math.cos(st), cur[-1][1] - hr * math.sin(st)
                cur += [(cx + wr * math.cos(st + sw * k / 12), cy + hr * math.sin(st + sw * k / 12)) for k in range(1, 13)]
            elif tag == "close":
                cur.append(cur[0])
                cur = None
    return [[(min(max(x, 0.0), 1.0), min(max(y, 0.0), 1.0)) for x, y in sub] for sub in subs if len(sub) >= 2]


def _bezier(pts, t):
    while len(pts) > 1:
        pts = [((1 - t) * a[0] + t * b[0], (1 - t) * a[1] + t * b[1]) for a, b in zip(pts, pts[1:])]
    return pts[0]


def _rdp(pts, eps):
    """Ramer-Douglas-Peucker: drop points closer than eps to the chord of their run."""
    if len(pts) < 3:
        return pts
    (ax, ay), (bx, by) = pts[0], pts[-1]
    seg = math.hypot(bx - ax, by - ay)
    dist = [abs((bx - ax) * (ay - y) - (ax - x) * (by - ay)) / seg if seg else math.hypot(x - ax, y - ay) for x, y in pts]
    k = max(range(1, len(pts) - 1), key=dist.__getitem__)
    if dist[k] <= eps:
        return [pts[0], pts[-1]]
    return _rdp(pts[:k + 1], eps)[:-1] + _rdp(pts[k:], eps)
