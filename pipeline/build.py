"""Stage 3: merge geometry + labels into design-DNA records, draw each wireframe from the record alone, write descriptions."""
import collections
import io
import itertools
import json
import math
from pathlib import Path

import jsonschema
from PIL import Image, ImageDraw, ImageFont
from referencing import Registry, Resource

from pipeline import label_prep

HERE = Path(__file__).parent
SCHEMA = json.loads((HERE / "schema" / "design-dna.v1.json").read_text())
_REGISTRY = Registry().with_resources([(s["$id"], Resource.from_contents(s)) for s in (SCHEMA, label_prep.SCHEMA)])
DESCRIPTION_VERSION = "desc-v2"  # v2: impact slides add what their impact frame is for
MAX_WIREFRAME = 30 * 1024
LABELS = {"title": "title", "tagline": "subtitle", "subtitle": "subtitle", "section-label": "label", "body": "text",
          "bullet-list": "bullets", "big-number": "number", "number-label": "label", "chart": "chart", "table": "table",
          "image": "image", "icon": "icon", "logo": "logo", "callout": "quote", "label": "label", "footer": "label",
          "source-note": "label", "page-number": "label"}  # card, other and unknown roles fall back on the region type
CHARTS = (("PIE", "pie"), ("DOUGHNUT", "doughnut"), ("SCATTER", "scatter"), ("BUBBLE", "bubble"), ("RADAR", "radar"),
          ("STOCK", "stock"), ("SURFACE", "surface"), ("AREA", "area"), ("LINE", "line"), ("BAR", "bar"),
          ("COLUMN", "bar"), ("CONE", "bar"), ("CYLINDER", "bar"), ("PYRAMID", "bar"))  # first match wins: BAR_OF_PIE is a pie
KEEP_TINY = {"[number]", "[icon]", "[logo]"}
TEXT_LABELS = {"[title]", "[subtitle]", "[text]", "[bullets]", "[quote]", "[number]", "[label]", "[logo]", "[icon]"}
NEVER_TRACED = {"logo", "icon"}  # brand marks: drawn as their bracket label only, so no outline can leak them
SMALL_AREA, MAX_SMALL_POINTS = 0.03, 12  # a small freeform with more points than this is not traced either
LARGE, ALIKE, TOUCH = 0.08, 0.15, 0.02  # large shape; size tolerance of a repeat; how near a line end touches a box
STACK = {"[title]": "title", "[subtitle]": "subtitle", "[text]": "text", "[bullets]": "text", "[quote]": "quote",
         "[label]": "label"}  # labels whose stacked line boxes join into one block; text joins bullets
MIN_AREA, BAND_AREA, SAME_BOX = 0.004, 0.15, 0.8  # fractions of the slide; SAME_BOX of the larger box
STACK_GAP = 0.01  # of slide height: line boxes of one paragraph touch, separate blocks sit a blank line apart
INK, BAND = 110, 242
SKIP_ROLES = {"group", "decoration", "other"}
SHAPES = {"shape", "picture", "group"}
CLUSTER_AREA, CLUSTER_SPAN, CLUSTER_MIN = 0.01, 0.1, 5  # a small shape: < 1% of the slide and no side over 10%
MAX_HOLDER, TOUCH_GAP, MARK_GAP = 0.5, 0.002, 0.05  # fractions of the slide
CLUSTER_ROLES = {"logo", "icon", "chart", "image"}  # a cluster keeps its majority role if it is one of these, else image
LOOSE_ROLES = {"other", "decoration", "image", "icon", "logo"}  # what a cluster takes in; cards, callouts... stay


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
        r = dict(r, role=labels["regions"].get(str(r["i"]), "other"))  # beyond the worksheet's largest regions
        r.pop("path", None)  # no freeform outline reaches a record: it could trace a map or a wordmark
        if r["role"] in NEVER_TRACED:
            r["geom"] = None  # nor a brand mark's preset
        if r["text"]:
            p = patterns.get(r["i"])
            r["text"] = dict(r["text"], pattern=p and p["pattern"], pattern_words=p and p["words"])
        regions.append(r)
    regions = _collapse(regions)
    dna = {"schema_version": "design-dna/v1", "id": f"{slide['deck_id']}-{slide['slide']:02d}",
           "deck_id": slide["deck_id"], "slide": slide["slide"],
           **{k: labels[k] for k in ("archetype", "purpose", "argument_shape", "insight_device", "data_type",
                                      "industry", "why_it_works")},
           "background": slide["background"], "regions": regions}
    dna["description"] = describe(dna)
    return {k: dna[k] for k in SCHEMA["required"]}


def _collapse(regions):
    """Geometry that could trace a brand or a market collapses into plain, unshaded boxes:
    - >= CLUSTER_MIN small shapes (lines and long thin rules aside) in one connected area (boxes touching, or inside
      one image or logo region) become one box with every smaller loose shape centred in it: a map with its shading
      and pins, a wordmark; clusters whose boxes then touch join, until none do;
    - logos and icons within MARK_GAP of each other become one box."""
    weight = {}  # small shapes folded into a cluster so far, by the cluster's index
    small = lambda r: r["type"] in SHAPES and not r["text"] and not _is_line(r) and (
        r["box"]["w"] * r["box"]["h"] < CLUSTER_AREA and max(r["box"]["w"], r["box"]["h"]) < CLUSTER_SPAN)
    count = lambda r: weight.get(r["i"], int(small(r)))
    holder = lambda r: r["type"] in SHAPES and r["role"] in ("image", "logo") and (
        CLUSTER_AREA <= r["box"]["w"] * r["box"]["h"] <= MAX_HOLDER)  # a full-bleed photo holds nothing
    linked = lambda a, b: _gap(a, b) <= TOUCH_GAP if count(a) and count(b) else bool(count(a)) != bool(count(b)) and (
        _inside(_xywh(a), _xywh(b)) if count(a) else _inside(_xywh(b), _xywh(a)))
    majority = lambda c: collections.Counter(r["role"] for r in sorted(c, key=lambda r: r["i"])).most_common(1)[0][0]
    folded = True
    while folded:
        folded = False
        for c in _components([r for r in regions if count(r) or holder(r)], linked):
            ids = {r["i"] for r in c}
            c = [r for r in regions if r["i"] in ids]  # what an earlier cluster has not taken in
            if sum(map(count, c)) >= CLUSTER_MIN and len(c) > 1:
                x0, y0, x1, y1 = _bounds(c)
                box = (x0, y0, x1 - x0, y1 - y0)  # takes in smaller shapes centred in it: shading, pins, big countries
                c += [r for r in regions if r["type"] in SHAPES and r["role"] in LOOSE_ROLES and not r["text"]
                      and r["i"] not in ids and _inside(_xywh(r), box) and r["box"]["w"] * r["box"]["h"] < box[2] * box[3]]
                role = majority(c) if majority(c) in CLUSTER_ROLES else "image"
                regions = _fold(regions, c, role, "picture" if role == "image" else None)
                weight[min(r["i"] for r in c)], folded = sum(map(count, c)), True
    for c in _components([r for r in regions if r["role"] in NEVER_TRACED], lambda a, b: _gap(a, b) <= MARK_GAP):
        if len(c) > 1:
            regions = _fold(regions, c, majority(c), None)
    return regions


def _components(items, linked):
    """Connected sets of items (in item order); deterministic for a given order."""
    comps = []
    for r in items:
        hit = [c for c in comps if any(linked(r, o) for o in c)]
        comps = [c for c in comps if all(c is not h for h in hit)] + [[o for h in hit for o in h] + [r]]
    return sorted(comps, key=lambda c: min(r["i"] for r in c))


def _fold(regions, members, role, type_):
    """Replace members by one box at the first member: the union box, role, no fill, outline, text or data."""
    ids, base = {r["i"] for r in members}, min(members, key=lambda r: r["i"])
    x0, y0, x1, y1 = _bounds(members)
    rep = dict(base, type=type_ or base["type"], role=role, parent=None if base["parent"] in ids else base["parent"],
               box={"x": x0, "y": y0, "w": round(x1 - x0, 4), "h": round(y1 - y0, 4)}, fill=None, line=None,
               dashed=False, text=None, chart=None, table=None, **{k: None for k in ("geom", "arrow") if k in base})
    return [rep if r["i"] == base["i"] else dict(r, parent=base["i"] if r["parent"] in ids else r["parent"])
            for r in regions if r["i"] == base["i"] or r["i"] not in ids]


def _is_line(r):
    geom = r.get("geom") or ""
    return r["type"] == "line" or r["role"] in ("divider", "connector") or geom == "line" or "Connector" in geom


def _bounds(regions):
    return (min(r["box"]["x"] for r in regions), min(r["box"]["y"] for r in regions),
            max(r["box"]["x"] + r["box"]["w"] for r in regions), max(r["box"]["y"] + r["box"]["h"] for r in regions))


def _xywh(r):
    return r["box"]["x"], r["box"]["y"], r["box"]["w"], r["box"]["h"]


def _gap(a, b):
    """The wider of the horizontal and vertical gaps between two boxes; negative when they overlap."""
    (ax0, ay0, ax1, ay1), (bx0, by0, bx1, by1) = _bounds([a]), _bounds([b])
    return max(max(ax0, bx0) - min(ax1, bx1), max(ay0, by0) - min(ay1, by1))


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
    """What the wireframe shows, decided from the record alone:
    - text, numbers, logos and icons are plain labels with no frame; logos, icons and small complex freeforms are
      never traced;
    - images, charts and tables are framed (images in their own outline);
    - other shapes are framed only when the shape matters: containers of labelled regions, insight regions (dashed,
      callouts, highlights on highlight devices), repeats (>= 3 alike; 2 on option grids; unlabelled shapes of a kind
      stacked more than half over each other are texture and never matter), shapes a line ends at, or large (> 8%);
    - lines and connectors stay; big filled decoration becomes a light panel; tiny shapes only stay on a line.
    Context: option grids keep pairs, journeys and sequences keep decorative connectors, executive summaries keep
    their row bands."""
    grid = dna.get("archetype") == "options" or dna.get("insight_device") == "matrix-position"
    path_like = dna.get("archetype") in ("customer-journey", "implementation") or dna.get("argument_shape") in (
        "sequence", "timeline") or dna.get("data_type") in ("process", "timeline")
    rows = dna.get("archetype") == "executive-summary"
    highlight = dna.get("insight_device") in ("highlight-contrast", "callout-annotation", "spotlight")
    bands, lines, boxes = [], [], []
    for r in dna["regions"]:
        b, role, geom, path = r["box"], r["role"], r.get("geom") or "", r.get("path")
        x, y, w, h = (b["x"], b["y"], b["w"], b["h"])
        if r["type"] == "group" or role == "group":
            continue
        if _is_line(r):
            if role != "decoration" or path_like:
                pts = [(x + px * w, y + py * h) for px, py in path[0]] if path else (
                    [(x, y), (x + w, y + h)] if r["type"] == "line" else
                    [(x, y + h / 2), (x + w, y + h / 2)] if w >= h else [(x + w / 2, y), (x + w / 2, y + h)])
                lines.append({"i": r["i"], "kind": "line", "pts": pts, "arrow": r.get("arrow"), "dashed": r["dashed"],
                              "box": (x, y, w, h), "label": None})
            continue
        x0, y0 = max(x, 0), max(y, 0)  # boxes hanging off the slide are drawn and labelled by their visible part
        box = (x0, y0, max(min(x + w, 1) - x0, 0), max(min(y + h, 1) - y0, 0))
        area = box[2] * box[3]
        if role in ("decoration", "background-band") and (r["fill"] or r["type"] == "picture"):
            big = area > BAND_AREA or (area >= MIN_AREA and (role == "background-band" or (rows and box[2] >= 0.5)))
            if big and area < 0.9:  # >= 90% is the slide itself
                bands.append({"i": r["i"], "kind": "band", "box": box, "label": None})
            if big or role == "background-band":
                continue
        traced = role not in NEVER_TRACED and not (path and area < SMALL_AREA and sum(map(len, path)) > MAX_SMALL_POINTS)
        shown = role not in NEVER_TRACED and bool(r["fill"] or r["line"] or r["type"] == "picture")
        visible = traced and shown  # untraced shapes still count as repeats, but draw as their label only
        boxes.append({"i": r["i"], "kind": "shape", "box": box, "label": None if role == "decoration" else _label(r),
                      "geom": (geom or None) if traced else None, "path": path if traced else None, "dashed": r["dashed"],
                      "visible": visible, "shown": shown, "holds": False, "frame": False,
                      "insight": visible and (r["dashed"] or role == "callout" or (
                          highlight and role != "decoration" and r["fill"] in ("primary", "accent")))})
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
    kept = []
    for c in sorted(boxes, key=lambda c: -c["box"][2] * c["box"][3]):
        same = next((k for k in kept if _overlap(k["box"], c["box"]) > SAME_BOX * k["box"][2] * k["box"][3]), None)
        if same is None:
            kept.append(c)
        elif same["label"] in ("[shape]", None) and c["label"]:
            same.update(label=c["label"], holds=True)
    key = lambda c: c["geom"] if c["geom"] not in (None, "rect") or c["path"] else "rect"
    alike = lambda a, b: key(a) == key(b) and all(abs(a["box"][k] - b["box"][k]) <= ALIKE * max(a["box"][k], b["box"][k]) for k in (2, 3))
    out = []
    for c in kept:
        area = c["box"][2] * c["box"][3]
        twins = [o for o in kept if o is not c and o["shown"] and alike(c, o)]
        texture = c["label"] is None and any(  # unlabelled stripes or rings stacked on each other; a Venn overlaps less
            o is not c and o["label"] is None and o["shown"] and key(o) == key(c)
            and _overlap(c["box"], o["box"]) > 0.5 * min(area, o["box"][2] * o["box"][3]) for o in kept)
        on_line = any(_near(p, c["box"]) for ln in lines for p in (ln["pts"][0], ln["pts"][-1])) or (
            area < MIN_AREA and any(_through(ln["pts"], c["box"]) for ln in lines))
        matters = on_line or (area >= MIN_AREA and not texture and (
            c["holds"] or c["insight"] or area > LARGE
            or any(o is not c and o["label"] and _inside(o["box"], c["box"]) and o["box"][2] * o["box"][3] < area for o in kept)
            or (c["shown"] and len(twins) + 1 >= (2 if grid else 3))))
        if area < MIN_AREA and c["label"] not in KEEP_TINY and not matters:
            continue  # a tiny isolated ornament
        if c["label"] in TEXT_LABELS:
            c["frame"] = c["visible"] and matters  # text inside a shape that matters, e.g. a chevron in a row
        elif c["label"] == "[image]":
            c["frame"] = c["visible"]
        elif c["label"] == "[table]" or (c["label"] or "").endswith("chart]"):
            c["frame"] = True
        elif not matters:
            continue
        else:
            c["frame"] = c["visible"]
        if c["frame"] or c["label"]:
            out.append(c)
    for c in out:  # a cut-out photo on its own circle or card: the shape carries the outline, the photo its label
        if c["label"] == "[image]" and any(
                o["frame"] and o["label"] in ("[shape]", None) and o["box"][2] * o["box"][3] < c["box"][2] * c["box"][3]
                and _overlap(c["box"], o["box"]) >= SAME_BOX * o["box"][2] * o["box"][3] for o in out):
            c["frame"] = False
    for k in out:  # a plain container's label would collide with the labels inside it
        if k["label"] == "[shape]" and any(o is not k and _inside(o["box"], k["box"]) for o in out):
            k["label"] = None
    return bands + lines + sorted((c for c in out if c["frame"] or c["label"]), key=lambda c: c["i"])


def _through(pts, box):
    """A polyline passes within half the box size of the box centre."""
    cx, cy, reach = box[0] + box[2] / 2, box[1] + box[3] / 2, max(box[2], box[3]) / 2
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        t = max(0, min(1, ((cx - ax) * dx + (cy - ay) * dy) / (dx * dx + dy * dy))) if dx or dy else 0
        if math.hypot(ax + t * dx - cx, ay + t * dy - cy) <= reach:
            return True
    return False


def _near(p, box):
    return box[0] - TOUCH <= p[0] <= box[0] + box[2] + TOUCH and box[1] - TOUCH <= p[1] <= box[1] + box[3] + TOUCH


def _ring(cx, cy, rx, ry, a0=0, a1=360, n=48):
    pts = [(cx + rx * math.cos(math.radians(a0 + (a1 - a0) * k / n)), cy + ry * math.sin(math.radians(a0 + (a1 - a0) * k / n)))
           for k in range(n + 1)]
    return pts[:-1] + [pts[0]] if a1 - a0 == 360 else pts


def _rounded(w, h, r, n=6):
    pts = []
    for cx, cy, a in ((w - r, r, 270), (w - r, h - r, 0), (r, h - r, 90), (r, r, 180)):
        pts += _ring(cx, cy, r, r, a, a + 90, n)
    return pts + [pts[0]]


def _poly(*pts):
    return [list(pts) + [pts[0]]]


def _preset(geom, w, h):
    """Outline of an OOXML preset at its default adjustments, as closed/open polylines in local (0..w, 0..h) pixels."""
    ss = min(w, h)
    a = ss / 2
    shapes = {
        "triangle": lambda: _poly((w / 2, 0), (w, h), (0, h)),
        "flowChartExtract": lambda: _poly((w / 2, 0), (w, h), (0, h)),
        "flowChartMerge": lambda: _poly((0, 0), (w, 0), (w / 2, h)),
        "rtTriangle": lambda: _poly((0, 0), (w, h), (0, h)),
        "diamond": lambda: _poly((w / 2, 0), (w, h / 2), (w / 2, h), (0, h / 2)),
        "pentagon": lambda: _poly((w / 2, 0), (w, 0.38 * h), (0.81 * w, h), (0.19 * w, h), (0, 0.38 * h)),
        "homePlate": lambda: _poly((0, 0), (w - a, 0), (w, h / 2), (w - a, h), (0, h)),
        "chevron": lambda: _poly((0, 0), (w - a, 0), (w, h / 2), (w - a, h), (0, h), (a, h / 2)),
        "hexagon": lambda: _poly((ss / 4, 0), (w - ss / 4, 0), (w, h / 2), (w - ss / 4, h), (ss / 4, h), (0, h / 2)),
        "octagon": lambda: (lambda c: _poly((c, 0), (w - c, 0), (w, c), (w, h - c), (w - c, h), (c, h), (0, h - c), (0, c)))(0.29289 * ss),
        "parallelogram": lambda: _poly((ss / 4, 0), (w, 0), (w - ss / 4, h), (0, h)),
        "flowChartInputOutput": lambda: _poly((w / 5, 0), (w, 0), (w - w / 5, h), (0, h)),
        "trapezoid": lambda: _poly((0, h), (ss / 4, 0), (w - ss / 4, 0), (w, h)),
        "flowChartManualOperation": lambda: _poly((0, 0), (w, 0), (w - w / 5, h), (w / 5, h)),
        "flowChartManualInput": lambda: _poly((0, h / 5), (w, 0), (w, h), (0, h)),
        "flowChartOffpageConnector": lambda: _poly((0, 0), (w, 0), (w, 0.8 * h), (w / 2, h), (0, 0.8 * h)),
        "rightArrow": lambda: _poly((0, h / 4), (w - a, h / 4), (w - a, 0), (w, h / 2), (w - a, h), (w - a, 3 * h / 4), (0, 3 * h / 4)),
        "notchedRightArrow": lambda: _poly((0, h / 4), (w - a, h / 4), (w - a, 0), (w, h / 2), (w - a, h), (w - a, 3 * h / 4),
                                           (0, 3 * h / 4), (ss / 4, h / 2)),
        "upArrow": lambda: _poly((w / 4, h), (w / 4, a), (0, a), (w / 2, 0), (w, a), (3 * w / 4, a), (3 * w / 4, h)),
        "ellipse": lambda: [_ring(w / 2, h / 2, w / 2, h / 2)],
        "donut": lambda: [_ring(w / 2, h / 2, w / 2, h / 2), _ring(w / 2, h / 2, w / 2 - ss / 4, h / 2 - ss / 4)],
        "arc": lambda: [_ring(w / 2, h / 2, w / 2, h / 2, 270, 360, 12)],
        "blockArc": lambda: [(lambda o: o + [o[0]])(_ring(w / 2, h / 2, w / 2, h / 2, 180, 360, 24)
                                                   + _ring(w / 2, h / 2, w / 2 - ss / 4, h / 2 - ss / 4, 360, 180, 24))],
        "roundRect": lambda: [_rounded(w, h, ss / 6)],
        "flowChartTerminator": lambda: [_rounded(w, h, ss / 2)],
    }
    mirror = {"leftArrow": ("rightArrow", True), "downArrow": ("upArrow", False)}
    alias = {"flowChartConnector": "ellipse", "flowChartDecision": "diamond", "flowChartAlternateProcess": "roundRect",
             "flowChartPreparation": "hexagon", "flowChartPunchedCard": "rect"}
    geom = alias.get(geom, geom)
    if geom in mirror:
        base, horizontal = mirror[geom]
        return [[(w - x, y) if horizontal else (x, h - y) for x, y in pl] for pl in shapes[base]()]
    if geom in shapes:
        return shapes[geom]()
    if (geom or "").endswith("Callout"):  # callouts: the body plus a pointer below it
        body = _preset("ellipse" if "Ellipse" in geom else "roundRect" if "Round" in geom else "rect", w, h)
        return body + [[(0.2 * w, h), (0.29 * w, 1.125 * h), (0.35 * w, h)]]
    if "round" in (geom or "").lower():
        return [_rounded(w, h, ss / 6)]
    return _poly((0, 0), (w, 0), (w, h), (0, h))  # rect and every unknown preset: its box


def _outline(geom, path, box):
    """Outline polylines of a shape in pixel box (x0, y0, x1, y1); a freeform path wins over the preset."""
    x0, y0, x1, y1 = box
    w, h = x1 - x0, y1 - y0
    local = [[(px * w, py * h) for px, py in sub] for sub in path] if path else _preset(geom, w, h)
    return [[(x0 + x, y0 + y) for x, y in pl] for pl in local]


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


def _stroke(d, pts, width, dashed, s):
    if not dashed:
        d.line(pts, fill=INK, width=width, joint="curve")
        return
    on, period, run = 7 * s, 12 * s, 0.0  # run: length walked so far, so the dash pattern flows round corners
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        seg = math.hypot(bx - ax, by - ay)
        t = -(run % period)
        while t < seg:
            t0, t1 = max(t, 0), min(t + on, seg)
            if t1 > t0:
                d.line(((ax + (bx - ax) * t0 / seg, ay + (by - ay) * t0 / seg),
                        (ax + (bx - ax) * t1 / seg, ay + (by - ay) * t1 / seg)), fill=INK, width=width)
            t += period
        run += seg


def _draw(dna, W, H):
    s = W / 960
    img = Image.new("L", (W, H), 255)
    d = ImageDraw.Draw(img)
    stroke = max(1, round(2 * s))
    plan = _plan(dna)
    px = lambda p: (p["box"][0] * W, p["box"][1] * H, p["box"][0] * W + max(p["box"][2] * W, 1), p["box"][1] * H + max(p["box"][3] * H, 1))
    for p in plan:
        if p["kind"] == "band":
            d.rectangle(px(p), fill=BAND)
        elif p["kind"] == "line":
            pts = [(x * W, y * H) for x, y in p["pts"]]
            _stroke(d, pts, stroke, p["dashed"], s)
            for end, prev, on in ((pts[-1], pts[-2], p["arrow"] in ("end", "both")), (pts[0], pts[1], p["arrow"] in ("start", "both"))):
                if on and end != prev:
                    a = math.atan2(end[1] - prev[1], end[0] - prev[0])
                    for da in (2.6, -2.6):  # two short barbs at about 150 degrees from the line
                        d.line((end, (end[0] + 9 * s * math.cos(a + da), end[1] + 9 * s * math.sin(a + da))), fill=INK, width=stroke)
        elif p["frame"]:
            for pl in _outline(p["geom"], p["path"], px(p)):
                _stroke(d, pl, stroke, p["dashed"], s)
    placed = []  # (label spot, its box) as pixel x, y, w, h
    for p in sorted((p for p in plan if p["label"]), key=lambda p: p["box"][2] * p["box"][3]):  # innermost first
        x, y, w, h = p["box"]
        framed = p["frame"]
        inset = 0.7 if framed and p["geom"] in ("ellipse", "flowChartConnector", "donut") else 1.0  # widest text inside an ellipse
        pad = 2 * stroke + 8 * s if framed else 4 * s
        room_w, room_h = w * W * inset - pad, h * H * inset - (2 * stroke + 4 * s if framed else 0)
        top = 40 if p["label"] == "[number]" else 22 if p["label"] == "[title]" else 18  # hero numbers draw larger
        align = "center" if framed else (_align(dna, p) or "left")
        for size in range(min(top, int(room_h / 1.3 / s)), 7, -1):  # shrink to fit, give up below 8px
            font = ImageFont.load_default(size=round(size * s))
            tw = d.textlength(p["label"], font=font)
            if tw <= room_w:
                cy, half = (y + h / 2) * H, font.size * 0.7
                for where in dict.fromkeys((align, "center")):  # blocked at its aligned spot: try the centre
                    if where in ("left", "justify"):
                        at, anchor, left = (x * W + pad / 2, cy), "lm", x * W + pad / 2
                    elif where == "right":
                        at, anchor, left = ((x + w) * W - pad / 2, cy), "rm", (x + w) * W - pad / 2 - tw
                    else:
                        at, anchor, left = ((x + w / 2) * W, cy), "mm", (x + w / 2) * W - tw / 2
                    spot, mine = (left, cy - half, tw, 2 * half), (x * W, y * H, w * W, h * H)
                    # never print over another label, nor over a labelled box inside this one
                    if not any(_overlap(spot, o) or (_inside(ob, mine) and _overlap(spot, ob)) for o, ob in placed):
                        d.text(at, p["label"], fill=INK, font=font, anchor=anchor)
                        placed.append((spot, mine))
                        break
                break
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _align(dna, p):
    """Alignment of the region a label came from (left/centre/right), from the record."""
    r = next((r for r in dna["regions"] if r["i"] == p["i"]), None)
    return r and r["text"] and r["text"]["align"]
