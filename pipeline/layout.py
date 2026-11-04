"""Agent-drawn layout lists: written from the slide PNG, snapped to extracted regions, built into mockups by pipeline.mockup."""
import copy
import json
from pathlib import Path

import jsonschema

HERE = Path(__file__).parent
SCHEMA_PATH = HERE / "schema" / "layout.v2.json"
SCHEMA, SCHEMA_V1 = json.loads(SCHEMA_PATH.read_text()), json.loads((HERE / "schema" / "layout.v1.json").read_text())
TEMPLATE = (HERE / "templates" / "layout.txt").read_text()
CONTAINERS = ("band", "panel", "card", "strip")
V1_CHARTS = {"bar_chart": "column", "line_chart": "line", "pie_chart": "pie", "chart": "column"}
V1_ARROWS = {"chevron": "chevron", **{s: "block" for s in ("arrow_right", "arrow_left", "arrow_up", "arrow_down")}}


def _check(layout, schema):
    errors = sorted(jsonschema.Draft202012Validator(schema).iter_errors(layout), key=str)
    if errors:
        raise ValueError("; ".join(f"{'/'.join(map(str, e.path)) or 'layout'}: {e.message}" for e in errors))


def upgrade(v1):
    """A valid v1 layout as v2: chart kinds become chart + chart_type, tables get a 3x3 grid, arrows a style,
    connectors an end head."""
    els = []
    for e in copy.deepcopy(v1["elements"]):
        if e["kind"] in V1_CHARTS:
            e["chart_type"], e["kind"] = V1_CHARTS[e["kind"]], "chart"
        elif e["kind"] == "table":
            e.update(rows=3, cols=3)
        elif e["kind"] == "arrow":
            e["arrow_style"] = V1_ARROWS.get(e["shape"], "line")
        elif e["kind"] == "connector":
            e["head"] = "end"
        els.append(e)
    return {"version": 2, "elements": els}


def validate(layout):
    """Return the layout as v2 (upgrading a v1 list); raise ValueError unless it matches the schema, connectors join
    existing elements and every parent is a container listed before its child."""
    if "version" not in layout:
        _check(layout, SCHEMA_V1)
        layout = upgrade(layout)
    _check(layout, SCHEMA)
    els = layout["elements"]
    bad = [f"elements/{k}/{end}: not an element index" for k, e in enumerate(els) for end in ("from", "to")
           if e.get(end, 0) >= len(els)]
    bad += [f"elements/{k}/parent: not a container listed before it" for k, e in enumerate(els)
            if "parent" in e and not (e["parent"] < k and els[e["parent"]]["kind"] in CONTAINERS)]
    if bad:
        raise ValueError("; ".join(bad))
    return layout


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


def prep(deck_id, library, slides=None):
    """Write one layout worksheet per slide (or only the listed slide numbers); return the output folder."""
    work, out = Path(library).absolute() / "work" / deck_id, Path(library).absolute() / "layouts" / deck_id
    out.mkdir(parents=True, exist_ok=True)
    el = SCHEMA["$defs"]["element"]["properties"]
    enum = lambda f: ", ".join(el[f]["enum"])
    for f in sorted(work.glob("slide-??.json")):
        if slides and f.stem[-2:] not in slides:
            continue
        (out / f"{f.stem}.final.prompt.txt").write_text(TEMPLATE.format(
            png=work / f"{f.stem}.png", regions=f, out=out / f"{f.stem}.final.json", schema=SCHEMA_PATH,
            kinds=enum("kind"), shapes=enum("shape"), emphases=enum("emphasis"), fills=enum("fill"),
            chart_types=enum("chart_type"), arrow_styles=enum("arrow_style"), heads=enum("head")))
    return out
