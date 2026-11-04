"""Stage 6: emit library/records.sql (D1 rows + FTS5) and copy wireframes to library/assets/ for the server to deploy.

Row n of `slides` is row n of vecs.bin/norms.bin. The file rebuilds the tables from scratch on every load, because
D1 cannot export databases with FTS5 tables (the local library build is the source of truth).
"""
import json
import shutil
from pathlib import Path

SCHEMA_SQL = """DROP TABLE IF EXISTS slides_fts;
DROP TABLE IF EXISTS slides;
DROP TABLE IF EXISTS meta;
CREATE TABLE slides (n INTEGER PRIMARY KEY, id TEXT NOT NULL UNIQUE, deck_id TEXT NOT NULL, archetype TEXT NOT NULL,
  industry TEXT NOT NULL, data_type TEXT NOT NULL, purpose TEXT NOT NULL, why_it_works TEXT NOT NULL,
  description TEXT NOT NULL, dna TEXT NOT NULL);
CREATE INDEX slides_filters ON slides (archetype, industry, data_type);
CREATE VIRTUAL TABLE slides_fts USING fts5(purpose, why_it_works, description, tokenize='porter');
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""


def _q(v):
    return "'" + str(v).replace("'", "''") + "'"


def run(library):
    lib = Path(library)
    records = [json.loads(p.read_text()) for p in sorted((lib / "records").glob("*.json"))]
    manifest = json.loads((lib / "manifest.json").read_text())
    if manifest["ids"] != [r["id"] for r in records]:
        raise SystemExit("library/records/ changed since the last embed: run embed again before package.")
    lines = [SCHEMA_SQL]
    for n, r in enumerate(records):
        cols = [r["id"], r["deck_id"], r["archetype"], r["industry"], r["data_type"], r["purpose"], r["why_it_works"],
                r["description"], json.dumps(r, separators=(",", ":"))]
        lines.append(f"INSERT INTO slides VALUES ({n}, {', '.join(map(_q, cols))});")
        lines.append(f"INSERT INTO slides_fts (rowid, purpose, why_it_works, description) VALUES "
                     f"({n}, {_q(r['purpose'])}, {_q(r['why_it_works'])}, {_q(r['description'])});")
    lines.append(f"INSERT INTO meta VALUES ('library_version', {_q(manifest['library_version'])});")
    (lib / "records.sql").write_text("\n".join(lines) + "\n")
    assets = lib / "assets" / "wireframes"
    shutil.rmtree(assets, ignore_errors=True)
    assets.mkdir(parents=True)
    for r in records:
        shutil.copyfile(lib / "wireframes" / f"{r['id']}.png", assets / f"{r['id']}.png")
