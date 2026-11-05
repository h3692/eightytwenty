"""Stage 6: emit library/records.sql (D1 rows + FTS5) and copy wireframes to library/assets/ for the server to deploy.

Row n of `slides` is row n of vecs.bin/norms.bin; row n of `flows` is row n of flow_vecs.bin. The file rebuilds the tables from scratch on every load, because
D1 cannot export databases with FTS5 tables (the local library build is the source of truth). A slide's impact
(none, build, spotlight, shade_ribbon, repeat) comes from its step in a published deck flow, and its layout is the
grid-snapped v3 layout its mockup was drawn from (enums and numbers only); the record stays unchanged.
"""
import json
import shutil
from pathlib import Path

from pipeline import flow, layout

SCHEMA_SQL = """DROP TABLE IF EXISTS flows;
DROP TABLE IF EXISTS slides_fts;
DROP TABLE IF EXISTS slides;
DROP TABLE IF EXISTS meta;
CREATE TABLE slides (n INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, deck_id TEXT NOT NULL, archetype TEXT NOT NULL,
  industry TEXT NOT NULL, data_type TEXT NOT NULL, purpose TEXT NOT NULL, why_it_works TEXT NOT NULL,
  description TEXT NOT NULL, dna TEXT NOT NULL, impact TEXT NOT NULL, layout TEXT NOT NULL);
CREATE INDEX slides_filters ON slides (archetype, industry, data_type);
CREATE VIRTUAL TABLE slides_fts USING fts5(purpose, why_it_works, description, tokenize='porter');
CREATE TABLE flows (n INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, deck_id TEXT NOT NULL, arc TEXT NOT NULL,
  length_bucket TEXT NOT NULL, industry TEXT NOT NULL, record TEXT NOT NULL, description TEXT NOT NULL);
CREATE INDEX flows_filters ON flows (industry, length_bucket);
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
-- Cached results of the old library can never be served again (the key holds library_version): drop them on load.
CREATE TABLE IF NOT EXISTS search_cache (key TEXT PRIMARY KEY, results TEXT NOT NULL, library_version TEXT);
DELETE FROM search_cache;
"""


MAX_REGIONS = 40  # what get_reference serves (server/src/app.ts); busy slides reach ~1000 regions, over D1's row limit
MAX_STATEMENT = 100_000  # D1's maximum SQL statement length, in bytes


def _q(v):
    return "'" + str(v).replace("'", "''") + "'"


def run(library):
    lib = Path(library)
    records = [json.loads(p.read_text()) for p in sorted((lib / "records").glob("*.json"))]
    manifest = json.loads((lib / "manifest.json").read_text())
    flows = [json.loads(p.read_text()) for p in sorted((lib / "flows").glob("*.json"))]
    if manifest["ids"] != [r["id"] for r in records] or manifest.get("flows", {}).get("ids") != [f["id"] for f in flows]:
        raise SystemExit("library/records/ or library/flows/ changed since the last embed: run embed again before package.")
    impact = flow.impacts(flows)
    lines = [SCHEMA_SQL]
    for n, r in enumerate(records):
        r = dict(r, description=flow.described(r, impact.get(r["id"])))  # the same text embed.py embedded
        f = lib / "layouts" / r["deck_id"] / f"slide-{r['slide']:02d}.v3.json"
        try:
            lay = layout.validate(json.loads(f.read_text()))
        except (OSError, ValueError) as e:
            raise SystemExit(f"{r['id']}: no valid v3 layout at {f} ({e}): rewrite it and run mockup + leak-check.")
        if len(r.get("regions", [])) > MAX_REGIONS:  # the largest by area, ties keep order, as get_reference picks
            keep = {id(x) for x in sorted(r["regions"], key=lambda x: -x["box"]["w"] * x["box"]["h"])[:MAX_REGIONS]}
            r = dict(r, regions=[x for x in r["regions"] if id(x) in keep],
                     regions_shown=f"the {MAX_REGIONS} largest of {len(r['regions'])}, by area")
        cols = [r["id"], r["deck_id"], r["archetype"], r["industry"], r["data_type"], r["purpose"], r["why_it_works"],
                r["description"], json.dumps(r, separators=(",", ":")), impact.get(r["id"], "none"),
                json.dumps(lay, separators=(",", ":"))]
        lines.append(f"INSERT INTO slides VALUES ({n}, {', '.join(map(_q, cols))});")
        if len(lines[-1].encode()) > MAX_STATEMENT:
            raise SystemExit(f"{r['id']}: its row is over D1's {MAX_STATEMENT:,}-byte statement limit; shorten it.")
        lines.append(f"INSERT INTO slides_fts (rowid, purpose, why_it_works, description) VALUES "
                     f"({n}, {_q(r['purpose'])}, {_q(r['why_it_works'])}, {_q(r['description'])});")
    for n, f in enumerate(flows):
        cols = [f["id"], f["deck_id"], f["arc"], f["length_bucket"], f["industry"], json.dumps(f, separators=(",", ":")),
                f["description"]]
        lines.append(f"INSERT INTO flows VALUES ({n}, {', '.join(map(_q, cols))});")
    lines.append(f"INSERT INTO meta VALUES ('library_version', {_q(manifest['library_version'])});")
    (lib / "records.sql").write_text("\n".join(lines) + "\n")
    assets = lib / "assets" / "wireframes"
    shutil.rmtree(assets, ignore_errors=True)
    assets.mkdir(parents=True)
    for r in records:
        shutil.copyfile(lib / "wireframes" / f"{r['id']}.png", assets / f"{r['id']}.png")
