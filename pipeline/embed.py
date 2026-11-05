"""Stage 5: bge-m3 embeddings of every published description, through a local Worker on the user's wrangler login.

Writes library/vecs.bin (N x 1024 int8, row-major, x*127/max|x| per vector), library/norms.bin (N float32 LE norms of
the int8 rows) and library/manifest.json, in the layout the server's WASM brute-force kernel expects; the published
deck flows (library/flows/) get their own int8 set, library/flow_vecs.bin, under the same library_version.
"""
import hashlib
import json
import math
import struct
import urllib.error
import urllib.request
from pathlib import Path

from pipeline import build, flow

MODEL, POOLING, DIMS, PORT, BATCH = "@cf/baai/bge-m3", "cls", 1024, 8799, 20
START = "npx wrangler dev --config pipeline/embed_worker/wrangler.jsonc"


def _post(url, texts):
    req = urllib.request.Request(url, json.dumps({"text": texts}).encode(), {"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read())
    except urllib.error.URLError as e:
        raise SystemExit(f"Embed Worker not reachable at {url} ({e}). Start it in another terminal: {START}")


def _embed(url, texts):
    """int8 rows and their float32 norms for texts, BATCH per request."""
    vectors = []
    for k in range(0, len(texts), BATCH):
        out = _post(url, texts[k:k + BATCH])
        if out.get("pooling") != POOLING:
            raise SystemExit(f"Expected pooling {POOLING!r}, got {out.get('pooling')!r}")
        if any(len(v) != DIMS for v in out["data"]):
            raise SystemExit(f"Expected {DIMS}-d vectors, got shape {out.get('shape')}")
        vectors += out["data"]
    vecs, norms = bytearray(), bytearray()
    for v in vectors:
        m = max(map(abs, v)) or 1.0
        q = [round(x * 127 / m) for x in v]
        vecs += struct.pack(f"{DIMS}b", *q)
        norms += struct.pack("<f", math.sqrt(sum(x * x for x in q)))
    return vecs, norms


def run(library, url=f"http://127.0.0.1:{PORT}"):
    lib = Path(library)
    records = [json.loads(p.read_text()) for p in sorted((lib / "records").glob("*.json"))]
    if not records:
        raise SystemExit("No published records in library/records/ (run leak-check first).")
    flows = [json.loads(p.read_text()) for p in sorted((lib / "flows").glob("*.json"))]
    impact = flow.impacts(flows)
    vecs, norms = _embed(url, [flow.described(r, impact.get(r["id"])) for r in records])
    flow_vecs, _ = _embed(url, [f["description"] for f in flows])
    digest = hashlib.sha256(json.dumps([records, flows], sort_keys=True).encode() + bytes(vecs + flow_vecs)).hexdigest()[:12]
    (lib / "vecs.bin").write_bytes(vecs)
    (lib / "norms.bin").write_bytes(norms)
    (lib / "flow_vecs.bin").write_bytes(flow_vecs)
    (lib / "manifest.json").write_text(json.dumps({
        "library_version": f"bge-m3/{build.DESCRIPTION_VERSION}/{digest}", "model": MODEL, "pooling": POOLING,
        "dims": DIMS, "quantisation": "int8 x*127/max|x|, float32 LE norms of int8 rows",
        "description_version": build.DESCRIPTION_VERSION, "schema_version": "design-dna/v1",
        "count": len(records), "ids": [r["id"] for r in records],
        "flows": {"count": len(flows), "ids": [f["id"] for f in flows]}}, indent=1))
