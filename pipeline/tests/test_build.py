import copy
import io
import json
import re

import jsonschema
import pytest
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData

from pipeline import build, extract, label_prep
from pipeline.tests.conftest import fixture_labels


def _label(lib, deck_id):
    work = lib / "work" / deck_id
    for f in sorted(work.glob("slide-??.json")):
        (work / "labels" / f.name).write_text(json.dumps(fixture_labels(json.loads(f.read_text()))))
    return work


@pytest.fixture
def built(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    label_prep.run(deck_id, lib)
    work = _label(lib, deck_id)
    ids = build.run(deck_id, lib)
    return work / "build", ids


def _dna(out, rid):
    return json.loads((out / f"{rid}.json").read_text())


def test_records_validate_against_versioned_schema(built):
    out, ids = built
    assert len(ids) == 2 and all(re.fullmatch(r"[0-9a-f]{16}-0[12]", i) for i in ids)
    for rid in ids:
        build.check_schema(_dna(out, rid))


@pytest.mark.parametrize("field", ["client", "competition", "year", "team", "source"])
def test_schema_has_no_room_for_identifying_fields(built, field):
    out, ids = built
    dna = _dna(out, ids[0])
    with pytest.raises(jsonschema.ValidationError):
        build.check_schema(dict(dna, **{field: "x"}))
    dna["regions"][0][field] = "x"
    with pytest.raises(jsonschema.ValidationError):
        build.check_schema(dna)


def test_dna_merges_geometry_and_labels(built):
    out, ids = built
    dna = _dna(out, ids[0])
    assert dna["archetype"] == "title" and dna["industry"] == "travel-hospitality"
    assert [r["role"] for r in dna["regions"]][:3] == ["card", "title", "big-number"]
    assert dna["regions"][1]["text"]["pattern"] == "outcome promise as a short noun phrase"
    assert dna["regions"][1]["text"]["pattern_words"] == 6
    assert dna["regions"][0]["box"] == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.2667}


def test_description_uses_fixed_template_without_digits(built):
    out, ids = built
    dna = _dna(out, ids[0])
    d = dna["description"]
    assert d.startswith("Title slide. Single claim argument, big number device, kpi numbers data, travel hospitality.")
    assert dna["purpose"] in d and dna["why_it_works"] in d and "outcome promise" in d
    assert not re.search(r"\d", d)


def test_build_refuses_missing_or_invalid_labels(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    label_prep.run(deck_id, lib)
    with pytest.raises(SystemExit, match="slide-01"):
        build.run(deck_id, lib)
    work = _label(lib, deck_id)
    bad = json.loads((work / "labels" / "slide-02.json").read_text()) | {"client": "x"}
    (work / "labels" / "slide-02.json").write_text(json.dumps(bad))
    with pytest.raises(SystemExit, match="slide-02"):
        build.run(deck_id, lib)
    assert not list((work / "build").glob("*")) if (work / "build").exists() else True


def test_wireframe_is_small_greyscale_skeleton(built):
    out, ids = built
    for rid in ids:
        png = (out / f"{rid}.png").read_bytes()
        assert len(png) <= 30 * 1024
        img = Image.open(io.BytesIO(png))
        assert img.mode == "L" and img.size in ((960, 540), (640, 360))


def test_brand_fills_darker_than_light_fills(built):
    out, ids = built
    s1 = Image.open(out / f"{ids[0]}.png")
    s2 = Image.open(out / f"{ids[1]}.png")
    w, h = s1.size
    band = s1.getpixel((3, 3))
    dna2 = _dna(out, ids[1])
    card = next(r for r in dna2["regions"] if r["fill"] == "neutral-light")["box"]
    light = s2.getpixel((int((card["x"] + card["w"] / 2) * w), int((card["y"] + card["h"] / 2) * h)))
    assert band < 120 < light


def test_wireframe_ignores_real_chart_values(deck, lib, tmp_path):
    prs = Presentation(str(deck))
    chart = next(s for s in prs.slides[1].shapes if getattr(s, "has_chart", False)).chart
    data = CategoryChartData()
    data.categories = ["A", "B", "C"]
    data.add_series("S", (1, 99, 5))
    chart.replace_data(data)
    other = tmp_path / "other.pptx"
    prs.save(other)
    charts = []
    for src in (deck, other):
        deck_id = extract.run(src, lib, render=False)
        s2 = json.loads((lib / "work" / deck_id / "slide-02.json").read_text())
        charts.append(next(r for r in s2["regions"] if r["type"] == "chart"))
    assert charts[0] == charts[1]


def test_wireframe_is_a_pure_function_of_the_dna(built):
    out, ids = built
    dna = _dna(out, ids[1])
    assert build.wireframe(dna) == build.wireframe(copy.deepcopy(dna)) == (out / f"{ids[1]}.png").read_bytes()
    pie = copy.deepcopy(dna)
    next(r for r in pie["regions"] if r["type"] == "chart")["chart"]["kind"] = "PIE"
    assert build.wireframe(pie) != build.wireframe(dna)


def test_number_tokens_never_carry_real_digits():
    assert [build.TOKENS[k] for k in ("percent", "currency", "multiple", "plain")] == ["##%", "$##M", "##x", "##"]


def test_dense_slide_stays_under_size_cap(built):
    out, ids = built
    dna = _dna(out, ids[1])
    base = [r for r in dna["regions"] if r["parent"] is None]
    regions = []
    for k in range(6):
        for r in base:
            r = copy.deepcopy(r)
            r["i"], r["box"] = len(regions), {"x": (k % 3) / 3, "y": (k // 3) / 2, "w": 0.32, "h": 0.48}
            regions.append(r)
    assert len(build.wireframe(dict(dna, regions=regions))) <= 30 * 1024


def test_tiny_text_box_draws_without_error(built):
    out, ids = built
    dna = _dna(out, ids[1])
    r = next(r for r in dna["regions"] if r["text"] and not r["text"]["number"] and r["role"] != "big-number"
             and not r["chart"] and not r["table"])
    r["box"] = {"x": 0.5, "y": 0.5, "w": 0.005, "h": 0.05}
    assert Image.open(io.BytesIO(build.wireframe(dna))).mode == "L"
