import json
import random

import pytest
from PIL import Image, ImageDraw

from pipeline import dedupe
from pipeline.__main__ import main

DECK = "ab" * 8
CARDS = {"version": 3, "components": [{"kind": "card_row", "box": [0, 0, 1, 0.5], "n": 3}]}
TABLE = {"version": 3, "components": [{"kind": "table", "box": [0, 0, 1, 1], "rows": 4, "cols": 3}]}
COPY = ["Three moves win the segment", "Move one", "Move two", "Move three"]


def _picture(seed, spotlight=None):
    """A slide-like picture: a title bar over three cards of seeded blocks; spotlight = the one card framed, the
    others greyed out."""
    rng = random.Random(seed)
    img = Image.new("RGB", (640, 360), "white")
    d = ImageDraw.Draw(img)
    d.rectangle((20, 20, 400, 50), fill=(20, 40, 80))
    for k in range(3):
        x = 20 + k * 205
        for _ in range(40):
            bx, by = x + rng.randrange(150), 100 + rng.randrange(190)
            d.rectangle((bx, by, bx + rng.randrange(10, 40), by + rng.randrange(8, 30)), fill=tuple(
                rng.randrange(256) for _ in range(3)))
        if spotlight is not None and k != spotlight:
            img.paste(Image.blend(img.crop((x, 100, x + 190, 320)), Image.new("RGB", (190, 220), "white"), 0.75),
                      (x, 100))
    if spotlight is not None:
        x = 20 + spotlight * 205
        d.rectangle((x - 8, 92, x + 198, 328), outline=(20, 120, 60), width=8)
    return img


def _slide(lib, n, layout=CARDS, archetype="solution-overview", png=None, text=COPY):
    nn = f"slide-{n:02d}"
    work, lay = lib / "work" / DECK, lib / "layouts" / DECK
    for p in (work / "labels", work / "text", lay):
        p.mkdir(parents=True, exist_ok=True)
    (lay / f"{nn}.v3.json").write_text(json.dumps(layout))
    (work / "labels" / f"{nn}.json").write_text(json.dumps({"archetype": archetype}))
    (work / "text" / f"{nn}.txt").write_text("\n".join(text))
    if png is not None:
        png.save(work / f"{nn}.png")


def _rid(n):
    return f"{DECK}-{n:02d}"


def test_blank_flag_or_an_other_slide_holding_one_placeholder_line_is_blank():
    one_line = {"version": 3, "components": [{"kind": "text", "box": [0.4, 0.4, 0.2, 0.1], "lines": 1}]}
    eight = {"version": 3, "components": [{"kind": "text", "box": [0, 0, 1, 1], "lines": 8}]}
    assert dedupe.blank({"archetype": "solution-overview"}, {"version": 3, "blank": True, "components": []})
    assert dedupe.blank({"archetype": "other"}, one_line)
    assert not dedupe.blank({"archetype": "solution-overview"}, one_line)
    assert not dedupe.blank({"archetype": "other"}, eight)  # a page of sources or links is a real slide
    assert not dedupe.blank({"archetype": "other"}, CARDS)
    assert not dedupe.blank(None, one_line)  # unlabelled: not enough to call it blank


def test_hash_tolerates_a_rerender_but_not_new_content(tmp_path):
    a, b, c = (tmp_path / f"{k}.png" for k in "abc")
    _picture(1).save(a)
    _picture(1).resize((1280, 720)).save(b)
    _picture(4).save(c)
    assert dedupe.distance(dedupe.dhash(a), dedupe.dhash(b)) <= dedupe.NEAR
    assert dedupe.distance(dedupe.dhash(a), dedupe.dhash(c)) > dedupe.LOOSE


def test_spotlight_sets_and_exact_copies_keep_the_fullest_slide(lib):
    _slide(lib, 1, png=_picture(1, spotlight=0))
    _slide(lib, 2, png=_picture(1))           # the neutral one: nothing faded, the most ink
    _slide(lib, 3, png=_picture(1, spotlight=2))
    _slide(lib, 4, png=_picture(2), text=["Another deck section"])
    _slide(lib, 5, png=_picture(2), text=["Another deck section"])  # exact copy: the later one is kept
    pics = [dedupe.dhash(lib / "work" / DECK / f"slide-0{n}.png") for n in (1, 2)]
    assert dedupe.NEAR < dedupe.distance(*pics) <= dedupe.LOOSE  # only the shared copy makes it a duplicate
    assert dedupe.excluded(DECK, lib) == {_rid(1): f"duplicate_of {_rid(2)}", _rid(3): f"duplicate_of {_rid(2)}",
                                          _rid(4): f"duplicate_of {_rid(5)}"}


def test_a_repeated_cover_keeps_its_first_copy(lib):
    _slide(lib, 1, archetype="title", png=_picture(1, spotlight=0))
    _slide(lib, 2, png=_picture(4), text=["Another deck section"])
    _slide(lib, 3, archetype="title", png=_picture(1))  # more ink and later: kept under the usual rule
    _slide(lib, 4, archetype="title", png=_picture(1))
    assert dedupe.excluded(DECK, lib) == {_rid(3): f"duplicate_of {_rid(1)}", _rid(4): f"duplicate_of {_rid(1)}"}


@pytest.mark.parametrize("change", ["other copy", "other layout", "no picture", "other picture", "bad layout"])
def test_when_unsure_both_are_kept(lib, change):
    _slide(lib, 1, png=_picture(1))
    second = {"png": _picture(1, spotlight=0)}
    if change == "other copy":
        second["text"] = ["Revised plan", "Move one", "Step two", "Step three"]
    elif change == "other layout":
        second["layout"] = TABLE
    elif change == "no picture":
        second["png"] = None
    elif change == "other picture":
        second["png"] = _picture(5)
    else:
        second["layout"] = {"version": 3, "components": [{"kind": "card_row", "n": 3}]}
    _slide(lib, 2, **second)
    assert dedupe.excluded(DECK, lib) == {}


def test_blank_slides_are_excluded_and_never_count_as_duplicates(lib):
    blank = {"version": 3, "blank": True, "components": []}
    _slide(lib, 1, layout=blank, png=_picture(1), text=[])
    _slide(lib, 2, layout=blank, png=_picture(1), text=[])
    _slide(lib, 3, png=_picture(1))
    assert dedupe.excluded(DECK, lib) == {_rid(1): "blank", _rid(2): "blank"}


def test_command_writes_the_dedupe_and_blank_reports(lib, capsys):
    _slide(lib, 1, layout={"version": 3, "blank": True, "components": []}, png=_picture(3), text=[])
    _slide(lib, 2, png=_picture(1))
    _slide(lib, 3, png=_picture(1, spotlight=1))
    main(["exclusions", "--library", str(lib)])
    dupes = (lib / "work" / "dedupe-report.txt").read_text().splitlines()
    blanks = (lib / "work" / "blank-report.txt").read_text().splitlines()
    assert dupes[1:] == [f"{DECK}\t{_rid(2)}\t{_rid(3)}\tsame copy, similar render"]
    assert blanks[1:] == [f"{DECK}\t{_rid(1)}\tblank flag"]
    assert "1 duplicate" in capsys.readouterr().out
