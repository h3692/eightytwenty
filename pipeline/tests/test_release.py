"""release: every subprocess, socket and HTTP call is faked; nothing reaches Cloudflare or the live server."""
import json
import signal
import ssl
import subprocess
import sys
import urllib.error
from pathlib import Path

import pytest

from pipeline import release
from pipeline.__main__ import main

VERSION = "bge-m3/desc-v1/abc123"
DEPLOY_OUT = "Uploaded eightytwenty (3.1 sec)\nDeployed eightytwenty triggers\nCurrent Version ID: 1234-abcd\n"
CLEAN = {"deck-a-01": {"auto": "pass", "problems": [], "judge": "pass", "published": True},
         "deck-a-03": {"auto": "excluded", "problems": ["blank"], "judge": "excluded", "published": False,
                       "excluded": "blank"},
         "flow": {"auto": "pass", "problems": ["withheld: 1 of 3 slides published, a flow needs 60%"], "judge": "pass",
                  "published": False}}


def _library(lib):
    for deck in ("deck-a", "deck-b"):
        (lib / "work" / deck / "build").mkdir(parents=True)
    (lib / "work" / "deck-c").mkdir()  # extracted, never built: not leak-checked
    (lib / "records").mkdir()
    (lib / "flows").mkdir()
    for rid in ("deck-a-01", "deck-a-02", "deck-b-01"):
        (lib / "records" / f"{rid}.json").write_text("{}")
    (lib / "flows" / "deck-a.json").write_text("{}")
    (lib / "manifest.json").write_text(json.dumps({"library_version": VERSION}))
    return lib


class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body.encode()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def close(self):
        pass


class _Proc:
    pid = 4242

    def __init__(self, fake):
        self.fake = fake

    def poll(self):
        return 1 if self.fake.exited else None

    def wait(self, timeout=None):
        if self.fake.stubborn and timeout:
            raise subprocess.TimeoutExpired("wrangler dev", timeout)


class _Fake:
    def __init__(self, lib):
        self.lib, self.steps, self.sleeps, self.libraries, self.requests = lib, [], [], [], []
        self.fail, self.reports, self.live = set(), {}, [VERSION]
        self.port_open, self.ready, self.stubborn, self.embed_error, self.porcelain = False, True, False, None, ""
        self.exited, self.rpc_error = False, None

    def run(self, cmd, cwd=None, **kw):
        line = " ".join(map(str, cmd))
        self.steps.append(line)
        self.cwds = getattr(self, "cwds", {}) | {line: Path(cwd)}
        out = {"git rev-parse --short HEAD": "abc1234\n", "git status --porcelain": self.porcelain,
               "npx wrangler deploy": DEPLOY_OUT}.get(line, "")
        return subprocess.CompletedProcess(cmd, int(any(f in line for f in self.fail)), out, "")

    def popen(self, cmd, cwd=None, **kw):
        self.steps.append(" ".join(cmd))
        self.popen_kw = dict(kw, cwd=Path(cwd))
        return _Proc(self)

    def killpg(self, pid, sig):
        if self.exited:
            raise ProcessLookupError(pid)
        self.steps.append(f"killpg {pid} {signal.Signals(sig).name}")

    def connect(self, addr, timeout=None):
        if not self.port_open:
            raise ConnectionRefusedError(61, "Connection refused")
        self.steps.append(f"connect {addr}")
        return _Resp("")

    def urlopen(self, req, timeout=None, context=None):
        if req.full_url.startswith("http://127.0.0.1:8799"):
            assert json.loads(req.data) == {"text": ["ready"]}
            if not self.ready:
                raise urllib.error.URLError("Connection refused")
            self.steps.append("ready")
            return _Resp("{}")
        assert req.full_url == "https://eightytwenty.socratic.workers.dev/mcp" and isinstance(context, ssl.SSLContext)
        self.requests.append(req)
        msg = json.loads(req.data)
        name = msg["params"].get("name", msg["method"])
        self.steps.append(f"rpc {name}")
        if name == "initialize":
            result = {"serverInfo": {"name": "eightytwenty"}, "instructions": "Scope: slide design references."}
        elif name == "find_references" and self.rpc_error:
            err = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32000, "message": self.rpc_error}}
            return _Resp(f"event: message\ndata: {json.dumps(err)}\n\n")
        elif name == "find_references":
            version = self.live.pop(0) if len(self.live) > 1 else self.live[0]
            result = {"content": [{"type": "text", "text": f"library_version {version}\n\n1. deck-a-01"}]}
        else:
            result = {"content": [{"type": "text", "text": "Otherwise: \"eightytwenty can't be used for that.\""}]}
        return _Resp(f"event: message\ndata: {json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': result})}\n\n")

    def leak_check(self, deck_id, library):
        self.steps.append(f"leak-check {deck_id}")
        self.libraries.append(Path(library))
        return self.reports.get(deck_id, CLEAN)

    def embed(self, library):
        self.steps.append("embed")
        if self.embed_error:
            raise SystemExit(self.embed_error)

    def package(self, library):
        self.steps.append("package")


@pytest.fixture
def fake(monkeypatch, lib):
    f = _Fake(_library(lib))
    for mod, name, fn in ((release.subprocess, "run", f.run), (release.subprocess, "Popen", f.popen),
                          (release.os, "killpg", f.killpg), (release.time, "sleep", f.sleeps.append),
                          (release.socket, "create_connection", f.connect),
                          (release.urllib.request, "urlopen", f.urlopen), (release.leak_check, "run", f.leak_check),
                          (release.embed, "run", f.embed), (release.package, "run", f.package)):
        monkeypatch.setattr(mod, name, fn)
    return f


def test_release_runs_every_step_in_order_deploying_before_loading_d1(fake, lib, capsys):
    release.run(lib)
    assert fake.steps == [
        "git status --porcelain", f"{sys.executable} -m pytest -q pipeline/tests", "npx vitest run",
        "npx tsc --noEmit -p .", "npx wrangler whoami --json", "leak-check deck-a", "leak-check deck-b",
        "npx wrangler dev --config ../pipeline/embed_worker/wrangler.jsonc", "ready", "embed", "killpg 4242 SIGTERM",
        "package", "npx wrangler deploy",
        f"npx wrangler d1 execute eightytwenty-db --remote --file {lib.resolve() / 'records.sql'} -y",
        "rpc initialize", "rpc find_references", "rpc get_playbook", "git rev-parse --short HEAD"]
    server = release.REPO / "server"
    assert fake.cwds[f"{sys.executable} -m pytest -q pipeline/tests"] == release.REPO
    assert all(cwd == server for line, cwd in fake.cwds.items() if line.startswith("npx"))
    assert fake.popen_kw == {"cwd": server, "start_new_session": True, "stdin": subprocess.DEVNULL}  # no tty hotkeys
    req = fake.requests[1]
    assert json.loads(req.data)["params"] == {"name": "find_references",
                                              "arguments": {"purpose": "executive summary", "k": 1}}
    assert (req.get_header("Content-type"), req.get_header("Accept"), req.get_header("Mcp-protocol-version"),
            req.get_header("User-agent")) == ("application/json", "application/json, text/event-stream", "2025-06-18",
                                              "eightytwenty-release")
    out = capsys.readouterr().out
    assert "Current Version ID: 1234-abcd" in out  # wrangler's own output is still shown
    summary = out.strip().splitlines()[-1]
    for part in ("3 records", "1 flows", VERSION, "git abc1234.", "Current Version ID: 1234-abcd"):
        assert part in summary


def test_refuses_uncommitted_changes_before_anything_else_but_a_dry_run_still_checks(fake, lib, capsys):
    fake.porcelain = " M server/src/app.ts\n"  # what is live must be a commit someone can read
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert "uncommitted" in str(e.value.code) and fake.steps == ["git status --porcelain"]
    fake.steps.clear()
    release.run(lib, dry_run=True)
    assert "leak-check deck-b" in fake.steps


def test_refuses_published_records_of_a_deck_that_is_no_longer_built(fake, lib, capsys):
    (lib / "records" / "deck-z-01.json").write_text("{}")  # its work folder is gone, so leak-check never re-checks it
    (lib / "flows" / "deck-z.json").write_text("{}")
    with pytest.raises(SystemExit):
        release.run(lib)
    out = capsys.readouterr().out
    assert "deck-z-01: published, but deck-z has no build folder" in out and "deck-z flow: published" in out


def test_refuses_while_items_fail_or_wait_for_review_naming_each(fake, lib, capsys):
    fake.reports = {
        "deck-a": dict(CLEAN, **{"deck-a-02": {"auto": "fail", "problems": ["digits in purpose", "stale mockup"],
                                               "judge": "pending", "published": False}}),
        "deck-b": {"deck-b-01": {"auto": "pass", "problems": [], "judge": "pending", "published": False},
                   "deck-b-02": {"auto": "pass", "problems": [], "judge": "fail", "published": False},
                   "flow": {"auto": "pass", "problems": [], "judge": "pending", "published": False}}}
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert e.value.code
    out = capsys.readouterr().out
    assert "deck-a-02: digits in purpose" in out and "stale mockup" not in out
    assert "deck-b-01: judge pending" in out and "deck-b-02: judge fail" in out and "deck-b flow: judge pending" in out
    assert "deck-a-01" not in out and "deck-a-03" not in out and "deck-a flow" not in out  # excluded and withheld are fine
    assert fake.steps[-1] == "leak-check deck-b"


def test_dry_run_reports_what_would_publish_and_never_embeds_or_deploys(fake, lib, capsys):
    release.run(lib, dry_run=True)
    assert fake.steps[-1] == "leak-check deck-b"
    assert not any("wrangler dev" in s or "deploy" in s or "d1" in s or s == "embed" for s in fake.steps)
    out = capsys.readouterr().out
    assert "3 records" in out and "1 flows" in out


def test_whoami_failure_says_how_to_log_in_again(fake, lib):
    fake.fail = {"whoami"}
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert "cd server && npx wrangler login" in str(e.value.code)
    assert not any(s.startswith("leak-check") for s in fake.steps)


def test_failing_tests_stop_the_release(fake, lib):
    fake.fail = {"vitest"}
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert e.value.code and fake.steps[-1] == "npx vitest run"


def test_refuses_when_the_embed_port_is_in_use(fake, lib):
    fake.port_open = True
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert "lsof -i :8799" in str(e.value.code)
    assert not any("wrangler dev" in s for s in fake.steps)


def test_kills_the_worker_process_group_when_embedding_fails(fake, lib):
    fake.embed_error = "Expected pooling 'cls', got 'mean'"
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert e.value.code == fake.embed_error
    assert fake.steps[-2:] == ["embed", "killpg 4242 SIGTERM"]


def test_kills_harder_when_the_worker_ignores_sigterm(fake, lib):
    fake.stubborn = True
    release.run(lib)
    i = fake.steps.index("embed")
    assert fake.steps[i + 1:i + 3] == ["killpg 4242 SIGTERM", "killpg 4242 SIGKILL"]


def test_gives_up_when_the_worker_never_answers_and_still_kills_it(fake, lib):
    fake.ready = False
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert "60" in str(e.value.code) and len(fake.sleeps) == 60
    assert "embed" not in fake.steps and fake.steps[-1] == "killpg 4242 SIGTERM"


def test_d1_failure_prints_the_rollback_hint(fake, lib):
    fake.fail = {"d1 execute"}
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert "D1 is unchanged" in str(e.value.code) and "cd server && npx wrangler rollback" in str(e.value.code)
    assert fake.steps[-2:] == ["npx wrangler deploy", fake.steps[-1]] and "d1 execute" in fake.steps[-1]


def test_deploy_failure_never_loads_d1(fake, lib):
    fake.fail = {"wrangler deploy"}
    with pytest.raises(SystemExit):
        release.run(lib)
    assert fake.steps[-1] == "npx wrangler deploy"


def test_smoke_check_retries_until_edges_serve_the_new_version(fake, lib, capsys):
    fake.live = ["bge-m3/desc-v1/old", "bge-m3/desc-v1/old", VERSION]
    release.run(lib)
    assert fake.sleeps == [10, 10]
    assert VERSION in capsys.readouterr().out.strip().splitlines()[-1]


def test_smoke_check_fails_after_90_s_of_a_version_mismatch(fake, lib):
    fake.live = ["bge-m3/desc-v1/old"]
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert sum(fake.sleeps) == 90 and VERSION in str(e.value.code)
    assert "git rev-parse --short HEAD" not in fake.steps


def test_works_from_another_folder_with_the_library_under_the_repo(fake, monkeypatch, tmp_path):
    assert release.REPO == Path(release.__file__).resolve().parents[1] and (release.REPO / "pyproject.toml").exists()
    repo = tmp_path / "repo"
    _library(repo / "library")
    (tmp_path / "elsewhere").mkdir()
    monkeypatch.setattr(release, "REPO", repo)
    monkeypatch.chdir(tmp_path / "elsewhere")
    main(["release", "--dry-run"])
    assert fake.libraries == [repo / "library"] * 2
    assert fake.cwds[f"{sys.executable} -m pytest -q pipeline/tests"] == repo
    assert fake.cwds["npx vitest run"] == repo / "server"


def test_a_worker_that_exits_early_fails_at_once_without_hiding_the_reason(fake, lib):
    fake.ready, fake.exited = False, True  # wrangler dev died, e.g. an expired login
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert "exited before it was ready" in str(e.value.code)
    assert len(fake.sleeps) <= 1 and not any(step.endswith("deploy") for step in fake.steps)


def test_smoke_check_reports_the_servers_own_error_message(fake, lib):
    fake.rpc_error = "D1 holds library_version old but the bundled vectors are new"
    with pytest.raises(SystemExit) as e:
        release.run(lib)
    assert fake.rpc_error in str(e.value.code) and "KeyError" not in str(e.value.code)
