"""Adversarial fixture deck: a client name planted in every channel the extractor must never read, plus body text."""
import io
import json

import pytest
from PIL import Image
from pptx import Presentation
from pptx.chart.data import CategoryChartData
from pptx.dml.color import RGBColor
from pptx.enum.chart import XL_CHART_TYPE
from pptx.enum.dml import MSO_LINE
from pptx.enum.shapes import MSO_CONNECTOR, MSO_SHAPE
from pptx.enum.text import PP_ALIGN
from pptx.opc.constants import RELATIONSHIP_TYPE as RT
from pptx.opc.package import Part
from pptx.opc.packuri import PackURI
from pptx.util import Emu, Inches, Pt

CLIENT = "Zorblax"  # appears in body text: may reach the local work dir, never a library output
# One marker per excluded channel: none of these may appear anywhere under library/.
EXCLUDED = {
    "notes": "ZorblaxNotes",
    "comments": "ZorblaxComment",
    "alt_text": "ZorblaxAltText",
    "hyperlink": "zorblaxlink",
    "doc_props": "ZorblaxProps",
    "hidden_slide": "ZorblaxHidden",
    "image_name": "ZorblaxImageName",
    "embedded_name": "ZorblaxEmbedded",
    "shape_name": "ZorblaxShapeName",
}

NAVY, ORANGE, GREY, WHITE = RGBColor(0x12, 0x2B, 0x4A), RGBColor(0xF2, 0x8C, 0x28), RGBColor(0xD9, 0xD9, 0xD9), RGBColor(0xFF, 0xFF, 0xFF)
COMMENTS_CT = "application/vnd.openxmlformats-officedocument.presentationml.comments+xml"


def _png(path):
    Image.new("RGB", (40, 40), (200, 30, 30)).save(path)
    return path


def build_fixture_deck(path, tmp_dir):
    prs = Presentation()
    prs.slide_width, prs.slide_height = Inches(13.333), Inches(7.5)
    blank = prs.slide_layouts[6]
    props = prs.core_properties
    props.title = props.author = props.subject = props.keywords = props.comments = EXCLUDED["doc_props"]
    props.category = props.last_modified_by = EXCLUDED["doc_props"]

    # Slide 1: title band + title text naming the client.
    s1 = prs.slides.add_slide(blank)
    band = s1.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(2))
    band.fill.solid(); band.fill.fore_color.rgb = NAVY; band.line.fill.background()
    band.name = EXCLUDED["shape_name"]
    band._element.nvSpPr.cNvPr.set("descr", EXCLUDED["alt_text"])
    band._element.nvSpPr.cNvPr.set("title", EXCLUDED["alt_text"])
    title = s1.shapes.add_textbox(Inches(0.5), Inches(0.4), Inches(12), Inches(1.2))
    r = title.text_frame.paragraphs[0].add_run()
    r.text = f"{CLIENT} Loyalty Rebuilt for Every Seat"
    r.font.size, r.font.bold, r.font.color.rgb = Pt(40), True, WHITE
    r.hyperlink.address = f"https://{EXCLUDED['hyperlink']}.example/"
    title.text_frame.paragraphs[0].alignment = PP_ALIGN.CENTER
    kpi = s1.shapes.add_textbox(Inches(5), Inches(3), Inches(3), Inches(1.5))
    k = kpi.text_frame.paragraphs[0].add_run()
    k.text, k.font.size, k.font.color.rgb = "42%", Pt(54), NAVY

    # Slide 2: body bullets, picture, chart, table, group, line, OLE embed, notes, comment.
    s2 = prs.slides.add_slide(blank)
    hdr = s2.shapes.add_textbox(Inches(0.5), Inches(0.3), Inches(12), Inches(0.8))
    hr = hdr.text_frame.paragraphs[0].add_run()
    hr.text = "Members who redeem twice stay three times longer"
    hr.font.size, hr.font.bold, hr.font.color.rgb = Pt(28), True, NAVY
    body = s2.shapes.add_textbox(Inches(0.5), Inches(1.4), Inches(4), Inches(3))
    tf = body.text_frame
    tf.text = f"{CLIENT} Foods grew loyalty in Ontario"
    for line in ("Points expire too fast for casual guests", "Rival programs reward the first visit"):
        p = tf.add_paragraph(); p.text = line; p.level = 1
    for p in tf.paragraphs:
        for run in p.runs:
            run.font.size = Pt(14)
    body.click_action.hyperlink.address = f"https://{EXCLUDED['hyperlink']}.example/click"
    pic = s2.shapes.add_picture(str(_png(tmp_dir / f"{EXCLUDED['image_name']}.png")), Inches(10.5), Inches(5.5), Inches(1), Inches(1))
    pic.name = EXCLUDED["shape_name"]
    data = CategoryChartData()
    data.categories = [CLIENT, "Rival", "Market"]
    data.add_series(f"{CLIENT} share", (42, 31, 27))
    gf = s2.shapes.add_chart(XL_CHART_TYPE.COLUMN_CLUSTERED, Inches(5), Inches(1.4), Inches(5), Inches(3.5), data)
    gf.chart.has_title = False
    table = s2.shapes.add_table(2, 3, Inches(0.5), Inches(5), Inches(4), Inches(1.2)).table
    table.cell(0, 0).text = CLIENT
    grp = s2.shapes.add_group_shape()
    for i in range(2):
        card = grp.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(10.5), Inches(1.4 + i * 1.8), Inches(2.3), Inches(1.5))
        card.fill.solid(); card.fill.fore_color.rgb = ORANGE if i == 0 else GREY
    card.line.dash_style = MSO_LINE.DASH
    line = s2.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(0.5), Inches(1.2), Inches(12.8), Inches(1.2))
    line.line.color.rgb = NAVY
    embed = tmp_dir / f"{EXCLUDED['embedded_name']}.xlsx"
    embed.write_bytes(f"PK fake workbook {EXCLUDED['embedded_name']}".encode())
    ole = s2.shapes.add_ole_object(str(embed), "Excel.Sheet.12", Inches(7), Inches(5.5), Inches(1), Inches(1))
    ole._element.xpath(".//p:oleObj")[0].set("name", EXCLUDED["embedded_name"])
    s2.notes_slide.notes_text_frame.text = f"{EXCLUDED['notes']} speaker notes"
    xml = (
        '<p:cmLst xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main">'
        f'<p:cm authorId="0" dt="2026-01-01T00:00:00" idx="1"><p:pos x="10" y="10"/><p:text>{EXCLUDED["comments"]}</p:text></p:cm></p:cmLst>'
    ).encode()
    s2.part.relate_to(Part(PackURI("/ppt/comments/comment1.xml"), COMMENTS_CT, s2.part.package, xml), RT.COMMENTS)

    # Slide 3: hidden, must be skipped entirely.
    s3 = prs.slides.add_slide(blank)
    s3.shapes.add_textbox(Inches(1), Inches(1), Inches(6), Inches(1)).text_frame.text = EXCLUDED["hidden_slide"]
    s3._element.set("show", "0")

    prs.save(path)
    return path


@pytest.fixture
def deck(tmp_path):
    src = tmp_path / "src"
    src.mkdir()
    return build_fixture_deck(src / f"{CLIENT} Final Round.pptx", src)


@pytest.fixture
def lib(tmp_path):
    return tmp_path / "library"


ROLE_BY_TYPE = {"text": "body", "picture": "image", "chart": "chart", "table": "table", "group": "group",
                "line": "divider", "shape": "card"}


def fixture_labels(slide):
    """Valid, leak-free labels for an extracted fixture slide (what a careful labeler would write)."""
    regions = {str(r["i"]): ROLE_BY_TYPE[r["type"]] for r in slide["regions"]}
    texts = [r["i"] for r in slide["regions"] if r["type"] == "text"]
    if slide["slide"] == 1:
        regions[str(texts[0])], regions[str(texts[1])] = "title", "big-number"
    return {
        "archetype": "title" if slide["slide"] == 1 else "situational-analysis",
        "purpose": "Open the story with one bold promise over a dark brand band",
        "argument_shape": "single-claim" if slide["slide"] == 1 else "evidence-stack",
        "insight_device": "big-number" if slide["slide"] == 1 else "highlight-contrast",
        "data_type": "kpi-numbers" if slide["slide"] == 1 else "quantitative-chart",
        "industry": "travel-hospitality",
        "why_it_works": "A single dominant statement on a saturated band makes the promise unmissable before any detail",
        "regions": regions,
        "text_patterns": [{"region": texts[0], "pattern": "outcome promise as a short noun phrase", "words": 6}],
        "when_to_use": "Opening a pitch when one promise must land before any evidence",
        "effect": "The audience grasps the central promise at a glance and expects proof next",
        "elements": [{"component": 0, "note": "A single headline block carries the promise with nothing competing"}],
    }


STYLE = "bold-pitch"


def fixture_style(work):
    """The deck style a careful labeler would pick for the fixture deck: work/<deck>/style.json."""
    (work / "style.json").write_text(json.dumps({"style": STYLE}))
