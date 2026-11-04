import json

import pytest

from pipeline import extract, layout
from pipeline.__main__ import main


def _el(kind, box, shape="none", **kw):
    return dict(kind=kind, shape=shape, box=list(box), **kw)


V1 = {"elements": [
    _el("band", (0, 0, 1, 0.2), "rect"),
    _el("title", (0.05, 0.05, 0.6, 0.1)),
    _el("card", (0.05, 0.3, 0.4, 0.5), "round_rect", region_ids=[1, 2]),
    _el("number", (0.1, 0.35, 0.3, 0.3), emphasis="hero"),
    _el("bar_chart", (0.55, 0.3, 0.4, 0.5), "rect"),
    _el("connector", (0.45, 0.5, 0.1, 0.05), "line", **{"from": 2, "to": 4}, dashed=True),
    _el("panel", (0.5, 0.25, 0.48, 0.6), "polygon", points=[[0.5, 0.25], [0.98, 0.25], [0.98, 0.85]]),
    _el("line_chart", (0.1, 0.8, 0.2, 0.1), "rect"),
    _el("pie_chart", (0.3, 0.8, 0.1, 0.1), "ellipse"),
    _el("chart", (0.4, 0.8, 0.1, 0.1), "rect"),
    _el("table", (0.6, 0.8, 0.2, 0.1), "rect"),
    _el("arrow", (0.8, 0.8, 0.1, 0.05), "arrow_right"),
    _el("arrow", (0.8, 0.9, 0.1, 0.05), "chevron"),
    _el("arrow", (0.9, 0.9, 0.1, 0.05), "line"),
]}

SAMPLE = {"version": 2, "elements": [
    _el("band", (0, 0, 1, 0.2), "rect", fill="mid"),
    _el("title", (0.05, 0.05, 0.6, 0.1), parent=0),
    _el("card", (0.05, 0.3, 0.4, 0.5), "round_rect", region_ids=[1, 2], fill="light"),
    _el("number", (0.1, 0.35, 0.3, 0.3), emphasis="hero", parent=2, framed=False),
    _el("chart", (0.55, 0.3, 0.4, 0.5), "rect", chart_type="stacked_bar", series=3, categories=5),
    _el("connector", (0.45, 0.5, 0.1, 0.05), "line", **{"from": 2, "to": 4}, dashed=True, head="both"),
    _el("strip", (0.5, 0.25, 0.1, 0.6), "rect", fill="none"),
    _el("table", (0.6, 0.8, 0.2, 0.1), "rect", rows=4, cols=3, header_row=True),
    _el("arrow", (0.8, 0.8, 0.1, 0.05), "arrow_right", arrow_style="block"),
    _el("takeaway", (0.1, 0.85, 0.4, 0.1), framed=True),
    _el("panel", (0.5, 0.25, 0.48, 0.6), "polygon", points=[[0.5, 0.25], [0.98, 0.25], [0.98, 0.85]]),
]}


# --- schema ---------------------------------------------------------------------------------------------------

def test_sample_layout_validates_unchanged():
    assert layout.validate(SAMPLE) == SAMPLE


def test_v1_layout_upgrades_to_v2():
    v2 = layout.validate(V1)
    els = v2["elements"]
    assert v2["version"] == 2 and len(els) == len(V1["elements"]) and "version" not in V1
    assert [(e["kind"], e.get("chart_type")) for e in els[7:10]] == [("chart", "line"), ("chart", "pie"), ("chart", "column")]
    assert (els[4]["kind"], els[4]["chart_type"]) == ("chart", "column")
    assert (els[10]["rows"], els[10]["cols"]) == (3, 3)
    assert [e["arrow_style"] for e in els[11:14]] == ["block", "chevron", "line"]
    assert els[5]["head"] == "end" and els[5]["from"] == 2 and els[5]["dashed"] is True
    assert els[0] == V1["elements"][0] and els[2]["region_ids"] == [1, 2]  # everything else carries over
    assert layout.validate(v2) == v2


def test_upgrade_needs_a_valid_v1_layout():
    with pytest.raises(ValueError, match="text"):
        layout.validate({"elements": [_el("title", (0, 0, 0.5, 0.1), text="Revenue up")]})


def _strings_without_enum(node):
    if isinstance(node, dict):
        if node.get("type") == "string" and "enum" not in node:
            yield node
        for v in node.values():
            yield from _strings_without_enum(v)
    elif isinstance(node, list):
        for v in node:
            yield from _strings_without_enum(v)


@pytest.mark.parametrize("schema", [layout.SCHEMA, layout.SCHEMA_V1])
def test_schema_has_no_free_text_fields(schema):
    assert list(_strings_without_enum(schema)) == []


@pytest.mark.parametrize("mutate, message", [
    (lambda l: l["elements"][1].update(text="Revenue up"), "text"),
    (lambda l: l["elements"][1].update(label="Revenue"), "label"),
    (lambda l: l.update(title="Q3 results"), "title"),
    (lambda l: l.update(version=3), "version"),
    (lambda l: l["elements"][1].update(kind="headline"), "headline"),
    (lambda l: l["elements"][1].update(kind="bar_chart"), "bar_chart"),
    (lambda l: l["elements"][1].update(shape="star"), "star"),
    (lambda l: l["elements"][1].update(box=[0.1, 0.1, 1.2, 0.1]), "box"),
    (lambda l: l["elements"][1].update(box=[0.1, 0.1, 0.2]), "box"),
    (lambda l: l["elements"][1].update(emphasis="loud"), "loud"),
    (lambda l: l["elements"][10].update(points=[[0.1, 0.1]] * 13), "points"),
    (lambda l: l["elements"].extend([_el("text", (0, 0, 0.1, 0.1))] * 15), "elements"),
    (lambda l: l["elements"][5].update(to=99), "to"),
    (lambda l: l["elements"][4].pop("chart_type"), "chart_type"),
    (lambda l: l["elements"][4].update(chart_type="radar"), "radar"),
    (lambda l: l["elements"][4].update(series=7), "series"),
    (lambda l: l["elements"][4].update(categories=13), "categories"),
    (lambda l: l["elements"][1].update(chart_type="pie"), "kind"),
    (lambda l: l["elements"][7].pop("rows"), "rows"),
    (lambda l: l["elements"][7].update(cols=21), "cols"),
    (lambda l: l["elements"][7].update(rows=0), "rows"),
    (lambda l: l["elements"][4].update(header_row=True), "kind"),
    (lambda l: l["elements"][8].update(arrow_style="curly"), "curly"),
    (lambda l: l["elements"][2].update(arrow_style="block"), "kind"),
    (lambda l: l["elements"][5].update(head="start"), "start"),
    (lambda l: l["elements"][2].update(head="end"), "kind"),
    (lambda l: l["elements"][8].update(**{"from": 0}), "kind"),
    (lambda l: l["elements"][1].update(fill="mid"), "kind"),
    (lambda l: l["elements"][0].update(fill="black"), "black"),
    (lambda l: l["elements"][4].update(framed=True), "kind"),
    (lambda l: l["elements"][1].update(parent=5), "parent"),   # parent listed after the child
    (lambda l: l["elements"][3].update(parent=1), "parent"),   # parent is not a container
    (lambda l: l["elements"][3].update(parent=3), "parent"),   # its own parent
    (lambda l: l["elements"].append(_el("logo", (0, 0, 0.1, 0.1), "polygon", points=[[0, 0], [0.1, 0.1]])), "points"),
])
def test_invalid_layouts_fail(mutate, message):
    bad = json.loads(json.dumps(SAMPLE))
    mutate(bad)
    with pytest.raises(ValueError, match=message):
        layout.validate(bad)


# --- snap -----------------------------------------------------------------------------------------------------

SLIDE = {"regions": [{"i": 0, "box": {"x": 0.0, "y": 0.0, "w": 1.0, "h": 1.0}},
                     {"i": 1, "box": {"x": 0.1, "y": 0.2, "w": 0.2, "h": 0.1}},
                     {"i": 2, "box": {"x": 0.25, "y": 0.4, "w": 0.3, "h": 0.2}}]}


def test_snap_replaces_box_with_union_of_regions():
    out = layout.snap(SAMPLE, SLIDE)
    assert out["elements"][2]["box"] == pytest.approx([0.1, 0.2, 0.45, 0.4])
    assert out["elements"][1]["box"] == SAMPLE["elements"][1]["box"]  # no region_ids: the agent's box stays
    assert SAMPLE["elements"][2]["box"] == [0.05, 0.3, 0.4, 0.5]  # input untouched


def test_snap_rejects_unknown_regions():
    with pytest.raises(ValueError, match="9"):
        layout.snap({"elements": [_el("text", (0, 0, 0.1, 0.1), region_ids=[9])]}, SLIDE)


# --- worksheet + render command -------------------------------------------------------------------------------

@pytest.fixture
def deck_id(deck, lib):
    return extract.run(deck, lib, render=False)


def test_worksheet_combines_picture_and_regions(deck_id, lib):
    main(["layout-prep", deck_id, "--library", str(lib)])
    out = lib / "layouts" / deck_id
    assert sorted(p.name for p in out.glob("*.prompt.txt")) == ["slide-01.final.prompt.txt", "slide-02.final.prompt.txt"]
    text = (out / "slide-02.final.prompt.txt").read_text()
    for needed in ("slide-02.png", str(lib / "work" / deck_id / "slide-02.json"), str(out / "slide-02.final.json"),
                   "layout.v2.json", '"version": 2', "5-20", "chevron", "region_ids", "clearly matches",
                   "Merge stacked text lines", "decoration", "background texture", "connectors", "insight device",
                   "takeaway", "strip", "parent", "framed", "rows", "cols", "header_row", "chart_type", "stacked_bar",
                   "waterfall", "series", "categories", "arrow_style", "block", "head", "fill"):
        assert needed in text, needed
    assert "bar_chart" not in text
    assert (out / "slide-01.final.prompt.txt").read_text().replace("slide-01", "slide-02") == text


def test_worksheet_slide_filter(deck_id, lib):
    main(["layout-prep", deck_id, "--library", str(lib), "--slides", "2"])
    assert [p.name for p in (lib / "layouts" / deck_id).glob("*.prompt.txt")] == ["slide-02.final.prompt.txt"]
