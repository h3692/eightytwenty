"""Stage 3: merge geometry + labels into design-DNA records, draw each wireframe from the record alone, write descriptions."""
import hashlib
import io
import json
import math
import random
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
TOKENS = {"percent": "##%", "currency": "$##M", "multiple": "##x", "plain": "##"}
GREY = {"primary": 85, "accent": 130, "neutral-dark": 70, "neutral-light": 222, "white": 250}
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


def _draw(dna, W, H):
    s = W / 960
    img = Image.new("L", (W, H), GREY.get(dna["background"], 255))
    d = ImageDraw.Draw(img)
    rng = random.Random(int(hashlib.sha256(dna["id"].encode()).hexdigest()[:8], 16))
    by_i = {r["i"]: r for r in dna["regions"]}
    for r in dna["regions"]:
        b = r["box"]
        x0, y0 = b["x"] * W, b["y"] * H
        x1, y1 = x0 + max(b["w"] * W, 1), y0 + max(b["h"] * H, 1)
        box = (x0, y0, x1, y1)
        fill, outline = GREY.get(r["fill"]), GREY.get(r["line"])
        if r["type"] == "line":  # shortcut: connector flips are not in the DNA, so diagonals may draw mirrored
            _line(d, (x0, y0, x1, y1), outline or 120, max(1, round(2 * s)), r["dashed"])
            continue
        if r["type"] == "picture" or r["role"] in ("image", "icon", "logo"):
            d.rectangle(box, fill=235, outline=150)
            d.line((x0, y0, x1, y1), fill=170)
            d.line((x0, y1, x1, y0), fill=170)
            continue
        if fill is not None or outline is not None:
            if r["dashed"]:
                d.rectangle(box, fill=fill)
                for edge in ((x0, y0, x1, y0), (x1, y0, x1, y1), (x1, y1, x0, y1), (x0, y1, x0, y0)):
                    _line(d, edge, outline or 120, 1, True)
            else:
                d.rectangle(box, fill=fill, outline=outline)
        if r["chart"]:
            _chart(d, box, r["chart"], rng, s)
        elif r["table"]:
            _table(d, box, r["table"])
        elif r["text"]:
            under = fill if fill is not None else _under(r, by_i, dna)
            _text(d, box, r, under, rng, s)
    out = io.BytesIO()
    img.save(out, "PNG", optimize=True)
    return out.getvalue()


def _under(r, by_i, dna):
    """Grey of whatever the region sits on: nearest filled region drawn earlier that contains its centre."""
    b = r["box"]
    cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    for o in reversed([o for o in dna["regions"] if o["i"] < r["i"] and o["fill"]]):
        ob = o["box"]
        if ob["x"] <= cx <= ob["x"] + ob["w"] and ob["y"] <= cy <= ob["y"] + ob["h"]:
            return GREY[o["fill"]]
    return GREY.get(dna["background"], 255)


def _line(d, xy, fill, width, dashed):
    if not dashed:
        d.line(xy, fill=fill, width=width)
        return
    x0, y0, x1, y1 = xy
    n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 6))
    for k in range(0, n, 2):
        a, c = k / n, min(1, (k + 1) / n)
        d.line((x0 + (x1 - x0) * a, y0 + (y1 - y0) * a, x0 + (x1 - x0) * c, y0 + (y1 - y0) * c), fill=fill, width=width)


def _text(d, box, r, under, rng, s):
    t, (x0, y0, x1, y1) = r["text"], box
    ink = 200 if under < 128 else 120
    pad = 6 * s
    kind = t["number"] or ("plain" if r["role"] == "big-number" else None)
    if kind:
        size = max(8, int(min(y1 - y0, (x1 - x0) / 2.2) * 0.7))
        font = ImageFont.load_default(size=size)
        tw = d.textlength(TOKENS[kind], font=font)
        tx = {"center": (x0 + x1 - tw) / 2, "right": x1 - pad - tw}.get(t["align"], x0 + pad)
        d.text((tx, (y0 + y1) / 2), TOKENS[kind], fill=ink, font=font, anchor="lm")
        return
    thick = {"title": 10, "tagline": 6}.get(r["role"]) or {"display": 12, "heading": 8, "body": 4, "caption": 3}[t["size"]]
    thick = max(2, round(thick * s))
    step = thick * 2.2
    lines = max(1, min(t["lines"], int((y1 - y0 - 2 * pad + thick * 1.2) // step) or 1))
    starts = {round(k * lines / t["paragraphs"]) for k in range(t["paragraphs"])} if t["paragraphs"] else set()
    bulleted = sorted(starts)[len(starts) - t["bullets"]:] if t["bullets"] else []
    for k in range(lines):
        indent = 4 * thick if any(b <= k for b in bulleted) else 0
        if k in bulleted:
            m = thick * 0.9
            yy = y0 + pad + k * step + thick / 2
            d.rectangle((x0 + pad + indent - 2.5 * m, yy - m / 2, x0 + pad + indent - 1.5 * m, yy + m / 2), fill=ink)
        full = x1 - x0 - 2 * pad - indent
        length = full * (0.6 if k == lines - 1 and lines > 1 else rng.uniform(0.85, 1.0))
        lx = {"center": x0 + indent + (x1 - x0 - indent - length) / 2, "right": x1 - pad - length}.get(t["align"], x0 + pad + indent)
        ly = y0 + pad + k * step
        d.rectangle((lx, ly, lx + length, ly + thick), fill=ink)


def _chart(d, box, c, rng, s):
    """A fake chart of the same kind and shape (series x categories) with dummy values seeded by the record id."""
    x0, y0, x1, y1 = box
    pad = 10 * s
    ax0, ay0, ax1, ay1 = x0 + pad, y0 + pad, x1 - pad, y1 - pad
    kind, n, m = c["kind"], max(1, c["categories"]), max(1, c["series"])
    phase = rng.uniform(0, math.pi)
    vals = [[0.35 + 0.3 * (0.5 + 0.5 * math.sin(phase + j * 0.9 + i * 0.6)) + rng.uniform(0, 0.1) for j in range(n)] for i in range(m)]
    shades = [100 + (110 * i) // max(1, m) for i in range(m)]
    if "PIE" in kind or "DOUGHNUT" in kind:
        r_ = min(ax1 - ax0, ay1 - ay0) / 2
        cx, cy = (ax0 + ax1) / 2, (ay0 + ay1) / 2
        total, a = sum(vals[0]), -90.0
        for j, v in enumerate(vals[0]):
            sweep = 360 * v / total
            d.pieslice((cx - r_, cy - r_, cx + r_, cy + r_), a, a + sweep, fill=90 + (130 * j) // n, outline=255)
            a += sweep
        if "DOUGHNUT" in kind:
            d.ellipse((cx - r_ / 2, cy - r_ / 2, cx + r_ / 2, cy + r_ / 2), fill=255)
        return
    d.line((ax0, ay0, ax0, ay1, ax1, ay1), fill=140, width=1)
    horizontal = kind.startswith("BAR")
    if horizontal or kind.startswith("COLUMN") or kind.startswith("THREE_D_BAR") or kind.startswith("THREE_D_COLUMN"):
        span = (ay1 - ay0) if horizontal else (ax1 - ax0)
        slot = span / n
        bw = slot * 0.7 / m
        for j in range(n):
            for i in range(m):
                a = (ay0 if horizontal else ax0) + j * slot + slot * 0.15 + i * bw
                if horizontal:
                    d.rectangle((ax0, a, ax0 + vals[i][j] * (ax1 - ax0), a + bw - 1), fill=shades[i])
                else:
                    d.rectangle((a, ay1 - vals[i][j] * (ay1 - ay0), a + bw - 1, ay1), fill=shades[i])
        return
    xs = [ax0 + (ax1 - ax0) * (j + 0.5) / n for j in range(n)]
    for i in range(m):
        pts = [(x, ay1 - v * (ay1 - ay0)) for x, v in zip(xs, vals[i])]
        if "AREA" in kind:
            d.polygon([(xs[0], ay1)] + pts + [(xs[-1], ay1)], fill=shades[i])
        elif "SCATTER" in kind or "BUBBLE" in kind:
            for x, y in pts:
                d.ellipse((x - 3 * s, y - 3 * s, x + 3 * s, y + 3 * s), fill=shades[i])
        else:  # line, radar, stock and anything else: a polyline per series
            d.line(pts, fill=shades[i], width=max(1, round(2 * s))) if len(pts) > 1 else d.ellipse((pts[0][0] - 2, pts[0][1] - 2, pts[0][0] + 2, pts[0][1] + 2), fill=shades[i])


def _table(d, box, t):
    x0, y0, x1, y1 = box
    rows, cols = max(1, t["rows"]), max(1, t["cols"])
    rh, cw = (y1 - y0) / rows, (x1 - x0) / cols
    d.rectangle((x0, y0, x1, y0 + rh), fill=200)
    for k in range(rows + 1):
        d.line((x0, y0 + k * rh, x1, y0 + k * rh), fill=150)
    for k in range(cols + 1):
        d.line((x0 + k * cw, y0, x0 + k * cw, y1), fill=150)
