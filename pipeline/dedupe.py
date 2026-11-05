"""Slides never published: blank/spacer slides, and near-duplicates within a deck (repeated slides, progressive
builds, spotlight sets that grey out all but one card). Fail-safe: a slide is only dropped on clear evidence, and a
slide without a readable layout, labels or render is always kept.

Two slides of one deck are duplicates only with the same v3 layout (component kinds + grid-snapped boxes) AND
  - renders NEAR-identical (difference hash, 16 x 16 bits), or
  - renders within LOOSE bits and the same copy (CONTAINS of the shorter slide's text lines appear in the other).
Same-template slides with other content measured 28-45 bits apart but share at most ~80% of their lines.
Of each set the slide with the most ink is kept (the neutral one of a spotlight set, the last build), ties the later.
"""
import json
from pathlib import Path

from PIL import Image, ImageStat

from pipeline import layout

HASH, NEAR, LOOSE, CONTAINS = 16, 12, 48, 0.9


def blank(labels, lay):
    """Blank or spacer: flagged blank, or archetype other with nothing but a one-line placeholder text block."""
    return lay.get("blank") is True or bool(
        labels and labels.get("archetype") == "other"
        and [(c["kind"], c.get("lines")) for c in lay["components"]] == [("text", 1)])


def dhash(png):
    """Difference hash: each bit says whether a pixel of the HASH x HASH greyscale thumbnail is brighter than the
    one to its right."""
    px = Image.open(png).convert("L").resize((HASH + 1, HASH), Image.Resampling.LANCZOS).tobytes()
    return sum(1 << k for k, (r, c) in enumerate((r, c) for r in range(HASH) for c in range(HASH))
               if px[r * (HASH + 1) + c] > px[r * (HASH + 1) + c + 1])


def distance(a, b):
    return bin(a ^ b).count("1")


def _slides(deck_id, library):
    """{record id: slide facts} for every slide with a valid layout; hash/ink only when its render exists."""
    lib, out = Path(library), {}
    for f in sorted((lib / "layouts" / deck_id).glob("slide-??.v3.json")):
        nn = f.name[:8]
        work = lib / "work" / deck_id
        try:
            lay = layout.validate(json.loads(f.read_text()))
        except ValueError:
            continue
        lf, tf, png = work / "labels" / f"{nn}.json", work / "text" / f"{nn}.txt", work / f"{nn}.png"
        s = out[f"{deck_id}-{nn[-2:]}"] = {
            "blank": blank(json.loads(lf.read_text()) if lf.exists() else None, lay),
            "layout": sorted((c["kind"], tuple(c.get("box", ()))) for c in lay["components"]),
            "text": {t.strip() for t in tf.read_text().splitlines() if t.strip()} if tf.exists() else set(),
            "hash": None}
        if png.exists():
            s["hash"], s["ink"] = dhash(png), 255 - ImageStat.Stat(Image.open(png).convert("L")).mean[0]
    return out


def _why(a, b):
    """Why b duplicates a, or None."""
    if a["layout"] != b["layout"]:
        return None
    d = distance(a["hash"], b["hash"])
    if d <= NEAR:
        return "near-exact render"
    if d <= LOOSE and a["text"] and b["text"] and \
            len(a["text"] & b["text"]) >= CONTAINS * min(len(a["text"]), len(b["text"])):
        return "same copy, similar render"
    return None


def duplicates(deck_id, library, slides=None):
    """{dropped id: (kept id, why)}: each dropped slide matches its kept one directly (no chains)."""
    slides = slides or _slides(deck_id, library)
    order = sorted((rid for rid, s in slides.items() if s["hash"] is not None and not s["blank"]),
                   key=lambda rid: (-slides[rid]["ink"], -int(rid[-2:])))
    kept, out = [], {}
    for rid in order:
        hit = next(((k, w) for k in kept if (w := _why(slides[k], slides[rid]))), None)
        if hit:
            out[rid] = hit
        else:
            kept.append(rid)
    return out


def excluded(deck_id, library):
    """{record id: "blank" | "duplicate_of <id>"} for the deck's slides that are never published."""
    slides = _slides(deck_id, library)
    out = {rid: "blank" for rid, s in slides.items() if s["blank"]}
    return out | {rid: f"duplicate_of {kept}" for rid, (kept, _) in duplicates(deck_id, library, slides).items()}


def report(library):
    """Write work/dedupe-report.txt and work/blank-report.txt over every deck with layouts; return the counts."""
    lib = Path(library)
    dupes, blanks = ["deck\tkept\tdropped\treason"], ["deck\tid\treason"]
    for deck in sorted(p.name for p in (lib / "layouts").iterdir() if p.is_dir()):
        slides = _slides(deck, lib)
        groups = {}
        for rid, (kept, why) in sorted(duplicates(deck, lib, slides).items()):
            groups.setdefault((kept, why), []).append(rid)
        dupes += [f"{deck}\t{kept}\t{','.join(ids)}\t{why}" for (kept, why), ids in sorted(groups.items())]
        blanks += [f"{deck}\t{rid}\t" + ("blank flag" if json.loads(
            (lib / "layouts" / deck / f"slide-{rid[-2:]}.v3.json").read_text()).get("blank") else
                   "archetype other, one placeholder text line")
                   for rid, s in slides.items() if s["blank"]]
    (lib / "work").mkdir(parents=True, exist_ok=True)
    (lib / "work" / "dedupe-report.txt").write_text("\n".join(dupes) + "\n")
    (lib / "work" / "blank-report.txt").write_text("\n".join(blanks) + "\n")
    return sum(len(line.split("\t")[2].split(",")) for line in dupes[1:]), len(blanks) - 1
