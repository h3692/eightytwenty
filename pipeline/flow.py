"""Deck flows: an agent looks at a contact sheet of a deck and writes only each slide's section, the arc pattern and
why the flow works (flow.v1.json); the rest of the record (steps, section dividers, pacing, length bucket, industry,
description) is computed from the slides' labels. Only decks with at least MIN_SLIDES visible slides get a flow.
The record is built into work/<deck>/flow-record.json; the leak check publishes it to library/flows/."""
import collections
import itertools
import json
from pathlib import Path

import jsonschema
from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
SCHEMA_PATH = HERE / "schema" / "flow.v1.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
SECTIONS = SCHEMA["properties"]["sections"]["items"]["enum"]
ARCS = SCHEMA["properties"]["arc"]["enum"]
TEMPLATE = (HERE / "templates" / "flow.txt").read_text()
MIN_SLIDES = 6
RECORD_KEYS = {"schema_version", "id", "deck_id", "arc", "why_the_flow_works", "steps", "dividers", "pacing",
               "length_bucket", "industry", "description"}
TILE, COLUMNS = (320, 180), 5  # contact sheet: slide thumbnails in px, per row


def validate(flow, n):
    """Raise ValueError unless the agent's flow matches the schema and has one section per visible slide."""
    errors = sorted(jsonschema.Draft202012Validator(SCHEMA).iter_errors(flow), key=str)
    if errors:
        raise ValueError("; ".join(f"{'/'.join(map(str, e.path)) or 'flow'}: {e.message}" for e in errors))
    if len(flow["sections"]) != n:
        raise ValueError(f"sections: {len(flow['sections'])} entries for {n} slides")


def length_bucket(n):
    return "short" if n <= 10 else "medium" if n <= 25 else "long"


def _visible(work):
    return len(list(work.glob("slide-??.json")))  # extract numbers visible slides only


def _labels(work):
    """Every visible slide's labels in deck order; refuses if any slide has none."""
    out, missing = [], []
    for f in sorted(work.glob("slide-??.json")):
        try:
            out.append(json.loads((work / "labels" / f.name).read_text()))
        except (OSError, ValueError):
            missing.append(f.stem)
    if missing:
        raise SystemExit(f"No labels for {', '.join(missing)}: label every slide of the deck first.")
    return out


def prep(deck_id, library):
    """Write work/<deck>/flow.prompt.txt and a contact sheet of the slide renders (local only, never published);
    return the worksheet path, or None for a deck under MIN_SLIDES."""
    work = Path(library).absolute() / "work" / deck_id
    n = _visible(work)
    if n < MIN_SLIDES:
        return None
    labels = _labels(work)
    renders = [work / f"slide-{k:02d}.png" for k in range(1, n + 1)]
    missing = [p.name for p in renders if not p.exists()]
    if missing:
        raise SystemExit(f"No slide renders ({', '.join(missing)}): re-extract the deck with LibreOffice installed.")
    sheet = Image.new("RGB", (COLUMNS * TILE[0], -(-n // COLUMNS) * TILE[1]), "white")
    d, font = ImageDraw.Draw(sheet), ImageFont.load_default(size=20)
    for k, p in enumerate(renders):
        x, y = k % COLUMNS * TILE[0], k // COLUMNS * TILE[1]
        with Image.open(p) as im:
            sheet.paste(im.convert("RGB").resize((TILE[0] - 8, TILE[1] - 8)), (x + 4, y + 4))
        d.rectangle((x + 4, y + 4, x + 40, y + 30), fill="black")
        d.text((x + 9, y + 6), f"{k + 1:02d}", fill="white", font=font)
    sheet_path, out = work / "flow-contact-sheet.png", work / "flow.prompt.txt"
    sheet.save(sheet_path)
    out.write_text(TEMPLATE.format(
        out=work / "flow.json", sheet=sheet_path, count=n, schema=SCHEMA_PATH, sections=", ".join(SECTIONS),
        arcs=", ".join(ARCS), slides="\n".join(f"{k:02d}  {lb['archetype']}  {lb['purpose']}"
                                               for k, lb in enumerate(labels, 1))))
    return out


def build_flow(deck_id, library):
    """Build work/<deck>/flow.json and the slides' labels into work/<deck>/flow-record.json and return the record,
    or None for a deck under MIN_SLIDES. Refuses a missing or invalid flow.json or missing labels."""
    work = Path(library) / "work" / deck_id
    n = _visible(work)
    if n < MIN_SLIDES:
        return None
    labels = _labels(work)
    try:
        agent = json.loads((work / "flow.json").read_text())
        validate(agent, n)
    except (OSError, ValueError) as e:
        raise SystemExit(f"{work / 'flow.json'}: {e} (run flow-prep and follow flow.prompt.txt)")
    sections = agent["sections"]
    rec = {"schema_version": "deck-flow/v1", "id": deck_id, "deck_id": deck_id, "arc": agent["arc"],
           "why_the_flow_works": agent["why_the_flow_works"],
           "steps": [{"id": f"{deck_id}-{k:02d}", "archetype": lb["archetype"], "section": s}
                     for k, (lb, s) in enumerate(zip(labels, sections), 1)],
           "dividers": [k for k, lb in enumerate(labels, 1) if lb["archetype"] == "section-divider"],
           "pacing": [{"section": s, "slides": len(list(g))} for s, g in itertools.groupby(sections)],
           "length_bucket": length_bucket(n),
           # ties go to the industry met first in deck order
           "industry": collections.Counter(lb["industry"] for lb in labels).most_common(1)[0][0]}
    rec["description"] = describe(rec)
    (work / "flow-record.json").write_text(json.dumps(rec, indent=1))
    return rec


def describe(rec):
    """Fixed template, words only (no counts, so no digits): length, arc, industry, the section sequence, the slide
    types (most used first) and why the flow works."""
    words = lambda s: s.replace("-", " ")
    mix = collections.Counter(s["archetype"] for s in rec["steps"]).most_common()
    return (f"{rec['length_bucket'].capitalize()} deck, {words(rec['arc'])} arc, {words(rec['industry'])}. "
            f"Sections: {', '.join(words(p['section']) for p in rec['pacing'])}. "
            f"Slide types: {', '.join(words(a) for a, _ in mix)}. "
            f"Why the flow works: {rec['why_the_flow_works'].rstrip('.')}.")
