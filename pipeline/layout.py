"""Agent-written component layouts: at most 8 components per slide, snapped to a 12 x 8 grid, built by pipeline.mockup."""
import copy
import json
from pathlib import Path

import jsonschema

HERE = Path(__file__).parent
SCHEMA_PATH = HERE / "schema" / "layout.v3.json"
SCHEMA = json.loads(SCHEMA_PATH.read_text())
KINDS = SCHEMA["$defs"]["component"]["properties"]["kind"]["enum"]
FULL = ("cover", "section_divider", "closing")  # whole-slide kinds: no header, no box
COLS, ROWS = 12, 8
MAX_LEAVES = 16


def _check(layout, schema):
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(layout), key=str)
    if errors:
        raise ValueError("; ".join(f"{'/'.join(map(str, e.path)) or 'layout'}: {e.message}" for e in errors))


def _snap(v, w, cells):
    """[start, size] as whole cells: at least one cell, kept on the slide."""
    a = min(round(v * cells), cells - 1)
    return a / cells, (max(round((v + w) * cells), a + 1) - a) / cells


def validate(layout):
    """Return a copy with every box snapped to the grid; raise ValueError unless it matches the schema, boxes stay
    on the slide, active pills, highlighted columns and groups exist, trees stay readable, tracker, logo and the
    whole-slide kinds appear at most once and an impact_overlay comes last (it shades what precedes it)."""
    _check(layout, SCHEMA)
    out = copy.deepcopy(layout)
    comps, bad = out["components"], []
    for k, c in enumerate(comps):
        if "box" in c:
            x, y, w, h = c["box"]
            if x + w > 1.001 or y + h > 1.001:
                bad.append(f"components/{k}/box: off the slide")
            (x, w), (y, h) = _snap(x, w, COLS), _snap(y, h, ROWS)
            c["box"] = [x, y, w, h]
        if c["kind"] in ("tracker", "stage_strip") and c["active"] > c["n"]:
            bad.append(f"components/{k}/active: past the last of {c['n']} pills")
        for field, count in (("highlight_col", "cols"), ("groups", "periods" if c["kind"] == "timeline" else "n")):
            if c.get(field, 0) > c.get(count, 0):
                bad.append(f"components/{k}/{field}: more than {count}")
        if c["kind"] == "tree" and c["branching"] ** (c["levels"] - 1) > MAX_LEAVES:
            bad.append(f"components/{k}: more than {MAX_LEAVES} leaves, zoom out")
    kinds = [c["kind"] for c in comps]
    bad += [f"components: more than one {k}" for k in ("tracker", "logo", "impact_overlay") if kinds.count(k) > 1]
    if "impact_overlay" in kinds[:-1]:
        bad.append("components: impact_overlay must come last")
    if sum(k in FULL for k in kinds) > 1:
        bad.append("components: more than one full-slide component (cover, section_divider, closing)")
    if bad:
        raise ValueError("; ".join(bad))
    return out

