import json
import math
import struct
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from pipeline import embed

WORKER = Path(embed.__file__).parent / "embed_worker"


def _vec(text, dims=1024):
    seed = sum(map(ord, text))
    return [math.sin(seed + d) * (1 + d % 7) for d in range(dims)]


class _FakeWorkersAI(BaseHTTPRequestHandler):
    """Stands in for the local embed Worker (no network in unit tests); same request/response contract."""
    dims, pooling, calls = 1024, "cls", []

    def do_POST(self):
        texts = json.loads(self.rfile.read(int(self.headers["Content-Length"])))["text"]
        type(self).calls.append(len(texts))
        body = json.dumps({"model": "@cf/baai/bge-m3", "pooling": self.pooling, "shape": [len(texts), self.dims],
                           "data": [_vec(t, self.dims) for t in texts]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def server():
    _FakeWorkersAI.dims, _FakeWorkersAI.pooling, _FakeWorkersAI.calls = 1024, "cls", []
    httpd = HTTPServer(("127.0.0.1", 0), _FakeWorkersAI)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_port}"
    httpd.shutdown()


def _records(lib, n):
    (lib / "records").mkdir(parents=True)
    ids = [f"{k:016x}-01" for k in range(n)]
    for i in ids:
        (lib / "records" / f"{i}.json").write_text(json.dumps({"id": i, "description": f"Slide about {i}"}))
    return ids


def test_writes_int8_vectors_norms_and_manifest_in_spike_layout(lib, server):
    ids = _records(lib, 3)
    embed.run(lib, server)
    vecs, norms = (lib / "vecs.bin").read_bytes(), (lib / "norms.bin").read_bytes()
    assert len(vecs) == 3 * 1024 and len(norms) == 3 * 4
    for row, rid in enumerate(sorted(ids)):
        v = _vec(f"Slide about {rid}")
        m = max(map(abs, v))
        q = [round(x * 127 / m) for x in v]
        assert list(struct.unpack("1024b", vecs[row * 1024:(row + 1) * 1024])) == q
        assert struct.unpack("<f", norms[row * 4:row * 4 + 4])[0] == pytest.approx(math.sqrt(sum(x * x for x in q)), rel=1e-6)
    man = json.loads((lib / "manifest.json").read_text())
    assert man["model"] == "@cf/baai/bge-m3" and man["pooling"] == "cls" and man["dims"] == 1024
    assert man["ids"] == sorted(ids) and man["count"] == 3
    assert man["description_version"] == "desc-v1" and man["schema_version"] == "design-dna/v1"
    assert man["library_version"].startswith("bge-m3/desc-v1/")


def test_library_version_is_deterministic_per_build(lib, server):
    _records(lib, 2)
    embed.run(lib, server)
    first = json.loads((lib / "manifest.json").read_text())["library_version"]
    embed.run(lib, server)
    assert json.loads((lib / "manifest.json").read_text())["library_version"] == first


def test_batches_requests(lib, server):
    _records(lib, embed.BATCH + 3)
    embed.run(lib, server)
    assert _FakeWorkersAI.calls == [embed.BATCH, 3]


@pytest.mark.parametrize("attr, value", [("dims", 768), ("pooling", "mean")])
def test_refuses_unexpected_model_output(lib, server, attr, value):
    _records(lib, 1)
    setattr(_FakeWorkersAI, attr, value)
    with pytest.raises(SystemExit, match=attr if attr == "pooling" else "1024"):
        embed.run(lib, server)
    assert not (lib / "vecs.bin").exists()


def test_unreachable_worker_explains_how_to_start_it(lib):
    _records(lib, 1)
    with pytest.raises(SystemExit, match="wrangler dev"):
        embed.run(lib, "http://127.0.0.1:9")


def test_local_worker_uses_the_logged_in_account_and_stays_local():
    cfg = (WORKER / "wrangler.jsonc").read_text()
    js = (WORKER / "index.js").read_text()
    assert '"remote": true' in cfg and '"ip": "127.0.0.1"' in cfg and str(embed.PORT) in cfg
    assert "@cf/baai/bge-m3" in js and "localhost" in js and "127.0.0.1" in js
    assert "token" not in (cfg + js).lower()
