"""Stage 3: merge geometry + labels into design-DNA records, draw each wireframe from the record alone, write descriptions."""
import io
import itertools
import json
from pathlib import Path

import jsonschema
from PIL import Image, ImageDraw, ImageFont
from referencing import Registry, Resource

from pipeline import label_prep

HERE = Path(__file__).parent
SCHEMA = json.loads((HERE / "schema" / "design-dna.v1.json").read_text())
_REGISTRY = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in (SCHEMA, label_prep.SCHEMA)])
DESCRIPTION_VERSION = "desc-v1"
MAX_WIREFRAME = 30 * 1024
LABELS = {"title": "title", "tagline": "subtitle", "subtitle": "subtitle", "section-label": "label", "body": "text",
          "bullet-list": "bullets", "big-number": "number", "number-label": "label", "chart": "chart", "table": "table",
          "image": "image", "icon": "icon", "logo": "logo", "callout": "quote", "label": "label", "footer": "label",
          "source-note": "label", "page-number": "label"}  # card, other and unknown roles fall back on the region type
CHARTS = (("PIE", "pie"), ("DOUGHNUT", "doughnut"), ("SCATTER", "scatter"), ("BUBBLE", "bubble"), ("RADAR", "radar"),
          ("STOCK", "stock"), ("SURFACE", "surface"), ("AREA", "area"), ("LINE", "line"), ("BAR", "bar"),
          ("COLUMN", "bar"), ("CONE", "bar"), ("CYLINDER", "bar"), ("PYRAMID", "bar"))  # first match wins: BAR_OF_PIE is a pie
ELLIPSES = {"ellipse", "flowChartConnector", "donut"}
KEEP_TINY = {"[number]", "[icon]", "[logo]"}
STACK = {"[title]": "title", "[subtitle]": "subtitle", "[text]": "text", "[bullets]": "text", "[quote]": "quote",
         "[label]": "label"}  # labels whose stacked line boxes join into one block; text joins bullets
MIN_AREA, BAND_AREA, SAME_BOX = 0.004, 0.15, 0.8  # fractions of the slide; SAME_BOX of the larger box
STACK_GAP = 0.01  # of slide height: line boxes of one paragraph touch, separate blocks sit a blank line apart
INK, BAND = 110, 242
SKIP_ROLES = {"group", "decoration", "other"}


def check_schema(dna):
    jsonschema.Draft202012Validator(SCHEMA, registry=_REGISTRY).validate(dna)


def run(deck_id, library):
    """Build every labelled slide of a deck into work/<deck_id>/build/. Refuses if any label is missing or invalid."""
    work = Path(library) / "work" / deck_id
    pairs, errors = [], []
    for f in sorted(work.glob("slide-??.json")):
        slide, lf = json.loads(f.read_text()), work / "labels" / f.name
        try:
            labels = json.loads(lf.read_text())
            label_prep.validate(labels, slide)
            pairs.append((slide, labels))
        except (OSError, ValueError) as e:
            errors.append(f"{lf.relative_to(work)}: {e}")
    if errors:
        raise SystemExit("Labels missing or invalid, nothing built:\n" + "\n".join(errors))
    out = work / "build"
    out.mkdir(exist_ok=True)
    ids = []
    for slide, labels in pairs:
        dna = merge(slide, labels)
        check_schema(dna)
        (out / f"{dna['id']}.json").write_text(json.dumps(dna, indent=1))
        (out / f"{dna['id']}.png").write_bytes(wireframe(dna))
        ids.append(dna["id"])
    return ids


def merge(slide, labels):
    patterns = {t["region"]: t for t in labels["text_patterns"]}
    regions = []
    for r in slide["regions"]:
        r = dict(r, role=labels["regions"][str(r["i"])])
        if r["text"]:
            p = patterns.get(r["i"])
            r["text"] = dict(r["text"], pattern=p and p["pattern"], pattern_words=p and p["words"])
        regions.append(r)
    dna = {"schema_version": "design-dna/v1", "id": f"{slide['deck_id']}-{slide['slide']:02d}",
           "deck_id": slide["deck_id"], "slide": slide["slide"],
           **{k: labels[k] for k in ("archetype", "purpose", "argument_shape", "insight_device", "data_type",
                                      "industry", "why_it_works")},
           "background": slide["background"], "regions": regions}
    dna["description"] = describe(dna)
    return {k: dna[k] for k in SCHEMA["required"]}


def describe(dna):
    """Fixed template (DESCRIPTION_VERSION). Uses labels and roles only, never counts, so it holds no digits."""
    words = lambda s: s.replace("-", " ")
    roles = list(dict.fromkeys(words(r["role"]) for r in dna["regions"] if r["role"] not in SKIP_ROLES))
    patterns = [r["text"]["pattern"] for r in dna["regions"] if r["text"] and r["text"]["pattern"]]
    return (f"{words(dna['archetype']).capitalize()} slide. {words(dna['argument_shape']).capitalize()} argument, "
            f"{words(dna['insight_device'])} device, {words(dna['data_type'])} data, {words(dna['industry'])}. "
            f"Purpose: {dna['purpose'].rstrip('.')}. Why it works: {dna['why_it_works'].rstrip('.')}. "
            f"Layout: {', '.join(roles)}." + (f" Text: {'; '.join(patterns)}." if patterns else ""))


def wireframe(dna):
    """Greyscale content-free skeleton of the slide, drawn from the DNA record only."""
    for w, h in ((960, 540), (640, 360)):
        png = _draw(dna, w, h)
        if len(png) <= MAX_WIREFRAME:
            return png
    raise ValueError(f"wireframe for {dna['id']} exceeds {MAX_WIREFRAME} bytes")


def _label(r):
    if r["chart"]:
        return "[" + next((name + " chart" for key, name in CHARTS if key in r["chart"]["kind"]), "chart") + "]"
    if r["table"]:
        return "[table]"
    if r["role"] == "body" and r["text"] and r["text"]["bullets"]:
        return "[bullets]"
    return "[" + (LABELS.get(r["role"]) or ("text" if r["text"] else "image" if r["type"] == "picture" else "shape")) + "]"


def _plan(dna):
    """What the wireframe shows: light panels, thin lines and labelled boxes, minus decoration, specks and duplicates."""
    bands, lines, boxes = [], [], []
    for r in dna["regions"]:
        b, role = r["box"], r["role"]
        x, y, w, h = box = (b["x"], b["y"], b["w"], b["h"])
        area = w * h
        if r["type"] == "group" or role == "group":
            continue
        if r["type"] == "line" or role in ("divider", "connector"):
            if role != "decoration":  # shortcut: connector flips are not in the DNA, so diagonals may draw mirrored
                xy = (x, y, x + w, y + h) if r["type"] == "line" else (
                    (x, y + h / 2, x + w, y + h / 2) if w >= h else (x + w / 2, y, x + w / 2, y + h))
                lines.append({"i": r["i"], "kind": "line", "xy": xy, "box": box, "label": None})
            continue
        x0, y0 = max(x, 0), max(y, 0)  # boxes hanging off the slide are drawn and labelled by their visible part
        box = (x0, y0, max(min(x + w, 1) - x0, 0), max(min(y + h, 1) - y0, 0))
        area = box[2] * box[3]
        if role in ("decoration", "background-band"):
            big = area > BAND_AREA or (role == "background-band" and area >= MIN_AREA)
            if big and area < 0.9 and (r["fill"] or r["type"] == "picture"):  # >= 90% is the slide itself
                bands.append({"i": r["i"], "kind": "band", "box": box, "label": None})
            continue
        geom = r.get("geom") or ""
        kind = "ellipse" if geom in ELLIPSES else "round" if "round" in geom.lower() or geom == "flowChartAlternateProcess" else "rect"
        boxes.append({"i": r["i"], "kind": kind, "box": box, "label": _label(r)})
    joined = True
    while joined:  # many decks put each line of text in its own box: join same-kind boxes stacked with no real gap
        joined = False
        for a, b in itertools.combinations(boxes, 2):
            if a["label"] in STACK and STACK.get(a["label"]) == STACK.get(b["label"]) and _stacked(a["box"], b["box"]):
                x0, y0 = min(a["box"][0], b["box"][0]), min(a["box"][1], b["box"][1])
                x1 = max(a["box"][0] + a["box"][2], b["box"][0] + b["box"][2])
                y1 = max(a["box"][1] + a["box"][3], b["box"][1] + b["box"][3])
                a.update(i=min(a["i"], b["i"]), box=(x0, y0, x1 - x0, y1 - y0), label="[bullets]" if "[bullets]" in (a["label"], b["label"]) else a["label"])
                boxes.remove(b)
                joined = True
                break
    boxes = [c for c in boxes if c["box"][2] * c["box"][3] >= MIN_AREA or c["label"] in KEEP_TINY]
    kept = []
    for c in sorted(boxes, key=lambda c: -c["box"][2] * c["box"][3]):
        same = next((k for k in kept if _overlap(k["box"], c["box"]) > SAME_BOX * k["box"][2] * k["box"][3]), None)
        if same is None:
            kept.append(c)
        elif same["label"] == "[shape]":
            same["label"] = c["label"]
    for k in kept:  # a plain container's label would collide with the labels inside it
        if k["label"] == "[shape]" and any(o is not k and _inside(o["box"], k["box"]) for o in kept):
            k["label"] = None
    return bands + lines + sorted(kept, key=lambda c: c["i"])


def _overlap(a, b):
    return max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])) * max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))


def _stacked(a, b):
    """Overlapping columns, and vertically touching or overlapping (a gap under a line's leading)."""
    across = min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0])
    gap = max(a[1], b[1]) - min(a[1] + a[3], b[1] + b[3])
    return across > 0 and gap <= STACK_GAP


def _inside(a, b):
    """Centre of box a lies in box b."""
    cx, cy = a[0] + a[2] / 2, a[1] + a[3] / 2
    return b[0] <= cx <= b[0] + b[2] and b[1] <= cy <= b[1] + b[3]


def _draw(dna, W, H):
    s = W / 960
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    stroke = max(1, round(2 * s))
    plan = _plan(dna)
    for p in plan:
        x, y, w, h = p["box"]
        box = (x * W, y * H, x * W + max(w * W, 1), y * H + max(h * H, 1))
        if p["kind"] == "band":
            d.rectangle(box, fill=BAND)
        elif p["kind"] == "line":
            x0, y0, x1, y1 = p["xy"]
            d.line((x0 * W, y0 * H, x1 * W, y1 * H), fill=INK, width=stroke)
        elif p["kind"] == "ellipse":
            d.ellipse(box, outline=INK, width=stroke)
        elif p["kind"] == "round":
            d.rounded_rectangle(box, radius=min(10 * s, (box[2] - box[0]) / 2, (box[3] - box[1]) / 2), outline=INK, width=stroke)
        else:
            d.rectangle(box, outline=INK, width=stroke)
    placed = []  # (label spot, its box) as pixel x, y, w, h
    for p in sorted((p for p in plan if p["label"]), key=lambda p: p["box"][2] * p["box"][3]):  # innermost first
        x, y, w, h = p["box"]
        inset = 0.7 if p["kind"] == "ellipse" else 1.0  # widest text that fits inside the ellipse
        room_w, room_h = w * W * inset - 2 * stroke - 8 * s, h * H * inset - 2 * stroke - 4 * s
        for size in range(min(18, int(room_h / 1.3 / s)), 7, -1):  # shrink to fit, give up below 8px
            font = ImageFont.load_default(size=round(size * s))
            tw = d.textlength(p["label"], font=font)
            if tw <= room_w:
                cx, cy, half = (x + w / 2) * W, (y + h / 2) * H, font.size * 0.7
                spot, mine = (cx - tw / 2, cy - half, tw, 2 * half), (x * W, y * H, w * W, h * H)
                # never print over another label, nor over a labelled box inside this one
                if not any(_overlap(spot, o) or (_inside(ob, mine) and _overlap(spot, ob)) for o, ob in placed):
                    d.text((cx, cy), p["label"], fill=INK, font=font, anchor="mm")
                    placed.append((spot, mine))
                break
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()
