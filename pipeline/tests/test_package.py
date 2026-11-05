import json
import sqlite3

import pytest

from pipeline import package
from pipeline.__main__ import main
from pipeline.tests.conftest import CLIENT, EXCLUDED, fixture_labels
from pipeline.tests.test_embed import server  # noqa: F401  (fixture)
from pipeline.tests.test_leak_check import mockups

LAYOUT = {"version": 3, "components": [{"kind": "tracker", "n": 5, "active": 2},
                                       {"kind": "kpi_row", "box": [0, 0.25, 1, 0.5], "n": 3}]}


def _library(lib, purposes):
    (lib / "records").mkdir(parents=True)
    (lib / "wireframes").mkdir()
    ids = []
    for k, purpose in enumerate(purposes):
        rid = f"{k:016x}-01"
        dna = {"id": rid, "deck_id": f"{k:016x}", "slide": 1, "archetype": "options", "industry": "technology",
               "data_type": "table", "purpose": purpose, "why_it_works": "Rows make the trade-off obvious",
               "description": f"Options slide. Purpose: {purpose}."}
        (lib / "records" / f"{rid}.json").write_text(json.dumps(dna))
        (lib / "wireframes" / f"{rid}.png").write_bytes(b"\x89PNG fake")
        (lib / "layouts" / f"{k:016x}").mkdir(parents=True)
        (lib / "layouts" / f"{k:016x}" / "slide-01.v3.json").write_text(json.dumps(LAYOUT))
        ids.append(rid)
    (lib / "manifest.json").write_text(json.dumps({"library_version": "bge-m3/desc-v1/abc", "ids": ids,
                                                   "flows": {"count": 0, "ids": []}}))
    return ids


def _flows(lib, decks):
    """Published flow records (in the shape flow.build_flow writes), listed in the manifest in embed order."""
    (lib / "flows").mkdir()
    for k, d in enumerate(decks):
        rec = {"schema_version": "deck-flow/v1", "id": d, "deck_id": d, "arc": "pillars",
               "why_the_flow_works": "Each pillar gets its own beat", "steps": [], "dividers": [], "pacing": [],
               "length_bucket": ("short", "long")[k % 2], "industry": "technology", "description": f"Deck flow {k}"}
        (lib / "flows" / f"{d}.json").write_text(json.dumps(rec))
    man = json.loads((lib / "manifest.json").read_text())
    (lib / "manifest.json").write_text(json.dumps(dict(man, flows={"count": len(decks), "ids": sorted(decks)})))


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


def test_flows_table_rows_follow_flow_vector_order(lib):
    _library(lib, ["Compare the options side by side"])
    _flows(lib, ["00000000000000bb", "00000000000000aa"])
    package.run(lib)
    db = _load(lib)
    rows = db.execute("SELECT n, id, deck_id, arc, length_bucket, industry, record, description FROM flows "
                      "ORDER BY n").fetchall()
    assert [r[:6] for r in rows] == [(0, "00000000000000aa", "00000000000000aa", "pillars", "long", "technology"),
                                     (1, "00000000000000bb", "00000000000000bb", "pillars", "short", "technology")]
    assert json.loads(rows[0][6])["why_the_flow_works"] == "Each pillar gets its own beat" and rows[0][7] == "Deck flow 1"
    assert db.execute("SELECT id FROM flows WHERE industry = 'technology' AND length_bucket = 'short'").fetchall() == [
        ("00000000000000bb",)]
    db.executescript((lib / "records.sql").read_text())
    assert db.execute("SELECT count(*) FROM flows").fetchone() == (2,)


def test_refuses_flows_changed_since_embed(lib):
    _library(lib, ["Compare the options side by side"])
    _flows(lib, ["00000000000000aa"])
    (lib / "flows" / "00000000000000cc.json").write_text((lib / "flows" / "00000000000000aa.json").read_text())
    with pytest.raises(SystemExit, match="embed"):
        package.run(lib)


def test_slides_get_the_impact_of_their_step_in_a_published_flow(lib):
    ids = _library(lib, ["Compare the options side by side", "Pick a winner", "Recap the plan"])
    _flows(lib, ["00000000000000aa"])
    f = lib / "flows" / "00000000000000aa.json"
    steps = [{"id": ids[0], "archetype": "options", "section": "solution", "impact": "none", "builds_on": None},
             {"id": ids[1], "archetype": "options", "section": "solution", "impact": "spotlight", "builds_on": 1}]
    f.write_text(json.dumps(dict(json.loads(f.read_text()), steps=steps)))
    package.run(lib)
    db = _load(lib)
    assert db.execute("SELECT id, impact FROM slides ORDER BY n").fetchall() == [
        (ids[0], "none"), (ids[1], "spotlight"), (ids[2], "none")]  # a slide in no flow is not an impact slide
    assert "impact" not in json.loads(db.execute("SELECT dna FROM slides WHERE n = 1").fetchone()[0])  # records unchanged


def test_slides_carry_their_v3_layout(lib):
    ids = _library(lib, ["Compare the options side by side", "Pick a winner"])
    (lib / "layouts" / ids[1][:16] / "slide-01.v3.json").write_text(json.dumps({"version": 3, "components": [
        {"kind": "chart_area", "box": [0.01, 0.2, 0.98, 0.6], "chart_type": "bar"}]}))
    package.run(lib)
    rows = _load(lib).execute("SELECT layout FROM slides ORDER BY n").fetchall()
    assert json.loads(rows[0][0]) == LAYOUT
    # stored grid-snapped, exactly as the mockup was drawn
    assert json.loads(rows[1][0])["components"][0]["box"] == [0, 0.25, 1, 0.5]


@pytest.mark.parametrize("layout", [None, {"version": 3, "components": [{"kind": "text", "box": [0, 0, 1, 1],
                                                                          "lines": 2, "note": "Acme pitch"}]}])
def test_refuses_a_missing_or_invalid_layout(lib, layout):
    ids = _library(lib, ["Compare the options side by side"])
    f = lib / "layouts" / ids[0][:16] / "slide-01.v3.json"
    if layout is None:
        f.unlink()
    else:
        f.write_text(json.dumps(layout))
    with pytest.raises(SystemExit, match="layout"):
        package.run(lib)
    assert not (lib / "records.sql").exists()


def test_busy_records_keep_their_largest_regions_so_every_statement_fits_d1(lib):
    ids = _library(lib, ["Compare the options side by side"])
    f = lib / "records" / f"{ids[0]}.json"
    regions = [{"i": i, "type": "shape", "box": {"x": 0, "y": 0, "w": 0.001 * (i % 50 + 1), "h": 0.5}, "fill": "white",
                "role": "decoration"} for i in range(977)]
    f.write_text(json.dumps(dict(json.loads(f.read_text()), regions=regions)))
    package.run(lib)
    sql = (lib / "records.sql").read_text()
    assert max(len(s.encode()) for s in sql.split(";\n")) <= package.MAX_STATEMENT
    dna = json.loads(_load(lib).execute("SELECT dna FROM slides").fetchone()[0])
    # the same 40 get_reference serves: largest by area, ties in their original order
    top = set(sorted(range(977), key=lambda i: -(i % 50))[:40])  # 19 + 19 of the two largest sizes, then 47 and 97
    assert [r["i"] for r in dna["regions"]] == [i for i in range(977) if i in top]
    assert dna["regions_shown"] == "the 40 largest of 977, by area"


def test_refuses_a_row_over_d1s_statement_limit(lib):
    ids = _library(lib, ["Compare the options side by side"])
    f = lib / "records" / f"{ids[0]}.json"
    f.write_text(json.dumps(dict(json.loads(f.read_text()), description="Options slide. " * 8000)))
    with pytest.raises(SystemExit, match=ids[0]):
        package.run(lib)


def test_impact_slides_are_described_and_searchable_by_what_their_impact_frame_is_for(lib):
    from pipeline import flow
    ids = _library(lib, ["Compare the options side by side", "Pick a winner"])
    _flows(lib, ["00000000000000aa"])
    f = lib / "flows" / "00000000000000aa.json"
    f.write_text(json.dumps(dict(json.loads(f.read_text()), steps=[{"id": ids[1], "archetype": "options", "section": "solution",
                                                                    "impact": "spotlight", "builds_on": 1}])))
    package.run(lib)
    db = _load(lib)
    rows = db.execute("SELECT description FROM slides ORDER BY n").fetchall()
    assert rows[0][0] == "Options slide. Purpose: Compare the options side by side."
    assert rows[1][0] == f"Options slide. Purpose: Pick a winner. {flow.IMPACT_PURPOSE['spotlight']}"
    assert db.execute("SELECT s.id FROM slides_fts f JOIN slides s ON s.n = f.rowid WHERE slides_fts MATCH 'attention'").fetchall() == [(ids[1],)]


def test_loading_a_library_clears_the_search_cache(lib):
    _library(lib, ["Compare the options side by side"])
    db = sqlite3.connect(":memory:")
    db.execute("CREATE TABLE search_cache (key TEXT PRIMARY KEY, results TEXT NOT NULL, library_version TEXT)")
    db.execute("INSERT INTO search_cache VALUES ('k', '[]', 'bge-m3/desc-v1/old')")
    package.run(lib)
    db.executescript((lib / "records.sql").read_text())
    assert db.execute("SELECT count(*) FROM search_cache").fetchone() == (0,)
    _load(lib)  # also loads where the cache table does not exist yet
