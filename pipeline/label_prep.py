"""Stage 2: write a labeling worksheet per slide, and validate the labels written back in the user's session."""
import json
from pathlib import Path

import jsonschema

HERE = Path(__file__).parent
SCHEMA = json.loads((HERE / "schema" / "labels.v1.json").read_text())
TEMPLATE = (HERE / "templates" / "labeling.txt").read_text()


def run(deck_id, library):
    work = Path(library) / "work" / deck_id
    (work / "labels").mkdir(exist_ok=True)
    p = SCHEMA["properties"]
    enums = {k: ", ".join(p[k]["enum"]) for k in ("archetype", "argument_shape", "insight_device", "data_type", "industry")}
    for f in sorted(work.glob("slide-??.json")):
        (work / f"{f.stem}.prompt.txt").write_text(TEMPLATE.format(
            slide=f.stem, archetypes=enums["archetype"], argument_shapes=enums["argument_shape"],
            insight_devices=enums["insight_device"], data_types=enums["data_type"], industries=enums["industry"],
            roles=", ".join(SCHEMA["$defs"]["role"]["enum"])))
    return work


def validate(labels, slide):
    """Raise ValueError unless labels match the schema and cover exactly the slide's extracted regions."""
    errors = sorted(jsonschema.Draft202012Validator(SCHEMA).iter_errors(labels), key=str)
    if errors:
        raise ValueError("; ".join(f"{'/'.join(map(str, e.path)) or 'labels'}: {e.message}" for e in errors))
    want = {str(r["i"]) for r in slide["regions"]}
    if set(labels["regions"]) != want:
        raise ValueError(f"region roles must cover exactly regions {sorted(want, key=int)}")
    texts = {r["i"] for r in slide["regions"] if r["type"] == "text"}
    bad = [t["region"] for t in labels["text_patterns"] if t["region"] not in texts]
    if bad:
        raise ValueError(f"text_patterns refer to non-text region(s) {bad}")
