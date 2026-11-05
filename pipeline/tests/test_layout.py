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
    "kpi_row": {"kind": "kpi_row", "box": B, "n": 3, "direction": "v", "tile": "round"},
    "card_row": {"kind": "card_row", "box": B, "n": 3, "header_strip": True, "icon": True},
    "label_rows": {"kind": "label_rows", "box": B, "rows": 4, "cols": 3},
    "table": {"kind": "table", "box": B, "rows": 5, "cols": 4, "header_row": True, "harvey": True, "marks": "harvey",
              "highlight_col": 2},
    "chart_area": {"kind": "chart_area", "box": B, "chart_type": "column"},
    "image_area": {"kind": "image_area", "box": B, "variant": "device"},
    "steps": {"kind": "steps", "box": B, "n": 4, "direction": "h"},
    "timeline": {"kind": "timeline", "box": B, "workstreams": 3, "periods": 8, "milestones": True, "rounded": True,
                 "groups": 2},
    "roadmap": {"kind": "roadmap", "box": B, "phases": 3},
    "matrix": {"kind": "matrix", "box": B, "dots": 4},
    "tree": {"kind": "tree", "box": B, "levels": 3, "branching": 2},
    "funnel": {"kind": "funnel", "box": B, "stages": 4},
    "hub": {"kind": "hub", "box": B, "n": 5, "connectors": True, "cycle": True},
    "before_after": {"kind": "before_after", "box": B, "rows": 3},
    "takeaway": {"kind": "takeaway", "box": B},
    "quote": {"kind": "quote", "box": B},
    "hero_number": {"kind": "hero_number", "box": B},
    "section_divider": {"kind": "section_divider", "number": 2},
    "cover": {"kind": "cover"},
    "closing": {"kind": "closing"},
    "card_stack": {"kind": "card_stack", "box": B, "n": 4, "header_strip": True, "icon": True},
    "swimlane": {"kind": "swimlane", "box": B, "lanes": 3, "stages": 4, "curve": True},
    "journey": {"kind": "journey", "box": B, "n": 5, "curve": True, "persona": True},
    "flow_diagram": {"kind": "flow_diagram", "box": B, "n": 5, "arrangement": "grid", "icon": True},
    "device_row": {"kind": "device_row", "box": B, "n": 3, "device": "phone"},
    "stage_strip": {"kind": "stage_strip", "box": B, "n": 4, "active": 2},
    "gauge_row": {"kind": "gauge_row", "box": B, "n": 3, "direction": "h"},
    "network": {"kind": "network", "box": B, "n": 6},
    "map_callouts": {"kind": "map_callouts", "box": B, "n": 4},
    "bar_list": {"kind": "bar_list", "box": B, "n": 6, "groups": 2},
    "nested_circles": {"kind": "nested_circles", "box": B, "n": 3, "arrangement": "nested"},
    "link_list": {"kind": "link_list", "box": B, "n": 6, "cols": 2, "numbered": True},
    "impact_overlay": {"kind": "impact_overlay", "position": "middle"},
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


def test_label_rows_go_up_to_ten_rows():
    assert layout.validate(_lay({**EXAMPLES["label_rows"], "rows": 10}))["components"][0]["rows"] == 10


def test_upper_limits_of_the_extended_kinds():
    for c in ({**EXAMPLES["table"], "cols": 12, "highlight_col": 12, "marks": "check"},
              {**EXAMPLES["timeline"], "periods": 24, "groups": 6}, {**EXAMPLES["stage_strip"], "n": 6, "active": 6},
              {**EXAMPLES["card_stack"], "n": 8}, {**EXAMPLES["flow_diagram"], "n": 10},
              {**EXAMPLES["network"], "n": 12}, {**EXAMPLES["bar_list"], "n": 12, "groups": 4},
              {**EXAMPLES["swimlane"], "lanes": 6, "stages": 8}, {**EXAMPLES["map_callouts"], "n": 8},
              {**EXAMPLES["timeline"], "workstreams": 10}, {**EXAMPLES["nested_circles"], "n": 4,
                                                             "arrangement": "concentric"},
              {**EXAMPLES["nested_circles"], "n": 2}, {**EXAMPLES["link_list"], "n": 12, "cols": 3},
              {**EXAMPLES["link_list"], "n": 2, "cols": 1, "numbered": False}):
        assert layout.validate(_lay(c))["components"][0] == c


def test_impact_overlay_comes_last_and_counts_toward_the_cap():
    parent = [EXAMPLES["tracker"], EXAMPLES["logo"], *[EXAMPLES["quote"]] * 5]
    for position in ("top", "middle", "bottom"):
        overlay = {"kind": "impact_overlay", "position": position}
        assert layout.validate(_lay(*parent, overlay))["components"][-1] == overlay
    with pytest.raises(ValueError, match="components"):
        layout.validate(_lay(*parent, EXAMPLES["quote"], EXAMPLES["impact_overlay"]))  # nine with the overlay


def test_blank_slides_have_no_components_and_only_blank_slides_may():
    assert layout.validate({"version": 3, "blank": True, "components": []})["components"] == []
    for bad in ({"version": 3, "components": []}, {"version": 3, "blank": True, "components": [EXAMPLES["logo"]]},
                {"version": 3, "blank": False, "components": [EXAMPLES["logo"]]}):
        with pytest.raises(ValueError):
            layout.validate(bad)


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
    (_lay({**EXAMPLES["label_rows"], "rows": 11}), "rows"),
    (_lay({**EXAMPLES["table"], "rows": 13}), "rows"),
    (_lay({**EXAMPLES["table"], "cols": 13}), "cols"),
    (_lay({**EXAMPLES["table"], "marks": "stars"}), "stars"),
    (_lay({**EXAMPLES["table"], "highlight_col": 5}), "highlight_col"),
    (_lay({**EXAMPLES["kpi_row"], "direction": "d"}), "direction"),
    (_lay({**EXAMPLES["kpi_row"], "tile": "hex"}), "hex"),
    (_lay({**EXAMPLES["chart_area"], "chart_type": "radar"}), "radar"),
    (_lay({"kind": "chart_area", "box": B}), "chart_type"),
    (_lay({**EXAMPLES["image_area"], "variant": "video"}), "video"),
    (_lay({**EXAMPLES["steps"], "direction": "diagonal"}), "diagonal"),
    (_lay({**EXAMPLES["steps"], "n": 9}), "n"),
    (_lay({**EXAMPLES["timeline"], "periods": 25}), "periods"),
    (_lay({**EXAMPLES["timeline"], "groups": 7}), "groups"),
    (_lay({**EXAMPLES["timeline"], "periods": 2, "groups": 3}), "groups"),
    (_lay({**EXAMPLES["card_stack"], "n": 1}), "n"),
    (_lay({**EXAMPLES["card_stack"], "n": 9}), "n"),
    (_lay({**EXAMPLES["swimlane"], "lanes": 7}), "lanes"),
    (_lay({**EXAMPLES["swimlane"], "stages": 9}), "stages"),
    (_lay({**EXAMPLES["journey"], "n": 2}), "n"),
    (_lay({**EXAMPLES["journey"], "n": 9}), "n"),
    (_lay({**EXAMPLES["flow_diagram"], "n": 11}), "n"),
    (_lay({**EXAMPLES["flow_diagram"], "arrangement": "circle"}), "circle"),
    (_lay({**EXAMPLES["device_row"], "n": 7}), "n"),
    (_lay({**EXAMPLES["device_row"], "device": "watch"}), "watch"),
    (_lay({**EXAMPLES["stage_strip"], "n": 7}), "n"),
    (_lay({**EXAMPLES["stage_strip"], "active": 5}), "active"),
    (_lay({**EXAMPLES["gauge_row"], "n": 7}), "n"),
    (_lay({**EXAMPLES["network"], "n": 2}), "n"),
    (_lay({**EXAMPLES["network"], "n": 13}), "n"),
    (_lay({**EXAMPLES["map_callouts"], "n": 9}), "n"),
    (_lay({**EXAMPLES["bar_list"], "n": 13}), "n"),
    (_lay({**EXAMPLES["bar_list"], "n": 2, "groups": 3}), "groups"),
    (_lay({**EXAMPLES["timeline"], "workstreams": 11}), "workstreams"),
    (_lay({**EXAMPLES["nested_circles"], "n": 1}), "n"),
    (_lay({**EXAMPLES["nested_circles"], "n": 5}), "n"),
    (_lay({**EXAMPLES["nested_circles"], "arrangement": "spiral"}), "spiral"),
    (_lay({**EXAMPLES["link_list"], "n": 1}), "n"),
    (_lay({**EXAMPLES["link_list"], "n": 13}), "n"),
    (_lay({**EXAMPLES["link_list"], "cols": 4}), "cols"),
    (_lay({**EXAMPLES["roadmap"], "phases": 7}), "phases"),
    (_lay({**EXAMPLES["matrix"], "dots": 9}), "dots"),
    (_lay({**EXAMPLES["tree"], "levels": 5}), "levels"),
    (_lay({**EXAMPLES["tree"], "levels": 4, "branching": 3}), "leaves"),
    (_lay({**EXAMPLES["funnel"], "stages": 7}), "stages"),
    (_lay({**EXAMPLES["hub"], "n": 2}), "n"),
    (_lay({**EXAMPLES["hub"], "n": 9}), "n"),
    (_lay({**EXAMPLES["hub"], "cycle": "yes"}), "cycle"),
    (_lay({**EXAMPLES["before_after"], "rows": 5}), "rows"),
    (_lay({**EXAMPLES["section_divider"], "number": 10}), "number"),
    (_lay({**EXAMPLES["matrix"], "harvey": True}), "harvey"),  # a field of another kind
    (_lay(EXAMPLES["impact_overlay"], EXAMPLES["quote"]), "impact_overlay"),  # drawn over what precedes it
    (_lay(EXAMPLES["quote"], EXAMPLES["impact_overlay"], EXAMPLES["impact_overlay"]), "impact_overlay"),
    (_lay({**EXAMPLES["impact_overlay"], "position": "left"}), "left"),
    (_lay({"kind": "impact_overlay"}), "position"),
    (_lay({**EXAMPLES["impact_overlay"], "box": B}), "box"),
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
    for needed in ("slide-02.png", '{"i": 0', str(out.absolute() / "slide-02.v3.json"), "do not write or change",
                   "layout.v3.json", '"version": 3', "8 components", "12 x 8", "zoomed out", "optional", *EXAMPLES,
                   "stacked_bar", "photo", "device", '"blank": true'):
        assert needed in text, needed
    assert "labels/slide-02.json" not in text and "archetype" not in text  # layouts only: labels stay as they are


def test_worksheet_slide_filter(deck_id, lib):
    main(["layout-prep", deck_id, "--library", str(lib), "--slides", "2"])
    assert [p.name for p in (lib / "layouts" / deck_id).glob("*.prompt.txt")] == ["slide-02.prompt.txt"]
