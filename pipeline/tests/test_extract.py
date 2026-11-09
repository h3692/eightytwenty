import inspect
import json
import re
import shutil

import pytest
from PIL import Image

from pipeline import extract
from pipeline.tests.conftest import CLIENT, EXCLUDED


def _all_bytes(root):
    return {p: p.read_bytes().lower() for p in root.rglob("*") if p.is_file()}


def _slides(lib, deck_id):
    return [json.loads((lib / "work" / deck_id / f"slide-{n:02d}.json").read_text()) for n in (1, 2)]


def test_deck_id_is_random_and_not_from_file_name(deck, lib):
    a = extract.run(deck, lib, render=False)
    b = extract.run(deck, lib, render=False)
    assert a != b
    assert re.fullmatch(r"[0-9a-f]{16}", a)


def test_hidden_slides_are_skipped(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    work = lib / "work" / deck_id
    assert sorted(p.name for p in work.glob("slide-*.json")) == ["slide-01.json", "slide-02.json"]


def test_no_excluded_channel_reaches_any_file(deck, lib):
    extract.run(deck, lib, render=False)
    for path, data in _all_bytes(lib).items():
        for channel, marker in EXCLUDED.items():
            assert marker.lower().encode() not in data, f"{channel} leaked into {path}"


def test_extracted_json_never_stores_words(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    for slide in _slides(lib, deck_id):
        text = json.dumps(slide).lower()
        assert CLIENT.lower() not in text and "loyalty" not in text and "42%" not in text
    # The slide text is kept only in the local work dir, for the leak check.
    assert CLIENT in (lib / "work" / deck_id / "text" / "slide-02.txt").read_text()


def test_shape_types_boxes_and_z_order(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    s1, s2 = _slides(lib, deck_id)
    types = [r["type"] for r in s2["regions"]]
    for t in ("text", "picture", "chart", "table", "group", "line"):
        assert t in types
    assert [r["i"] for r in s2["regions"]] == list(range(len(s2["regions"])))
    for r in s1["regions"] + s2["regions"]:
        b = r["box"]
        assert all(-0.01 <= v <= 1.01 for v in b.values())
    band = s1["regions"][0]
    assert band["box"] == {"x": 0.0, "y": 0.0, "w": 1.0, "h": 0.2667}


def test_group_children_are_flattened_with_slide_coordinates(deck, lib):
    s2 = _slides(lib, extract.run(deck, lib, render=False))[1]
    group = next(r for r in s2["regions"] if r["type"] == "group")
    kids = [r for r in s2["regions"] if r["parent"] == group["i"]]
    assert len(kids) == 2
    assert kids[0]["box"]["x"] == pytest.approx(10.5 / 13.333, abs=1e-3)
    assert kids[1]["box"]["y"] == pytest.approx(3.2 / 7.5, abs=1e-3)
    assert kids[1]["dashed"] is True and kids[0]["dashed"] is False


def test_chart_and_table_structure_counts_only(deck, lib):
    s2 = _slides(lib, extract.run(deck, lib, render=False))[1]
    chart = next(r for r in s2["regions"] if r["type"] == "chart")
    table = next(r for r in s2["regions"] if r["type"] == "table")
    assert chart["chart"] == {"kind": "COLUMN_CLUSTERED", "series": 1, "categories": 3}
    assert table["table"] == {"rows": 2, "cols": 3}


def test_colour_roles_relative_to_deck_palette(deck, lib):
    s1, s2 = _slides(lib, extract.run(deck, lib, render=False))
    assert s1["regions"][0]["fill"] == "primary"  # navy: most-used chromatic colour
    cards = [r for r in s2["regions"] if r["parent"] is not None]
    assert [c["fill"] for c in cards] == ["accent", "neutral-light"]
    assert s1["regions"][1]["text"]["color"] == "white"
    line = next(r for r in s2["regions"] if r["type"] == "line")
    assert line["line"] == "primary"


def test_text_structure_font_roles_numbers_and_alignment(deck, lib):
    s1, s2 = _slides(lib, extract.run(deck, lib, render=False))
    title, kpi = s1["regions"][1]["text"], s1["regions"][2]["text"]
    assert title["size"] == "display" and title["weight"] == "bold" and title["align"] == "center"
    assert title["number"] is None and title["words"] == 6 and title["lines"] == 1
    assert kpi["number"] == "percent" and kpi["size"] == "display"
    header, body = s2["regions"][0]["text"], s2["regions"][1]["text"]
    assert header["size"] == "heading"
    assert body["size"] == "body" and body["weight"] == "regular"
    assert (body["words"], body["paragraphs"], body["bullets"]) == (19, 3, 2)
    assert body["lines"] >= 3


def test_extractor_never_touches_excluded_channels():
    src = inspect.getsource(extract)
    for forbidden in ("notes_slide", "comment", "descr", "hyperlink", "click_action", "core_properties",
                      "docProps", "shape.name", "filename", "oleObj", "image.blob"):
        assert forbidden not in src, forbidden


def test_pdf_pages_become_pngs_scaled_to_1280(tmp_path):
    pdf = tmp_path / "deck.pdf"
    pages = [Image.new("RGB", (160, 90), c) for c in ("navy", "orange")]
    pages[0].save(pdf, save_all=True, append_images=pages[1:])
    extract._pdf_to_png(pdf, tmp_path, 2)
    pngs = sorted(tmp_path.glob("slide-*.png"))
    assert [p.name for p in pngs] == ["slide-01.png", "slide-02.png"]
    assert all(Image.open(p).size == (1280, 720) for p in pngs)


def test_render_without_libreoffice_says_so(deck, tmp_path, monkeypatch):
    monkeypatch.setattr(extract.shutil, "which", lambda _: None)
    monkeypatch.setattr(extract, "SOFFICE_APP", tmp_path / "missing" / "soffice")
    with pytest.raises(SystemExit, match="LibreOffice"):
        extract._render(deck, tmp_path, 2)


@pytest.mark.skipif(not (shutil.which("soffice") or extract.SOFFICE_APP.exists()), reason="LibreOffice not installed")
def test_render_writes_one_png_per_visible_slide(deck, lib):
    deck_id = extract.run(deck, lib)
    assert sorted(p.name for p in (lib / "work" / deck_id).glob("slide-*.png")) == ["slide-01.png", "slide-02.png"]


def _pdf(path, colours):
    pages = [Image.new("RGB", (160, 120), c) for c in colours]  # 4:3, like the IB decks
    pages[0].save(path, save_all=True, append_images=pages[1:])
    return path


def test_render_from_renders_the_given_pdf_pages_not_libreoffice(deck, lib, tmp_path, monkeypatch):
    from pipeline.__main__ import main
    monkeypatch.setattr(extract, "_render", lambda *_: pytest.fail("LibreOffice render used"))
    pdf = _pdf(tmp_path / "deck.pdf", ("navy", "orange"))
    main(["extract", str(deck), "--render-from", str(pdf), "--library", str(lib)])
    pngs = sorted((lib / "work").glob("*/slide-*.png"))
    assert [p.name for p in pngs] == ["slide-01.png", "slide-02.png"]
    assert all(Image.open(p).size == (1280, 960) for p in pngs)
    assert Image.open(pngs[1]).convert("RGB").getpixel((640, 480)) == (255, 165, 0)


def test_render_from_refuses_a_pdf_whose_page_count_differs_from_the_slides(deck, lib, tmp_path):
    pdf = _pdf(tmp_path / "deck.pdf", ("navy", "orange", "white"))
    with pytest.raises(SystemExit, match="3 pages but the deck has 2 visible slides"):
        extract.run(deck, lib, render_from=pdf)
    assert not (lib / "work").exists()  # refused before anything is written


def test_pdf_import_never_overwrites_a_deck_file(lib, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(extract.subprocess, "run", lambda *a, **k: calls.append(a))
    (lib / "decks").mkdir(parents=True, exist_ok=True)
    (lib / "decks" / "pitch.pptx").write_bytes(b"original")
    (tmp_path / "pitch.pdf").write_bytes(b"%PDF")
    with pytest.raises(SystemExit, match="already"):
        extract.run(tmp_path / "pitch.pdf", lib)
    assert calls == [] and (lib / "decks" / "pitch.pptx").read_bytes() == b"original"


def test_pdf_import_refuses_when_libreoffice_writes_no_deck(lib, tmp_path, monkeypatch):
    # soffice exits 0 without converting when another LibreOffice instance is running
    monkeypatch.setattr(extract, "_soffice", lambda: "soffice")
    monkeypatch.setattr(extract.subprocess, "run", lambda *a, **k: None)
    (tmp_path / "pitch.pdf").write_bytes(b"%PDF")
    with pytest.raises(SystemExit, match="LibreOffice"):
        extract.run(tmp_path / "pitch.pdf", lib)


@pytest.mark.skipif(not (shutil.which("soffice") or extract.SOFFICE_APP.exists()), reason="LibreOffice not installed")
def test_a_pdf_deck_is_converted_into_library_decks_and_rendered_from_the_pdf(lib, tmp_path):
    from pipeline.__main__ import main
    pdf = _pdf(tmp_path / "deck.pdf", ("navy", "orange"))
    main(["extract", str(pdf), "--library", str(lib)])
    assert (lib / "decks" / "deck.pptx").is_file()
    pngs = sorted((lib / "work").glob("*/slide-*.png"))
    assert [p.name for p in pngs] == ["slide-01.png", "slide-02.png"]
    assert Image.open(pngs[0]).size == (1280, 960)


def test_dash_presets_python_pptx_cannot_map_still_extract_as_dashed(tmp_path, lib):
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    for val in ("dot", "sysDashDot", "solid"):
        s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, 100, 100)
        s.line.width = 12700
        s.line._ln.get_or_add_prstDash().set("val", val)
    path = tmp_path / "dots.pptx"
    prs.save(path)
    deck_id = extract.run(path, lib, render=False)
    regions = json.loads((lib / "work" / deck_id / "slide-01.json").read_text())["regions"]
    assert [r["dashed"] for r in regions] == [True, True, False]


def test_preset_geometry_is_extracted_from_a_closed_vocabulary(tmp_path, lib):
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE
    prs = Presentation()
    slide = prs.slides.add_slide(prs.slide_layouts[6])
    for shape in (MSO_SHAPE.OVAL, MSO_SHAPE.ROUNDED_RECTANGLE, MSO_SHAPE.RECTANGLE, MSO_SHAPE.RECTANGLE):
        slide.shapes.add_shape(shape, 0, 0, 100, 100)
    slide.shapes[-1]._element.xpath("./p:spPr/a:prstGeom")[0].set("prst", "Zorblax")  # not an OOXML preset
    path = tmp_path / "geom.pptx"
    prs.save(path)
    deck_id = extract.run(path, lib, render=False)
    regions = json.loads((lib / "work" / deck_id / "slide-01.json").read_text())["regions"]
    assert [r["geom"] for r in regions] == ["ellipse", "roundRect", "rect", None]


def _freeform_deck(tmp_path, build):
    """One blank slide; build(slide) adds shapes. Returns the saved path."""
    from pptx import Presentation
    prs = Presentation()
    prs.slide_width, prs.slide_height = 12192000, 6858000
    build(prs.slides.add_slide(prs.slide_layouts[6]))
    path = tmp_path / "shapes.pptx"
    prs.save(path)
    return path


def _regions(path, lib):
    deck_id = extract.run(path, lib, render=False)
    return json.loads((lib / "work" / deck_id / "slide-01.json").read_text())["regions"]


CIRCLE = ('<a:custGeom xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:avLst/><a:gdLst/><a:ahLst/>'
          '<a:rect l="0" t="0" r="r" b="b"/><a:pathLst><a:path w="3155" h="3155">'
          '<a:moveTo><a:pt x="0" y="1578"/></a:moveTo>'
          '<a:cubicBezTo><a:pt x="0" y="706"/><a:pt x="706" y="0"/><a:pt x="1577" y="0"/></a:cubicBezTo>'
          '<a:cubicBezTo><a:pt x="2448" y="0"/><a:pt x="3155" y="706"/><a:pt x="3155" y="1578"/></a:cubicBezTo>'
          '<a:cubicBezTo><a:pt x="3155" y="2449"/><a:pt x="2448" y="3155"/><a:pt x="1577" y="3155"/></a:cubicBezTo>'
          '<a:cubicBezTo><a:pt x="706" y="3155"/><a:pt x="0" y="2449"/><a:pt x="0" y="1578"/></a:cubicBezTo>'
          '<a:close/></a:path></a:pathLst></a:custGeom>')


def _custom(slide, x, y, w, h, xml):
    from lxml import etree
    from pptx.enum.shapes import MSO_SHAPE
    s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
    prst = s._element.xpath("./p:spPr/a:prstGeom")[0]
    prst.addprevious(etree.fromstring(xml))
    prst.getparent().remove(prst)
    return s


def test_freeform_paths_are_normalised_simplified_and_capped(tmp_path, lib):
    import math
    def build(slide):
        zig = [(int(4000 * k / 99), int(3000 if k % 2 else 0) + int(1000 * math.sin(k))) for k in range(100)]
        ff = slide.shapes.build_freeform(*zig[0], scale=1000)  # 4 x 4 inches of points, a large shape
        ff.add_line_segments(zig[1:], close=True)
        ff.convert_to_shape()
        flat = slide.shapes.build_freeform(0, 0, scale=1000)
        flat.add_line_segments([(k * 100, 0) for k in range(1, 60)] + [(5900, 3000)], close=False)
        flat.convert_to_shape(1000000, 1000000)
    zig, flat = _regions(_freeform_deck(tmp_path, build), lib)
    for r in (zig, flat):
        assert r["geom"] is None
        pts = [p for sub in r["path"] for p in sub]
        assert all(isinstance(v, float) and 0 <= v <= 1 for p in pts for v in p)
    assert 3 <= sum(map(len, zig["path"])) <= 32
    assert zig["path"][0][0] == zig["path"][0][-1]  # closed outline repeats its start
    assert flat["path"] == [[[0.0, 0.0], [1.0, 0.0], [1.0, 1.0]]]  # 59 collinear points collapse into one segment


def test_near_circular_freeform_becomes_an_ellipse_but_squat_or_angular_ones_keep_their_path(tmp_path, lib):
    tri = ('<a:custGeom xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:pathLst><a:path w="100" h="100">'
           '<a:moveTo><a:pt x="50" y="0"/></a:moveTo><a:lnTo><a:pt x="100" y="100"/></a:lnTo>'
           '<a:lnTo><a:pt x="0" y="100"/></a:lnTo><a:close/></a:path></a:pathLst></a:custGeom>')
    regions = _regions(_freeform_deck(tmp_path, lambda s: (
        _custom(s, 0, 0, 2000000, 2000000, CIRCLE), _custom(s, 0, 0, 4000000, 1000000, CIRCLE),
        _custom(s, 0, 0, 2000000, 2000000, tri))), lib)
    assert (regions[0]["geom"], regions[0]["path"]) == ("ellipse", None)
    assert regions[1]["geom"] is None and len(regions[1]["path"][0]) > 4
    assert regions[2]["path"] == [[[0.5, 0.0], [1.0, 1.0], [0.0, 1.0], [0.5, 0.0]]]


def test_small_complex_freeforms_never_store_an_outline(tmp_path, lib):
    import math
    star = [(int(500 + (500 if k % 2 else 200) * math.cos(k * math.pi / 10)),
             int(500 + (500 if k % 2 else 200) * math.sin(k * math.pi / 10))) for k in range(20)]
    def build(slide):
        for size in (300000, 4000000):  # ~0.1% of the slide, then ~20%
            ff = slide.shapes.build_freeform(*star[0], scale=size / 1000)
            ff.add_line_segments(star[1:], close=True)
            ff.convert_to_shape()
    small, big = _regions(_freeform_deck(tmp_path, build), lib)
    assert small["path"] is None
    assert big["path"] is not None


def test_lines_keep_direction_bends_and_arrowheads(tmp_path, lib):
    from lxml import etree
    from pptx.enum.shapes import MSO_CONNECTOR
    def build(slide):
        a = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, 3000000, 0, 0, 2000000)  # drawn right-to-left: flipH
        etree.SubElement(a.line._get_or_add_ln(), "{http://schemas.openxmlformats.org/drawingml/2006/main}tailEnd").set("type", "triangle")
        slide.shapes.add_connector(MSO_CONNECTOR.ELBOW, 0, 0, 3000000, 2000000)
    a, b = _regions(_freeform_deck(tmp_path, build), lib)
    assert a["geom"] == "line"
    assert a["path"] == [[[1.0, 0.0], [0.0, 1.0]]] and a["arrow"] == "end"
    assert b["geom"] == "bentConnector3" and b["path"] == [[[0.0, 0.0], [0.5, 0.0], [0.5, 1.0], [1.0, 1.0]]]
    assert b["arrow"] is None


def test_custom_dash_patterns_count_as_dashed(tmp_path, lib):
    from lxml import etree
    from pptx.enum.shapes import MSO_SHAPE
    def build(slide):
        s = slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, 100, 100)
        s.line.width = 12700
        cd = etree.SubElement(s.line._get_or_add_ln(), "{http://schemas.openxmlformats.org/drawingml/2006/main}custDash")
        ds = etree.SubElement(cd, "{http://schemas.openxmlformats.org/drawingml/2006/main}ds")
        ds.set("d", "400000"), ds.set("sp", "300000")
    assert _regions(_freeform_deck(tmp_path, build), lib)[0]["dashed"] is True


def test_off_slide_shapes_are_dropped_and_overhanging_boxes_clamped_into_the_schema_range(tmp_path, lib):
    from pptx.enum.shapes import MSO_SHAPE
    W, H = 12192000, 6858000
    def build(slide):
        add = lambda x, y, w, h: slide.shapes.add_shape(MSO_SHAPE.RECTANGLE, x, y, w, h)
        add(0, 0, W // 4, H // 4)                                  # 0 on the slide
        add(W // 4, -2 * H, W // 4, H)                             # 1 entirely above it
        add(W // 2, round(-1.23 * H), W // 4, round(1.5 * H))      # 2 hangs in from far above
        grp = slide.shapes.add_group_shape()                       # 3 entirely right of it, with children 4 and 5
        for k in range(2):
            grp.shapes.add_shape(MSO_SHAPE.OVAL, W + 100 + k * 1000, 0, 500, 500)
        add(0, H // 2, W, H // 4)                                  # 6 on the slide
    regions = _regions(_freeform_deck(tmp_path, build), lib)
    assert [r["i"] for r in regions] == [0, 2, 6]  # numbering stays the walk order, so older labels still line up
    assert regions[1]["box"] == {"x": 0.5, "y": -1.0, "w": 0.25, "h": 1.27}  # bottom edge kept at 0.27
    assert all(-1 <= r["box"][k] <= 2 for r in regions for k in "xywh")


def test_reextract_keeps_the_deck_id_and_its_labels(deck, lib):
    from pipeline.__main__ import main
    deck_id = extract.run(deck, lib, render=False)
    work = lib / "work" / deck_id
    (work / "labels").mkdir()
    (work / "labels" / "slide-01.json").write_text('{"kept": true}')
    slide = work / "slide-01.json"
    slide.write_text(slide.read_text().replace('"path"', '"old"'))
    main(["reextract", deck_id, str(deck), "--library", str(lib)])
    assert sorted(p.name for p in (lib / "work").iterdir()) == [deck_id]
    assert (work / "labels" / "slide-01.json").read_text() == '{"kept": true}'
    assert '"path"' in slide.read_text() and json.loads(slide.read_text())["deck_id"] == deck_id
    with pytest.raises(SystemExit):
        main(["reextract", "0" * 16, str(deck), "--library", str(lib)])  # only an existing deck can be re-extracted


def test_reextract_reports_labels_of_regions_that_are_gone_and_lists_newly_listed_ones(deck, lib, monkeypatch, capsys):
    from pipeline import label_prep
    from pipeline.__main__ import main
    from pipeline.tests.conftest import fixture_labels
    monkeypatch.setattr(label_prep, "MAX_REGIONS", 3)
    deck_id = extract.run(deck, lib, render=False)
    work = lib / "work" / deck_id
    (work / "labels").mkdir()
    slide = json.loads((work / "slide-02.json").read_text())  # as an older extraction saw it: a shape parked off-slide
    slide["regions"].append(dict(slide["regions"][0], i=99, parent=None, box={"x": 1.5, "y": 0, "w": 1, "h": 1}))
    (work / "slide-02.json").write_text(json.dumps(slide))
    labels = fixture_labels(slide)
    labels["regions"] = {str(r["i"]): labels["regions"][str(r["i"])] for r in label_prep.worksheet_regions(slide)}
    labels["regions"]["99"] = "decoration"
    labels["text_patterns"] = [t for t in labels["text_patterns"] if str(t["region"]) in labels["regions"]]
    (work / "labels" / "slide-02.json").write_text(json.dumps(labels))
    main(["reextract", deck_id, str(deck), "--library", str(lib)])
    out = capsys.readouterr().out
    new = json.loads((work / "slide-02.json").read_text())
    added = [str(r["i"]) for r in label_prep.worksheet_regions(new) if str(r["i"]) not in labels["regions"]]
    kept = json.loads((work / "labels" / "slide-02.json").read_text())
    assert "slide-02" in out and "99 (decoration)" in out and all(f"{i} (other)" in out for i in added) and added
    assert "99" not in kept["regions"] and {i: kept["regions"][i] for i in added} == dict.fromkeys(added, "other")
    assert {k: v for k, v in kept["regions"].items() if k not in added} == {k: v for k, v in labels["regions"].items()
                                                                            if k != "99"}
    label_prep.validate(kept, new)  # builds again
    assert "slide-01" not in out  # nothing to report: its labels are untouched (none were written)
