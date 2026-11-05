"""Deck flows: an agent looks at a contact sheet of a deck and writes only each slide's section, the arc pattern and
why the flow works, and may mark impact slides (flow.v2.json; v1 flows stay valid); the rest of the record (steps, section dividers, pacing, length bucket, industry,
description) is computed from the slides' labels. Only decks with at least MIN_SLIDES visible slides get a flow.
The record is built into work/<deck>/flow-record.json; the leak check publishes it to library/flows/."""
import collections
import itertools
import json
from pathlib import Path

import jsonschema
from PIL import Image, ImageDraw, ImageFont

from pipeline import dedupe

HERE = Path(__file__).parent
SCHEMA_PATH = HERE / "schema" / "flow.v2.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
SECTIONS = SCHEMA["properties"]["sections"]["items"]["enum"]
ARCS = SCHEMA["properties"]["arc"]["enum"]
IMPACTS = SCHEMA["properties"]["impact"]["items"]["enum"]
TEMPLATE = (HERE / "templates" / "flow.txt").read_text()
IMPACT_TEMPLATE = (HERE / "templates" / "flow-impact.txt").read_text()
MIN_SLIDES = 6
# What each impact frame is for, appended to an impact slide's description when it is embedded and packaged, so a
# request like "emphasize a key point" finds them. Fixed text: nothing from the source deck.
IMPACT_PURPOSE = {
    "build": "Impact frame, build: reveals the slide's content step by step, to pace the argument and land each point in turn.",
    "spotlight": "Impact frame, spotlight: repeats an earlier slide with one part highlighted and the rest faded, to draw attention to one point.",
    "shade_ribbon": "Impact frame, shade and ribbon: repeats the previous slide dimmed with a ribbon stating the key point, to emphasize the main takeaway.",
    "repeat": "Impact frame, repeat: brings an earlier slide back, such as the agenda, summary or cover, to recap or bookend the story.",
}


def impacts(flows):
    """Slide id -> the impact kind of its step in a published flow (v1 flows mark none)."""
    return {s["id"]: s.get("impact", "none") for f in flows for s in f.get("steps", [])}


def described(record, impact):
    """The text a slide is embedded and searched by: its description, plus what its impact frame is for."""
    return f"{record['description']} {IMPACT_PURPOSE[impact]}" if impact in IMPACT_PURPOSE else record["description"]
RECORD_KEYS = {"schema_version", "id", "deck_id", "arc", "why_the_flow_works", "steps", "dividers", "pacing",
               "length_bucket", "industry", "description"}
STEP_KEYS = {"id", "archetype", "section", "impact", "builds_on"}
TILE, COLUMNS = (320, 180), 5  # contact sheet: slide thumbnails in px, per row


def validate(flow, n):
    """Raise ValueError unless the agent's flow matches the schema and has one section (and, when marked, one impact
    and one builds_on) per visible slide; builds_on names an earlier step, only on an impact slide, and a build's
    the step just before it."""
    errors = sorted(jsonschema.Draft202012Validator(SCHEMA).iter_errors(flow), key=str)
    if errors:
        raise ValueError("; ".join(f"{'/'.join(map(str, e.path)) or 'flow'}: {e.message}" for e in errors))
    for key in ("sections", "impact", "builds_on"):
        if key in flow and len(flow[key]) != n:
            raise ValueError(f"{key}: {len(flow[key])} entries for {n} slides")
    for step, (kind, base) in enumerate(zip(flow.get("impact", ()), flow.get("builds_on", ())), 1):
        if base is None:
            continue
        if kind == "none":
            raise ValueError(f"builds_on: step {step} is not an impact slide, so its builds_on must be null")
        if not (type(base) is int and base < step):  # the schema already refused booleans and numbers below one
            raise ValueError(f"builds_on: step {step} builds on {base}, not an earlier step")
        if kind == "build" and base != step - 1:
            raise ValueError(f"builds_on: step {step} is a build, so it builds on step {step - 1}, not {base}")


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


def prep(deck_id, library, impact_only=False):
    """Write work/<deck>/flow.prompt.txt and a contact sheet of the slide renders (local only, never published);
    return the worksheet path, or None for a deck under MIN_SLIDES. impact_only writes flow-impact.prompt.txt instead:
    add impact marks to the deck's existing flow.json and change nothing else."""
    work = Path(library).absolute() / "work" / deck_id
    n = _visible(work)
    if n < MIN_SLIDES:
        return None
    if impact_only and not (work / "flow.json").exists():
        raise SystemExit(f"No {work / 'flow.json'} to add impact marks to: run flow-prep without --impact-only.")
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
    sheet_path = work / "flow-contact-sheet.png"
    sheet.save(sheet_path)
    hints = [f"  {d[-2:]}  duplicate_of {k[-2:]} (spotlight/build?)"
             for d, (k, _) in sorted(dedupe.duplicates(deck_id, library).items())]
    fields = dict(out=work / "flow.json", sheet=sheet_path, count=n, schema=SCHEMA_PATH,
                  slides="\n".join(f"{k:02d}  {lb['archetype']}  {lb['purpose']}" for k, lb in enumerate(labels, 1)))
    text = TEMPLATE.format(**fields, sections=", ".join(SECTIONS), arcs=", ".join(ARCS), impacts=", ".join(IMPACTS),
                           hints="\n".join(hints) or "  none found")
    out = work / "flow.prompt.txt"
    if impact_only:  # the same impact fields and definitions, from the full worksheet
        text, out = IMPACT_TEMPLATE.format(**fields, impact=text[text.index("  impact "):text.index("Hard rules")]), \
            work / "flow-impact.prompt.txt"
    out.write_text(text)
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
    impact, builds_on = agent.get("impact", ["none"] * n), agent.get("builds_on", [None] * n)
    rec = {"schema_version": "deck-flow/v2", "id": deck_id, "deck_id": deck_id, "arc": agent["arc"],
           "why_the_flow_works": agent["why_the_flow_works"],
           "steps": [{"id": f"{deck_id}-{k:02d}", "archetype": lb["archetype"], "section": s, "impact": i,
                      "builds_on": b} for k, (lb, s, i, b) in enumerate(zip(labels, sections, impact, builds_on), 1)],
           "dividers": [k for k, lb in enumerate(labels, 1) if lb["archetype"] == "section-divider"],
           "pacing": [{"section": s, "slides": len(list(g))} for s, g in itertools.groupby(sections)],
           "length_bucket": length_bucket(n),
           # ties go to the industry met first in deck order
           "industry": collections.Counter(lb["industry"] for lb in labels).most_common(1)[0][0]}
    rec["description"] = describe(rec)
    (work / "flow-record.json").write_text(json.dumps(rec, indent=1))
    return rec


def describe(rec):
    """Fixed template, words only (counts spelled out, so no digits): length, arc, industry, the section sequence,
    the slide types (most used first), the impact slides per kind and why the flow works."""
    words = lambda s: s.replace("-", " ").replace("_", " ")
    mix = collections.Counter(s["archetype"] for s in rec["steps"]).most_common()
    impact = collections.Counter(s["impact"] for s in rec["steps"])
    return (f"{rec['length_bucket'].capitalize()} deck, {words(rec['arc'])} arc, {words(rec['industry'])}. "
            f"Sections: {', '.join(words(p['section']) for p in rec['pacing'])}. "
            f"Slide types: {', '.join(words(a) for a, _ in mix)}. "
            f"Impact slides: {', '.join(f'{_count(impact[k])} {words(k)}' for k in IMPACTS[1:] if impact[k]) or 'none'}. "
            f"Why the flow works: {rec['why_the_flow_works'].rstrip('.')}.")


def _count(k):
    # shortcut: counts past twelve read "many"; spell them out if a deck ever marks that many of one kind
    return ("one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven", "twelve")[k - 1] \
        if k <= 12 else "many"
