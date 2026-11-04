"""Agent-drawn wireframes: a layout list written from the slide PNG, snapped to extracted regions, drawn in one clean style."""
import copy
import io
import json
import math
from pathlib import Path

import jsonschema
from PIL import Image, ImageDraw, ImageFont

from pipeline import build

HERE = Path(__file__).parent
SCHEMA_PATH = HERE / "schema" / "layout.v1.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
TEMPLATE = (HERE / "templates" / "layout.txt").read_text()
SOURCE = {
    "A": "Work from the picture only: estimate every box by eye.\n",
    "B": "Extracted regions of the same slide: {regions}\n"
         "(index \"i\", type, normalised box {{x, y, w, h}}). Where an element matches one or more regions, list their\n"
         "indices in region_ids: the renderer then uses the exact union of those regions' boxes. Otherwise estimate\n"
         "the box from the picture. Give a box for every element either way.\n",
}
REGION_FIELD = {"A": "", "B": "  region_ids  optional: indices \"i\" of the extracted regions this element covers (box becomes their union)\n"}
TEXT = {"title": 22, "subtitle": 18, "text": 16, "bullets": 16, "quote": 18, "number": 24, "label": 14, "logo": 14}  # top label px at 960 wide
CONTAINERS, LINES = ("band", "panel", "card"), ("divider", "arrow", "connector")
BAND, CARD = 246, 236  # band/panel and card fills
SHAPES = {"chevron": "chevron", "arrow_right": "rightArrow", "arrow_left": "leftArrow", "arrow_up": "upArrow",
          "arrow_down": "downArrow", "triangle": "triangle", "diamond": "diamond", "ellipse": "ellipse"}  # others: rect


def validate(layout):
    """Raise ValueError unless the layout matches the schema and connectors join existing elements."""
    errors = sorted(jsonschema.Draft202012Validator(SCHEMA).iter_errors(layout), key=str)
    if errors:
        raise ValueError("; ".join(f"{'/'.join(map(str, e.path)) or 'layout'}: {e.message}" for e in errors))
    n = len(layout["elements"])
    bad = [f"elements/{k}/{end}" for k, e in enumerate(layout["elements"]) for end in ("from", "to") if e.get(end, 0) >= n]
    if bad:
        raise ValueError(f"{', '.join(bad)}: not an element index")


def snap(layout, slide):
    """Elements listing region_ids take the union of those extracted regions' boxes; the others keep the agent's box."""
    boxes = {r["i"]: r["box"] for r in slide["regions"]}
    out = copy.deepcopy(layout)
    for e in out["elements"]:
        if "region_ids" in e:
            missing = [i for i in e["region_ids"] if i not in boxes]
            if missing:
                raise ValueError(f"unknown region(s) {missing}")
            bs = [boxes[i] for i in e["region_ids"]]
            x0, y0 = min(b["x"] for b in bs), min(b["y"] for b in bs)
            e["box"] = [x0, y0, max(b["x"] + b["w"] for b in bs) - x0, max(b["y"] + b["h"] for b in bs) - y0]
    return out


def render_layout(layout):
    """Greyscale wireframe PNG of a (validated) layout list."""
    for w, h in ((960, 540), (640, 360)):
        png = _draw(layout["elements"], w, h)
        if len(png) <= build.MAX_WIREFRAME:
            return png
    raise ValueError(f"layout wireframe exceeds {build.MAX_WIREFRAME} bytes")


def _exit(box, toward):
    """Where the segment from the box centre toward a point leaves the box."""
    cx, cy = box[0] + box[2] / 2, box[1] + box[3] / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    t = min([half / abs(v) for half, v in ((box[2] / 2, dx), (box[3] / 2, dy)) if v] + [1])
    return cx + t * dx, cy + t * dy


def _path(e, els):
    """A line element's points, normalised."""
    if e.get("points"):
        return [tuple(p) for p in e["points"]]
    if e["kind"] == "connector" and "from" in e and "to" in e:
        a, b = els[e["from"]]["box"], els[e["to"]]["box"]
        return [_exit(a, (b[0] + b[2] / 2, b[1] + b[3] / 2)), _exit(b, (a[0] + a[2] / 2, a[1] + a[3] / 2))]
    x, y, w, h = e["box"]
    across, down = [(x, y + h / 2), (x + w, y + h / 2)], [(x + w / 2, y), (x + w / 2, y + h)]
    return {"arrow_left": across[::-1], "arrow_up": down[::-1], "arrow_down": down, "arrow_right": across}.get(
        e["shape"], across if w >= h else down)


def _outline(e, box, s, W, H):
    """Closed outline polylines of a framed or container element, in pixels."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    if e["shape"] in ("polygon", "line") and e.get("points"):
        pts = [(x * W, y * H) for x, y in e["points"]]
        return [pts + [pts[0]] if e["shape"] == "polygon" else pts]
    if e["shape"] == "line":
        return [[(x0, y0 + h / 2), (x1, y0 + h / 2)] if w >= h else [(x0 + w / 2, y0), (x0 + w / 2, y1)]]
    if e["shape"] == "round_rect" or (e["kind"] in ("card", "panel") and e["shape"] in ("none", "rect", "polygon")):
        local = [build._rounded(w, h, min(10 * s, w / 4, h / 4))]
    else:
        local = build._preset(SHAPES.get(e["shape"], "rect"), w, h)
    return [[(x0 + x, y0 + y) for x, y in pl] for pl in local]


def _draw(els, W, H):
    s = W / 960
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    px = lambda b: (b[0] * W, b[1] * H, max(min(b[0] + b[2], 1) * W, b[0] * W + 1), max(min(b[1] + b[3], 1) * H, b[1] * H + 1))
    width = lambda e: max(1, round((3 if e.get("emphasis") in ("strong", "hero") else 2) * s))
    rank = lambda e: 0 if e["kind"] in ("band", "panel") else 1 if e["kind"] == "card" else 3 if e["kind"] in LINES else 2
    for e in sorted((e for e in els if e["kind"] not in TEXT), key=rank):  # bands/panels, cards, frames, lines
        if e["kind"] in LINES:
            pts = [(x * W, y * H) for x, y in _path(e, els)]
            head = None
            if e["kind"] != "divider" and pts[-1] != pts[-2]:
                (ax, ay), (bx, by) = pts[-2], pts[-1]
                a, size, half = math.atan2(by - ay, bx - ax), 11 * s + width(e), 4 * s + width(e)
                base = (bx - size * math.cos(a), by - size * math.sin(a))
                head = [(bx, by), (base[0] - half * math.sin(a), base[1] + half * math.cos(a)),
                        (base[0] + half * math.sin(a), base[1] - half * math.cos(a))]
                if math.hypot(bx - ax, by - ay) > size:
                    pts[-1] = base  # the line stops where the head begins
            build._stroke(d, pts, width(e), e.get("dashed", False), s)
            if head:
                d.polygon(head, fill=build.INK)
            continue
        outline = _outline(e, px(e["box"]), s, W, H)
        if e["kind"] in CONTAINERS:
            for pl in outline:
                if len(pl) > 2:
                    d.polygon(pl, fill=CARD if e["kind"] == "card" else BAND)
            if not (e.get("dashed") or e.get("emphasis") in ("strong", "hero")):
                continue
        for pl in outline:
            build._stroke(d, pl, width(e), e.get("dashed", False), s)
    placed = []
    for e in sorted((e for e in els if e["kind"] not in CONTAINERS + LINES), key=lambda e: e["box"][2] * e["box"][3]):
        x0, y0, x1, y1 = px(e["box"])
        label, framed = f"[{e['kind'].replace('_', ' ')}]", e["kind"] not in TEXT
        top = TEXT.get(e["kind"], 16)
        if e.get("emphasis") == "hero" and e["kind"] == "number":
            top = 56
        elif e.get("emphasis") in ("strong", "hero"):
            top = round(top * 1.25)
        inset = 0.7 if framed and e["shape"] in ("ellipse", "diamond", "triangle") else 1.0
        pad = 2 * width(e) + 8 * s if framed else 4 * s
        room_w, room_h = (x1 - x0) * inset - pad, (y1 - y0) * inset - (8 * s if framed else 0)
        for size in range(min(top, int(room_h / 1.2 / s)), 7, -1):  # shrink to fit, omit below 8px
            font = ImageFont.load_default(size=round(size * s))
            tw = d.textlength(label, font=font)
            if tw <= room_w:
                break
        else:
            continue
        centred = framed or e["kind"] == "number"
        at = ((x0 + x1) / 2, (y0 + y1) / 2) if centred else (x0 + pad / 2, (y0 + y1) / 2)
        spot = (at[0] - (tw / 2 if centred else 0), at[1] - font.size * 0.7, tw, font.size * 1.4)
        if any(build._overlap(spot, o) for o in placed):  # never print over another label; the innermost wins
            continue
        d.text(at, label, fill=build.INK, font=font, anchor="mm" if centred else "lm")
        placed.append(spot)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def prep(deck_id, library, slides=None, variant="A"):
    """Write one layout worksheet per slide (or only the listed slide numbers); return the output folder."""
    work, out = Path(library).absolute() / "work" / deck_id, Path(library).absolute() / "layouts" / deck_id
    out.mkdir(parents=True, exist_ok=True)
    el = SCHEMA["$defs"]["element"]["properties"]
    for f in sorted(work.glob("slide-??.json")):
        if slides and f.stem[-2:] not in slides:
            continue
        (out / f"{f.stem}.{variant}.prompt.txt").write_text(TEMPLATE.format(
            png=work / f"{f.stem}.png", out=out / f"{f.stem}.{variant}.json", schema=SCHEMA_PATH,
            source=SOURCE[variant].format(regions=f), region_field=REGION_FIELD[variant],
            kinds=", ".join(el["kind"]["enum"]), shapes=", ".join(el["shape"]["enum"]), emphases=", ".join(el["emphasis"]["enum"])))
    return out


def render(deck_id, library, variant="A"):
    """Validate every slide-NN.<variant>.json, snap it to the extracted regions, then write slide-NN.<variant>.png."""
    work, out = Path(library) / "work" / deck_id, Path(library) / "layouts" / deck_id
    layouts, errors = {}, []
    for f in sorted(out.glob(f"slide-??.{variant}.json")):
        try:
            lay = json.loads(f.read_text())
            validate(lay)
            if any("region_ids" in e for e in lay["elements"]):
                lay = snap(lay, json.loads((work / f"{f.name[:8]}.json").read_text()))
            layouts[f] = lay
        except ValueError as e:
            errors.append(f"{f.name}: {e}")
    if errors:
        raise ValueError("\n".join(errors))
    for f, lay in layouts.items():
        f.with_suffix(".png").write_bytes(render_layout(lay))
    return [f.with_suffix(".png") for f in layouts]
