import json

import pytest

from pipeline import build, extract, label_prep, leak_check
from pipeline.tests.conftest import CLIENT, EXCLUDED, fixture_labels


def _pipeline(deck, lib, edit=lambda n, labels: None):
    deck_id = extract.run(deck, lib, render=False)
    work = label_prep.run(deck_id, lib)
    for f in sorted(work.glob("slide-??.json")):
        labels = fixture_labels(json.loads(f.read_text()))
        edit(int(f.stem[-2:]), labels)
        (work / "labels" / f.name).write_text(json.dumps(labels))
    return deck_id, build.run(deck_id, lib)


def _judge(lib, deck_id, rid, identified):
    v = lib / "judge" / deck_id / "verdicts"
    v.mkdir(parents=True, exist_ok=True)
    (v / f"{rid}.json").write_text(json.dumps({"identified": identified, "guess": "none"}))


def test_clean_records_wait_for_judge_then_promote(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    report = leak_check.run(deck_id, lib)
    assert {r["auto"] for r in report.values()} == {"pass"} and {r["judge"] for r in report.values()} == {"pending"}
    assert not (lib / "records").exists() or not list((lib / "records").iterdir())
    judge = lib / "judge" / deck_id
    assert (judge / "JUDGE.txt").exists() and all((judge / f"{i}.json").exists() and (judge / f"{i}.png").exists() for i in ids)
    for rid in ids:
        _judge(lib, deck_id, rid, False)
    report = leak_check.run(deck_id, lib)
    assert {r["judge"] for r in report.values()} == {"pass"}
    assert sorted(p.name for p in (lib / "records").iterdir()) == sorted(f"{i}.json" for i in ids)
    assert sorted(p.name for p in (lib / "wireframes").iterdir()) == sorted(f"{i}.png" for i in ids)
    for sub in ("records", "wireframes", "judge"):
        for p in (lib / sub).rglob("*"):
            if p.is_file():
                data = p.read_bytes().lower()
                assert CLIENT.lower().encode() not in data, p
                assert not any(m.lower().encode() in data for m in EXCLUDED.values()), p


@pytest.mark.parametrize("field, value, problem", [
    ("why_it_works", f"Feels like the {CLIENT} brand book: bold band, one promise", "name"),
    ("why_it_works", "Borrowed from the Toronto subway map that Sarah Lee designed", "name"),
    ("purpose", "Show 3 reasons members stay longer", "digit"),
    ("purpose", "Show the ranking in a 3 column grid", "digit"),
    ("pattern", "points expire too fast then the fix", "shared words"),
])
def test_leaks_in_free_text_fail_closed_even_with_judge_pass(deck, lib, field, value, problem):
    def edit(n, labels):
        if n == 2:
            if field == "pattern":
                labels["text_patterns"][0]["pattern"] = value
            else:
                labels[field] = value
    deck_id, ids = _pipeline(deck, lib, edit)
    for rid in ids:
        _judge(lib, deck_id, rid, False)
    report = leak_check.run(deck_id, lib)
    bad = report[ids[1]]
    assert bad["auto"] == "fail" and any(problem in p for p in bad["problems"]), bad
    assert report[ids[0]]["auto"] == "pass"
    assert not (lib / "records" / f"{ids[1]}.json").exists()
    assert not (lib / "wireframes" / f"{ids[1]}.png").exists()
    assert not (lib / "judge" / deck_id / f"{ids[1]}.json").exists()


def test_design_vocabulary_is_not_a_name():
    assert leak_check.problems_in("Gantt bars and a SWOT grid with KPI tiles and Harvey balls", "", set()) == []


def test_names_from_the_slide_text_are_blocked_even_if_ner_misses_them():
    source = "Zorblax Foods grew loyalty in Ontario"
    tokens = leak_check.source_names(source)
    assert {"zorblax", "ontario"} <= tokens
    assert leak_check.problems_in("A zorblax style promise", source, tokens)


def test_numeric_dna_fields_are_exempt(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    report = leak_check.run(deck_id, lib)
    assert all(r["problems"] == [] for r in report.values())


def test_judge_identification_blocks_and_unpromotes(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    for rid in ids:
        _judge(lib, deck_id, rid, False)
    leak_check.run(deck_id, lib)
    assert (lib / "records" / f"{ids[0]}.json").exists()
    _judge(lib, deck_id, ids[0], True)
    report = leak_check.run(deck_id, lib)
    assert report[ids[0]]["judge"] == "fail"
    assert not (lib / "records" / f"{ids[0]}.json").exists()
    assert not (lib / "wireframes" / f"{ids[0]}.png").exists()


def test_malformed_verdict_counts_as_fail(deck, lib):
    deck_id, ids = _pipeline(deck, lib)
    leak_check.run(deck_id, lib)
    v = lib / "judge" / deck_id / "verdicts"
    v.mkdir(exist_ok=True)
    (v / f"{ids[0]}.json").write_text('{"identified": "no"}')
    assert leak_check.run(deck_id, lib)[ids[0]]["judge"] == "fail"
