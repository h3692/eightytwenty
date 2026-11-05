import json
import re
from pathlib import Path

import pytest

from pipeline import build, extract, label_prep, layout
from pipeline.tests.conftest import fixture_labels

PLAYBOOK = Path(__file__).resolve().parents[2] / "playbook" / "archetypes.md"


@pytest.fixture
def work(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    label_prep.run(deck_id, lib)
    return lib / "work" / deck_id


def _slide(work, n):
    return json.loads((work / f"slide-{n:02d}.json").read_text())


def test_archetype_enum_matches_playbook_ids():
    ids = re.findall(r"^\| `([a-z-]+)` \|", PLAYBOOK.read_text(), re.M)
    assert len(ids) == 17
    assert label_prep.SCHEMA["properties"]["archetype"]["enum"] == ids


def test_industry_is_a_fixed_list_of_at_most_15():
    assert 2 <= len(label_prep.SCHEMA["properties"]["industry"]["enum"]) <= 15


LEAK_RULES = (  # verbatim: the labeling agent sees exactly these rules
    "Hard rules for every free-text field (purpose, why_it_works, pattern). A leak check rejects the record otherwise:",
    "  - Describe the design, never the content. No client, competition, team, school, year, person, company,\n"
    "    brand, product or place names, and no hint that identifies them.",
    '  - No digits at all (write "one big number", not "3x").',
    "  - Never copy three or more consecutive words from the slide's text.",
    "  - No other fields than the ones above.",
    '  - No brand identity. No specific colour names (red, blue, coral, teal, navy, gold ... or "-ish" forms): use\n'
    "    roles (primary, accent, brand-colour fill, dark, light, mid-grey, black, white, greyscale, tint, shade,\n"
    "    saturated, muted).",
    "  - No mascot, wordmark, lockup, logomark, monogram, emblem, crest, watermark, signature, sponsor, affiliation,\n"
    '    portrait, domain or URL, and no "brand art", "brand illustration", "brand motif" or "brand swoosh". Write\n'
    '    "headshot slots" for portraits; "logo" is fine as a placement ("logo top right").',
    "  - Never say what an illustration depicts (botanical, an animal, a character, a landmark, a skyline, a world\n"
    '    map): write "illustration", "photo", "icon", "image" or "map".',
    "  - No words from the slide and no fields other than the ones above: the mockup only ever shows fixed placeholder\n"
    '    copy ("Header here", "Text here", "XX%" ...).',
)


def _listed(text):
    """Region indices a worksheet lists, one JSON object per line."""
    return [json.loads(line)["i"] for line in text.splitlines() if line.startswith('{"i":')]


def test_writes_one_combined_worksheet_per_slide(work):
    prompts = sorted(work.glob("slide-*.prompt.txt"))
    assert [p.name for p in prompts] == ["slide-01.prompt.txt", "slide-02.prompt.txt"]
    text = prompts[1].read_text()
    lib, deck_id = work.parents[1], work.name
    for needed in (str(work.absolute() / "slide-02.png"), str(work.absolute() / "labels" / "slide-02.json"),
                   str(lib.absolute() / "layouts" / deck_id / "slide-02.v3.json"), "ONCE", "BOTH",
                   "labels.v1.json", "layout.v3.json", '"version": 3', "zoomed out", "12 x 8", "situational-analysis",
                   "why_it_works", "text_patterns", "claim + mechanism + number", "stacked_bar", *layout.KINDS,
                   *LEAK_RULES):
        assert needed in text, needed
    assert _listed(text) == [r["i"] for r in _slide(work, 2)["regions"]]
    assert '"path"' not in text  # outlines are heavy and useless to a labeler
    assert (work / "labels").is_dir() and (lib / "layouts" / deck_id).is_dir()


def _busy(slide, n=60):
    """The slide with n regions whose areas repeat every 25 indices (ties), alternating shape and text, apart (no cluster)."""
    text = next(r for r in slide["regions"] if r["type"] == "text")
    shape = next(r for r in slide["regions"] if r["type"] == "shape")
    return dict(slide, regions=[dict(text if i % 2 else shape, i=i, parent=None,
                                     box={"x": 0, "y": 0.016 * i, "w": 0.01 * (1 + i % 25), "h": 0.01}) for i in range(n)])


def _capped_labels(slide):
    labels = fixture_labels(slide)
    keep = {str(r["i"]) for r in label_prep.worksheet_regions(slide)}
    labels["regions"] = {k: v for k, v in labels["regions"].items() if k in keep}
    labels["text_patterns"][0]["region"] = 49  # a listed text region
    return labels


def test_worksheet_regions_are_the_40_largest_ties_by_index(work):
    slide = _busy(_slide(work, 2))
    picked = [r["i"] for r in label_prep.worksheet_regions(slide)]
    assert label_prep.MAX_REGIONS == 40 and len(picked) == 40 and picked == sorted(picked)
    assert set(picked) == set(sorted(range(60), key=lambda i: (-(1 + i % 25), i))[:40])
    assert 6 in picked and 31 not in picked and 56 not in picked  # the last tie goes to the lowest index
    small = _slide(work, 2)
    assert label_prep.worksheet_regions(small) == small["regions"]


@pytest.mark.parametrize("layouts_only", [False, True])
def test_worksheets_list_only_the_capped_regions(work, layouts_only):
    slide = _busy(_slide(work, 2))
    (work / "slide-02.json").write_text(json.dumps(slide))
    out = label_prep.run(work.name, work.parents[1], layouts_only=layouts_only)
    text = (out / "slide-02.prompt.txt").read_text()
    assert _listed(text) == [r["i"] for r in label_prep.worksheet_regions(slide)]
    assert "40 largest" in text and "of 60" in text


def test_labels_cover_exactly_the_listed_regions_or_every_region(work):
    slide = _busy(_slide(work, 2))
    labels = _capped_labels(slide)
    label_prep.validate(labels, slide)
    legacy = fixture_labels(slide)  # labelled before the cap: every region
    legacy["text_patterns"][0]["region"] = 49
    label_prep.validate(legacy, slide)
    for broken in ({**labels["regions"], "31": "body"}, {k: v for k, v in labels["regions"].items() if k != "6"}):
        with pytest.raises(ValueError, match="region"):
            label_prep.validate({**labels, "regions": broken}, slide)
    labels["text_patterns"][0]["region"] = 31  # a text region that is not listed
    with pytest.raises(ValueError, match="non-text region"):
        label_prep.validate(labels, slide)


def test_unlisted_regions_build_as_other(work):
    slide = _busy(_slide(work, 2))
    dna = build.merge(slide, _capped_labels(slide))
    build.check_schema(dna)
    listed = {r["i"] for r in label_prep.worksheet_regions(slide)}
    assert {r["role"] for r in dna["regions"] if r["i"] not in listed} == {"other"}
    assert "other" not in {r["role"] for r in dna["regions"] if r["i"] in listed}


def test_valid_labels_pass(work):
    label_prep.validate(fixture_labels(_slide(work, 2)), _slide(work, 2))


@pytest.mark.parametrize("mutate, message", [
    (lambda l: l.update(archetype="hero-slide"), "archetype"),
    (lambda l: l.update(industry="aerospace-defense-and-space"), "industry"),
    (lambda l: l.update(client="Somebody"), "client"),
    (lambda l: l["regions"].pop("0"), "region"),
    (lambda l: l["regions"].update({"99": "body"}), "region"),
    (lambda l: l["text_patterns"].append({"region": 99, "pattern": "short claim", "words": 3}), "non-text region"),
])
def test_invalid_labels_fail(work, mutate, message):
    labels = fixture_labels(_slide(work, 2))
    mutate(labels)
    with pytest.raises(ValueError, match=message):
        label_prep.validate(labels, _slide(work, 2))
