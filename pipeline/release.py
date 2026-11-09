"""python -m pipeline release: preflight, embed, package, deploy the Worker, load D1, then smoke-check the live server.

Stops at the first failure. Deploy runs before the D1 load: the import is atomic, so a failed load leaves D1 unchanged
and the new Worker serving the old data until a re-run or `wrangler rollback`.
"""
import contextlib
import json
import os
import signal
import socket
import ssl
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import certifi

from pipeline import embed, leak_check, package

REPO = Path(__file__).resolve().parents[1]
URL = "https://eightytwenty.socratic.workers.dev/mcp"
HEADERS = {"content-type": "application/json", "accept": "application/json, text/event-stream",
           "mcp-protocol-version": "2025-06-18", "user-agent": "eightytwenty-release"}
SCOPE = "eightytwenty can't be used for that."
SMOKE_TRIES, SMOKE_WAIT = 10, 10  # ~90 s while edges still serve the old version
READY_TRIES = 60  # one a second


def _run(cmd, cwd, fail=None):
    if subprocess.run(cmd, cwd=cwd).returncode:
        raise SystemExit(fail or f"Failed: {' '.join(cmd)}")


def preflight(lib):
    server = REPO / "server"
    _run([sys.executable, "-m", "pytest", "-q", "pipeline/tests"], REPO)
    _run(["npx", "vitest", "run"], server)
    _run(["npx", "tsc", "--noEmit", "-p", "."], server)
    # --json: plain `whoami` exits 0 even when logged out
    _run(["npx", "wrangler", "whoami", "--json"], server, "wrangler is not logged in. Log in again: cd server && npx wrangler login")
    blocking, withheld, built = [], 0, {b.parent.name for b in (lib / "work").glob("*/build")}
    for f in sorted((lib / "records").glob("*.json")) + sorted((lib / "flows").glob("*.json")):  # leak-check can't reach these
        deck = f.stem[:-3] if f.parent.name == "records" else f.stem
        if deck not in built:
            what = f.stem if f.parent.name == "records" else f"{deck} flow"
            blocking.append(f"{what}: published, but {deck} has no build folder (run leak-check on it before retiring it)")
    for build in sorted((lib / "work").glob("*/build")):
        deck = build.parent.name
        for rid, r in leak_check.run(deck, lib).items():
            # excluded slides, flows withheld by the share rule and items the judge identified are designed
            # outcomes, not unfinished work: none of them is ever published
            if r["auto"] == "fail" or r["judge"] == "pending":
                why = r["problems"][0] if r["problems"] else f"judge {r['judge']}"
                blocking.append(f"{deck} flow: {why}" if rid == "flow" else f"{rid}: {why}")
            withheld += r["auto"] == "pass" and r["judge"] == "fail"
    if withheld:
        print(f"{withheld} withheld by the judge (identified; never published)")
    if blocking:
        print("\n".join(blocking))
        raise SystemExit(f"Release refused: {len(blocking)} item(s) failing the leak check or waiting for review.")


def _embed(lib):
    try:
        socket.create_connection(("127.0.0.1", embed.PORT), timeout=1).close()
    except OSError:
        pass
    else:
        raise SystemExit(f"Port {embed.PORT} is already in use; find the process with: lsof -i :{embed.PORT}")
    proc = subprocess.Popen(["npx", "wrangler", "dev", "--config", "../pipeline/embed_worker/wrangler.jsonc"],
                            cwd=REPO / "server", start_new_session=True, stdin=subprocess.DEVNULL)
    try:
        ready = urllib.request.Request(f"http://127.0.0.1:{embed.PORT}", json.dumps({"text": ["ready"]}).encode(),
                                       {"Content-Type": "application/json"})
        for _ in range(READY_TRIES):
            if proc.poll() is not None:  # e.g. an expired wrangler login: say so now, not after the timeout
                raise SystemExit("The embed Worker exited before it was ready; its output is above.")
            try:
                with urllib.request.urlopen(ready, timeout=5):
                    break
            except OSError:
                time.sleep(1)
        else:
            raise SystemExit(f"The embed Worker did not answer on port {embed.PORT} within {READY_TRIES} s.")
        embed.run(lib)
    finally:
        with contextlib.suppress(ProcessLookupError):  # already gone: nothing to stop, keep the real error
            os.killpg(proc.pid, signal.SIGTERM)
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait()


def _rpc(method, params):
    body = json.dumps({"jsonrpc": "2.0", "id": 1, "method": method, "params": params}).encode()
    ctx = ssl.create_default_context(cafile=certifi.where())
    with urllib.request.urlopen(urllib.request.Request(URL, body, HEADERS), timeout=30, context=ctx) as r:
        text = r.read().decode()
    data = [line[5:] for line in text.splitlines() if line.startswith("data:")]
    reply = json.loads(data[-1] if data else text)
    if "error" in reply:
        raise ValueError(reply["error"].get("message", reply["error"]))
    return reply["result"]


def _tool(name, args):
    return _rpc("tools/call", {"name": name, "arguments": args})["content"][0]["text"]


def smoke(version):
    for attempt in range(SMOKE_TRIES):
        if attempt:
            print(f"Smoke check: {problem}; retrying in {SMOKE_WAIT} s")
            time.sleep(SMOKE_WAIT)
        try:
            init = _rpc("initialize", {"protocolVersion": HEADERS["mcp-protocol-version"], "capabilities": {},
                                       "clientInfo": {"name": "eightytwenty-release", "version": "1"}})
            found = _tool("find_references", {"purpose": "executive summary", "k": 1})
            playbook = _tool("get_playbook", {})
        except (OSError, ValueError, LookupError, TypeError) as e:
            problem = f"{type(e).__name__}: {e}"
            continue
        problem = ("initialize sent no instructions" if not init.get("instructions") else
                   f"find_references does not serve library_version {version}" if f"library_version {version}" not in found
                   else "get_playbook lacks the scope line" if SCOPE not in playbook else None)
        if not problem:
            return
    raise SystemExit(f"Smoke check of {URL} failed for {SMOKE_WAIT * (SMOKE_TRIES - 1)} s: {problem}")


def run(library, dry_run=False):
    sys.stdout.reconfigure(line_buffering=True)  # our lines and wrangler's, in the order they happen
    lib, server = Path(library).resolve(), REPO / "server"
    git = lambda *a: subprocess.run(["git", *a], cwd=REPO, capture_output=True, text=True).stdout.strip()
    if not dry_run and git("status", "--porcelain"):  # what goes live must be a commit someone can read
        raise SystemExit("Release refused: uncommitted changes in the repo. Commit them first (git status shows them).")
    preflight(lib)
    records, flows = (len(list((lib / d).glob("*.json"))) for d in ("records", "flows"))
    if dry_run:
        print(f"Would publish {records} records and {flows} flows.")
        return
    _embed(lib)
    package.run(lib)
    deploy = subprocess.run(["npx", "wrangler", "deploy"], cwd=server, capture_output=True, text=True)
    print(deploy.stdout + deploy.stderr, end="")
    if deploy.returncode:
        raise SystemExit("wrangler deploy failed; D1 was not touched.")
    _run(["npx", "wrangler", "d1", "execute", "eightytwenty-db", "--remote", "--file", str(lib / "records.sql"), "-y"],
         server, "D1 is unchanged; the new Worker is live with the old data. Re-run release, or roll back the Worker: "
                 "cd server && npx wrangler rollback")
    version = json.loads((lib / "manifest.json").read_text())["library_version"]
    smoke(version)
    sha = git("rev-parse", "--short", "HEAD")
    deployed = next((line.strip() for line in deploy.stdout.splitlines() if "Version ID" in line), "")
    print(f"Released {records} records, {flows} flows, library_version {version}, git {sha}. {deployed}")
