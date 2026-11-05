import json

import pytest

from pipeline import extract, layout
from pipeline.__main__ import main

B = [0.0, 0.0, 0.5, 0.5]
# One valid component of every kind, with every optional field set.
EXAMPLES = {
    "tracker": {"kind": "tracker", "n": 4, "active": 2},
    "logo": {"kind": "logo"},
    "text": {"kind": "text", "box": B, "bullets": True, "lines": 3},
    "kpi_row": {"kind": "kpi_row", "box": B, "n": 3},
    "card_row": {"kind": "card_row", "box": B, "n": 3, "header_strip": True, "icon": True},
    "label_rows": {"kind": "label_rows", "box": B, "rows": 4, "cols": 3},
    "table": {"kind": "table", "box": B, "rows": 5, "cols": 4, "header_row": True, "harvey": True},
    "chart_area": {"kind": "chart_area", "box": B, "chart_type": "column"},
    "image_area": {"kind": "image_area", "box": B, "variant": "device"},
    "steps": {"kind": "steps", "box": B, "n": 4, "direction": "h"},
    "timeline": {"kind": "timeline", "box": B, "workstreams": 3, "periods": 8, "milestones": True},
    "roadmap": {"kind": "roadmap", "box": B, "phases": 3},
    "matrix": {"kind": "matrix", "box": B, "dots": 4},
    "tree": {"kind": "tree", "box": B, "levels": 3, "branching": 2},
    "funnel": {"kind": "funnel", "box": B, "stages": 4},
    "before_after": {"kind": "before_after", "box": B, "rows": 3},
    "takeaway": {"kind": "takeaway", "box": B},
    "quote": {"kind": "quote", "box": B},
    "hero_number": {"kind": "hero_number", "box": B},
    "section_divider": {"kind": "section_divider", "number": 2},
    "cover": {"kind": "cover"},
    "closing": {"kind": "closing"},
}

SAMPLE = {"version": 3, "components": [
    {"kind": "tracker", "n": 4, "active": 2},
    {"kind": "logo"},
    {"kind": "label_rows", "box": [0, 0, 1, 0.75], "rows": 4, "cols": 3},
    {"kind": "takeaway", "box": [0, 0.875, 1, 0.125]},
]}


def _lay(*components):
    return {"version": 3, "components": list(components)}


# --- schema ---------------------------------------------------------------------------------------------------

def test_every_kind_has_an_example():
    assert set(EXAMPLES) == set(layout.KINDS) == set(layout.SCHEMA["$defs"]["component"]["properties"]["kind"]["enum"])


@pytest.mark.parametrize("kind", EXAMPLES)
def test_each_kind_validates(kind):
    assert layout.validate(_lay(EXAMPLES[kind]))["components"][0]["kind"] == kind


def test_sample_on_grid_validates_unchanged():
    assert layout.validate(SAMPLE) == SAMPLE


def test_boxes_snap_to_the_12_by_8_grid():
    out = layout.validate(_lay({"kind": "text", "box": [0.07, 0.3, 0.45, 0.02], "lines": 1}))
    assert out["components"][0]["box"] == [1 / 12, 2 / 8, 5 / 12, 1 / 8]  # at least one cell high
    out = layout.validate(_lay({"kind": "quote", "box": [0.99, 0.99, 0.01, 0.01]}))
    assert out["components"][0]["box"] == [11 / 12, 7 / 8, 1 / 12, 1 / 8]  # stays on the slide
    raw = {"kind": "quote", "box": [0.07, 0.3, 0.45, 0.02]}
    layout.validate(_lay(raw))
    assert raw["box"] == [0.07, 0.3, 0.45, 0.02]  # input untouched


def _strings_without_enum(node):
    if isinstance(node, dict):
        if node.get("type") == "string" and "enum" not in node:
            yield node
        for v in node.values():
            yield from _strings_without_enum(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings_without_enum(v)


def test_schema_has_no_free_text_fields():
    assert list(_strings_without_enum(layout.SCHEMA)) == []
    for kind, d in layout.SCHEMA["$defs"].items():
        if kind in EXAMPLES:
            assert d["additionalProperties"] is False, kind


@pytest.mark.parametrize("bad, message", [
    (_lay({**EXAMPLES["text"], "text": "Revenue up"}), "text"),
    (_lay({**EXAMPLES["quote"], "label": "Revenue"}), "label"),
    ({**SAMPLE, "title": "Q3 results"}, "title"),
    ({**SAMPLE, "version": 2}, "version"),
    ({"version": 3, "components": []}, "components"),
    (_lay(*[EXAMPLES["quote"]] * 9), "components"),
    (_lay({"kind": "headline", "box": B}), "headline"),
    (_lay({"kind": "text", "lines": 2}), "box"),
    (_lay({**EXAMPLES["logo"], "box": B}), "box"),
    (_lay({**EXAMPLES["quote"], "box": [0.1, 0.1, 0.95, 0.1]}), "box"),
    (_lay({**EXAMPLES["quote"], "box": [0.1, 0.1, 0.2]}), "box"),
    (_lay({**EXAMPLES["quote"], "box": [0.1, 0.1, 1.2, 0.1]}), "box"),
    (_lay({**EXAMPLES["tracker"], "n": 9}), "n"),
    (_lay({**EXAMPLES["tracker"], "n": 1}), "n"),
    (_lay({**EXAMPLES["tracker"], "active": 5}), "active"),
    (_lay({"kind": "tracker", "n": 3}), "active"),
    (_lay(EXAMPLES["tracker"], EXAMPLES["tracker"]), "tracker"),
    (_lay(EXAMPLES["cover"], EXAMPLES["closing"]), "full-slide"),
    (_lay({**EXAMPLES["text"], "lines": 9}), "lines"),
    (_lay({**EXAMPLES["text"], "bullets": "yes"}), "bullets"),
    (_lay({**EXAMPLES["kpi_row"], "n": 7}), "n"),
    (_lay({**EXAMPLES["card_row"], "n": 0}), "n"),
    (_lay({**EXAMPLES["label_rows"], "cols": 5}), "cols"),
    (_lay({**EXAMPLES["table"], "rows": 13}), "rows"),
    (_lay({**EXAMPLES["table"], "cols": 9}), "cols"),
    (_lay({**EXAMPLES["chart_area"], "chart_type": "radar"}), "radar"),
    (_lay({"kind": "chart_area", "box": B}), "chart_type"),
    (_lay({**EXAMPLES["image_area"], "variant": "video"}), "video"),
    (_lay({**EXAMPLES["steps"], "direction": "diagonal"}), "diagonal"),
    (_lay({**EXAMPLES["steps"], "n": 9}), "n"),
    (_lay({**EXAMPLES["timeline"], "periods": 13}), "periods"),
    (_lay({**EXAMPLES["timeline"], "workstreams": 7}), "workstreams"),
    (_lay({**EXAMPLES["roadmap"], "phases": 7}), "phases"),
    (_lay({**EXAMPLES["matrix"], "dots": 9}), "dots"),
    (_lay({**EXAMPLES["tree"], "levels": 5}), "levels"),
    (_lay({**EXAMPLES["tree"], "levels": 4, "branching": 3}), "leaves"),
    (_lay({**EXAMPLES["funnel"], "stages": 7}), "stages"),
    (_lay({**EXAMPLES["before_after"], "rows": 5}), "rows"),
    (_lay({**EXAMPLES["section_divider"], "number": 10}), "number"),
    (_lay({**EXAMPLES["matrix"], "harvey": True}), "harvey"),  # a field of another kind
])
def test_invalid_layouts_fail(bad, message):
    with pytest.raises(ValueError, match=message):
        layout.validate(bad)


# --- worksheet ------------------------------------------------------------------------------------------------

@pytest.fixture
def deck_id(deck, lib):
    return extract.run(deck, lib, render=False)


def test_worksheet_shows_the_picture_and_the_components(deck_id, lib):
    main(["layout-prep", deck_id, "--library", str(lib)])
    out = lib / "layouts" / deck_id
    assert sorted(p.name for p in out.glob("*.prompt.txt")) == ["slide-01.prompt.txt", "slide-02.prompt.txt"]
    text = (out / "slide-02.prompt.txt").read_text()
    for needed in ("slide-02.png", str(lib / "work" / deck_id / "slide-02.json"), str(out / "slide-02.v3.json"),
                   "layout.v3.json", '"version": 3', "8 components", "12 x 8", "zoomed out", "optional", *EXAMPLES,
                   "stacked_bar", "photo", "device"):
        assert needed in text, needed
    assert (out / "slide-01.prompt.txt").read_text().replace("slide-01", "slide-02") == text


def test_worksheet_slide_filter(deck_id, lib):
    main(["layout-prep", deck_id, "--library", str(lib), "--slides", "2"])
    assert [p.name for p in (lib / "layouts" / deck_id).glob("*.prompt.txt")] == ["slide-02.prompt.txt"]
