"""Stage 2: write one worksheet per slide (labels + component layout in one look at the slide, or the layout alone
for slides labelled before), and validate the labels written back in the user's session."""
import json
from pathlib import Path

import jsonschema

from pipeline import layout

HERE = Path(__file__).parent
SCHEMA = json.loads((HERE / "schema" / "labels.v1.json").read_text())
TEMPLATE, LAYOUT_ONLY, COMPONENTS = ((HERE / "templates" / f"{n}.txt").read_text()
                                     for n in ("labeling", "layout", "components"))
MAX_REGIONS = 40  # busy slides extract 1,000+ regions; a labeler only needs the big ones


def worksheet_regions(slide):
    """The regions a worksheet lists: the MAX_REGIONS largest by box area (ties by index), in index order."""
    big = sorted(slide["regions"], key=lambda r: (-r["box"]["w"] * r["box"]["h"], r["i"]))[:MAX_REGIONS]
    return sorted(big, key=lambda r: r["i"])


def run(deck_id, library, slides=None, layouts_only=False):
    """Write a worksheet per slide (or only the listed slide numbers) and return its folder: work/<deck>/ for the
    combined labels + layout pass, layouts/<deck>/ for the layout alone."""
    lib = Path(library).absolute()
    work, layouts = lib / "work" / deck_id, lib / "layouts" / deck_id
    (work / "labels").mkdir(exist_ok=True)
    layouts.mkdir(parents=True, exist_ok=True)
    p, defs = SCHEMA["properties"], layout.SCHEMA["$defs"]
    enums = {k: ", ".join(p[k]["enum"]) for k in ("archetype", "argument_shape", "insight_device", "data_type", "industry")}
    for f in sorted(work.glob("slide-??.json")):
        if slides and f.stem[-2:] not in slides:
            continue
        slide, out = json.loads(f.read_text()), layouts / f"{f.stem}.v3.json"
        listed = worksheet_regions(slide)
        common = dict(png=work / f"{f.stem}.png", count=len(listed), total=len(slide["regions"]),
                      regions="\n".join(json.dumps({k: v for k, v in r.items() if k != "path" and v is not None})
                                        for r in listed),
                      components=COMPONENTS.format(
                          out=out, schema=layout.SCHEMA_PATH,
                          chart_types=", ".join(defs["chart_area"]["properties"]["chart_type"]["enum"]),
                          variants=", ".join(defs["image_area"]["properties"]["variant"]["enum"])))
        if layouts_only:
            (layouts / f"{f.stem}.prompt.txt").write_text(LAYOUT_ONLY.format(**common))
            continue
        (work / f"{f.stem}.prompt.txt").write_text(TEMPLATE.format(
            **common, labels_out=work / "labels" / f.name, layout_out=out, schema=layout.SCHEMA_PATH,
            archetypes=enums["archetype"], argument_shapes=enums["argument_shape"],
            insight_devices=enums["insight_device"], data_types=enums["data_type"], industries=enums["industry"],
            roles=", ".join(SCHEMA["$defs"]["role"]["enum"])))
    return layouts if layouts_only else work


def reconcile(deck_id, library):
    """After a re-extract: drop labels (and text patterns) of regions that no longer exist and label regions newly
    listed on the worksheet "other" (what build gives unlisted regions). Returns one report line per changed slide."""
    work, report = Path(library) / "work" / deck_id, []
    for lf in sorted((work / "labels").glob("slide-??.json")):
        labels = json.loads(lf.read_text())
        if not isinstance(labels.get("regions"), dict):
            continue
        slide = json.loads((work / lf.name).read_text())
        have = {str(r["i"]) for r in slide["regions"]}
        gone = [k for k in labels["regions"] if k not in have]
        new = [str(r["i"]) for r in worksheet_regions(slide) if str(r["i"]) not in labels["regions"]]
        patterns = [t for t in labels.get("text_patterns", []) if str(t["region"]) not in have]
        if not (gone or new or patterns):
            continue
        lists = (", ".join(f"{k} ({labels['regions'][k]})" for k in gone), ", ".join(str(t["region"]) for t in patterns),
                 ", ".join(f"{k} (other)" for k in new))
        report.append("{}: removed labels of regions no longer extracted: {}; removed text patterns of: {}; "
                      "newly listed regions labelled: {}".format(lf.stem, *(s or "none" for s in lists)))
        labels["regions"] = {k: v for k, v in labels["regions"].items() if k in have} | dict.fromkeys(new, "other")
        labels["text_patterns"] = [t for t in labels.get("text_patterns", []) if t not in patterns]
        lf.write_text(json.dumps(labels, indent=1))
    return report


def validate(labels, slide):
    """Raise ValueError unless labels match the schema and cover exactly the worksheet's regions (or, for slides
    labelled before the cap, exactly every extracted region)."""
    errors = sorted(jsonschema.Draft202012Validator(SCHEMA).iter_errors(labels), key=str)
    if errors:
        raise ValueError("; ".join(f"{'/'.join(map(str, e.path)) or 'labels'}: {e.message}" for e in errors))
    want = {str(r["i"]) for r in worksheet_regions(slide)}
    if set(labels["regions"]) not in (want, {str(r["i"]) for r in slide["regions"]}):
        raise ValueError(f"region roles must cover exactly regions {sorted(want, key=int)}")
    texts = {r["i"] for r in slide["regions"] if r["type"] == "text" and str(r["i"]) in labels["regions"]}
    bad = [t["region"] for t in labels["text_patterns"] if t["region"] not in texts]
    if bad:
        raise ValueError(f"text_patterns refer to unlabelled or non-text region(s) {bad}")
