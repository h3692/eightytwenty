import json
import sqlite3

import pytest

from pipeline import package
from pipeline.__main__ import main
from pipeline.tests.conftest import CLIENT, EXCLUDED, fixture_labels
from pipeline.tests.test_embed import server  # noqa: F401  (fixture)
from pipeline.tests.test_leak_check import mockups


def _library(lib, purposes):
    (lib / "records").mkdir(parents=True)
    (lib / "wireframes").mkdir()
    ids = []
    for k, purpose in enumerate(purposes):
        rid = f"{k:016x}-01"
        dna = {"id": rid, "deck_id": f"{k:016x}", "archetype": "options", "industry": "technology",
               "data_type": "table", "purpose": purpose, "why_it_works": "Rows make the trade-off obvious",
               "description": f"Options slide. Purpose: {purpose}."}
        (lib / "records" / f"{rid}.json").write_text(json.dumps(dna))
        (lib / "wireframes" / f"{rid}.png").write_bytes(b"\x89PNG fake")
        ids.append(rid)
    (lib / "manifest.json").write_text(json.dumps({"library_version": "bge-m3/desc-v1/abc", "ids": ids}))
    return ids


def _load(lib):
    db = sqlite3.connect(":memory:")
    db.executescript((lib / "records.sql").read_text())
    return db


def test_records_sql_loads_with_rows_filters_and_fts(lib):
    ids = _library(lib, ["Compare the options side by side", "Pick a winner with the team's criteria"])
    package.run(lib)
    db = _load(lib)
    rows = db.execute("SELECT n, id, archetype, industry, data_type, dna FROM slides ORDER BY n").fetchall()
    assert [(r[0], r[1]) for r in rows] == [(0, ids[0]), (1, ids[1])]
    assert json.loads(rows[1][5])["purpose"] == "Pick a winner with the team's criteria"
    hit = db.execute("SELECT s.id FROM slides_fts f JOIN slides s ON s.n = f.rowid WHERE slides_fts MATCH 'winner' "
                     "AND s.industry = 'technology'").fetchall()
    assert hit == [(ids[1],)]
    assert db.execute("SELECT value FROM meta WHERE key = 'library_version'").fetchone() == ("bge-m3/desc-v1/abc",)
    # Rebuild-safe: loading twice replaces rather than duplicates.
    db.executescript((lib / "records.sql").read_text())
    assert db.execute("SELECT count(*) FROM slides").fetchone() == (2,)


def test_no_explicit_transactions_for_d1(lib):
    _library(lib, ["Compare the options side by side"])
    package.run(lib)
    sql = (lib / "records.sql").read_text().upper()
    assert "BEGIN" not in sql and "COMMIT" not in sql


def test_copies_wireframes_for_binding_only_assets(lib):
    ids = _library(lib, ["Compare the options side by side"])
    (lib / "assets" / "wireframes").mkdir(parents=True)
    (lib / "assets" / "wireframes" / "stale-01.png").write_bytes(b"old")
    package.run(lib)
    assert sorted(p.name for p in (lib / "assets" / "wireframes").iterdir()) == [f"{ids[0]}.png"]


def test_refuses_stale_embeddings(lib):
    _library(lib, ["Compare the options side by side"])
    (lib / "manifest.json").write_text(json.dumps({"library_version": "x", "ids": ["other-01"]}))
    with pytest.raises(SystemExit, match="embed"):
        package.run(lib)


def test_cli_runs_the_whole_pipeline_and_nothing_identifying_reaches_outputs(deck, lib, server, capsys):  # noqa: F811
    main(["extract", str(deck), "--library", str(lib), "--skip-render"])
    deck_id = capsys.readouterr().out.strip().split()[-1]
    main(["label-prep", deck_id, "--library", str(lib)])
    work = lib / "work" / deck_id
    for f in sorted(work.glob("slide-??.json")):
        (work / "labels" / f.name).write_text(json.dumps(fixture_labels(json.loads(f.read_text()))))
    main(["build", deck_id, "--library", str(lib)])
    mockups(lib, deck_id)
    with pytest.raises(SystemExit) as pending:
        main(["leak-check", deck_id, "--library", str(lib)])
    assert pending.value.code == 1  # judge verdicts still missing: nothing promoted
    for rid in json.loads((work / "leak-report.json").read_text()):
        (lib / "judge" / deck_id / "verdicts" / f"{rid}.json").write_text('{"identified": false, "guess": "none"}')
    main(["leak-check", deck_id, "--library", str(lib)])
    main(["embed", "--library", str(lib), "--url", server])
    main(["package", "--library", str(lib)])
    outputs = [p for p in lib.rglob("*") if p.is_file() and "work" not in p.relative_to(lib).parts]
    assert {"records.sql", "manifest.json", "vecs.bin", "norms.bin"} <= {p.name for p in outputs}
    for p in outputs:
        data = p.read_bytes().lower()
        assert CLIENT.lower().encode() not in data, p
        assert not any(m.lower().encode() in data for m in EXCLUDED.values()), p
    assert _load(lib).execute("SELECT count(*) FROM slides").fetchone() == (2,)
