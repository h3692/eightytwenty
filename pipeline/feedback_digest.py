"""python -m pipeline feedback-digest: feedback corrections that recur become playbook PRs for a human to review.

Per feedback table: fetch the unused rows of the last 90 days, ask Claude to group them, keep the groups that pass
qualifies(), then append each one to its chapter's "Learned from feedback" section on its own branch and open a PR.
Raw feedback text never leaves D1 and this process: the PR carries counts, dates, row ids and the model-written chunk.
Secrets come from the environment only (ANTHROPIC_API_KEY, CLOUDFLARE_API_TOKEN, CLOUDFLARE_ACCOUNT_ID, FEEDBACK_DB_ID;
gh reads GH_TOKEN).
"""
import json
import os
import ssl
import subprocess
import tempfile
import unicodedata
import urllib.error
import urllib.request
from pathlib import Path

import certifi

REPO = Path(__file__).resolve().parents[1]
PLAYBOOK = REPO / "playbook"
TEMPLATE = (Path(__file__).parent / "templates" / "feedback.txt").read_text()
TABLES = {"consulting": "consulting_feedback", "stock_pitch": "stock_pitch_feedback"}  # deck type -> table
EXCLUDED = {"writing", "archetypes"}  # chapters the digest never edits
SECTION = "## Learned from feedback"
SUBSECTIONS = {"consulting": "### Case-competition and consulting decks", "stock_pitch": "### Finance pitch decks"}
MIN_ROWS, MAX_CHARS, WINDOW, LIMIT = 5, 600, "-90 days", 500
BANNED = ("http", "www.", "@", "<", "`", "](", "//", "&#", "&lt")  # checked after NFKC: no full-width look-alikes
MODEL, MAX_TOKENS = "claude-sonnet-5-5", 16000
VERDICTS = ("new", "covered", "vague")
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["clusters"], "properties": {"clusters": {
    "type": "array", "items": {"type": "object", "additionalProperties": False,
                               "required": ["row_ids", "target", "markdown", "verdict"], "properties": {
            "row_ids": {"type": "array", "items": {"type": "integer"}}, "target": {"type": "string"},
            "markdown": {"type": "string"}, "verdict": {"type": "string", "enum": list(VERDICTS)}}}}}}


def _env(name):
    if not os.environ.get(name):
        raise SystemExit(f"{name} is not set. This value must come from environment variables.")
    return os.environ[name]


def _post(url, body, headers):
    req = urllib.request.Request(url, json.dumps(body).encode(), {"content-type": "application/json",
                                                                  "user-agent": "eightytwenty-feedback-digest", **headers})
    try:
        with urllib.request.urlopen(req, timeout=600, context=ssl.create_default_context(cafile=certifi.where())) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"{url.split('/')[2]} answered HTTP {e.code}: {e.read().decode()[:500]}")


def query(sql, params):
    url = (f"https://api.cloudflare.com/client/v4/accounts/{_env('CLOUDFLARE_ACCOUNT_ID')}"
           f"/d1/database/{_env('FEEDBACK_DB_ID')}/query")
    reply = _post(url, {"sql": sql, "params": params}, {"authorization": f"Bearer {_env('CLOUDFLARE_API_TOKEN')}"})
    if not reply.get("success"):
        raise SystemExit(f"D1 query failed: {reply.get('errors')}")
    return reply["result"][0]["results"]


def fetch(table):
    if table not in TABLES.values():
        raise ValueError(f"not a feedback table: {table}")
    # redacted rows ('[removed]') were withdrawn by their sender: they never count toward a PR
    return query(f"SELECT id, created_at, slide_type, deck_style, slide_role, message, correction, reason FROM {table} "
                 "WHERE used_in_pr IS NULL AND created_at >= strftime('%Y-%m-%dT%H:%M:%SZ', 'now', ?) "
                 "AND '[removed]' NOT IN (slide_role, message, correction) ORDER BY id LIMIT ?", [WINDOW, LIMIT])


def _outline(stem, text):
    heads = "; ".join(line[3:] for line in text.splitlines() if line.startswith("## ") and line != SECTION)
    learned = text.partition(f"\n{SECTION}\n")[2].strip() or "nothing yet"
    return f"Chapter {stem}: {heads}\nLearned from feedback so far:\n{learned}"


def cluster(rows, deck_type, chapters):
    prompt = TEMPLATE.format(
        deck_label=SUBSECTIONS[deck_type].removeprefix("### ").lower(), max_chars=MAX_CHARS, min_rows=MIN_ROWS,
        chapters="\n\n".join(_outline(s, t) for s, t in chapters.items()),
        rows=json.dumps(rows, indent=1).replace("<", "\\u003c"))  # still valid JSON; a row can't close the data block
    reply = _post("https://api.anthropic.com/v1/messages",
                  {"model": MODEL, "max_tokens": MAX_TOKENS, "messages": [{"role": "user", "content": prompt}],
                   "output_config": {"format": {"type": "json_schema", "schema": SCHEMA}}},
                  {"x-api-key": _env("ANTHROPIC_API_KEY"), "anthropic-version": "2026-10-21"})
    if reply.get("stop_reason") != "end_turn":  # a refusal, a cut-off or an error body: no clusters
        return []
    try:
        clusters = json.loads(next(b["text"] for b in reply["content"] if b.get("type") == "text"))["clusters"]
    except (KeyError, StopIteration, TypeError, ValueError):
        return []
    if not isinstance(clusters, list):
        return []
    return [c for c in clusters if isinstance(c, dict) and isinstance(c.get("row_ids"), list)
            and all(type(i) is int for i in c["row_ids"]) and isinstance(c.get("target"), str)
            and isinstance(c.get("markdown"), str) and c.get("verdict") in VERDICTS]


def qualifies(c, rows_by_id, allowed):
    md = c["markdown"]
    plain = unicodedata.normalize("NFKC", md).lower()
    return (c["verdict"] == "new" and len(set(c["row_ids"]) & rows_by_id.keys()) >= MIN_ROWS
            and c["target"] in allowed and 0 < len(md.strip()) and len(md) <= MAX_CHARS
            and not any(b in plain for b in BANNED)
            and not any(line.lstrip().startswith("#") for line in md.splitlines()))


def append(path, deck_type, markdown):
    lines = path.read_text().rstrip("\n").split("\n")
    if SECTION not in lines:
        lines += ["", SECTION, "", SUBSECTIONS["consulting"], "", SUBSECTIONS["stock_pitch"]]
    if SUBSECTIONS[deck_type] not in lines[lines.index(SECTION):]:
        lines += ["", SUBSECTIONS[deck_type]]
    start = lines.index(SUBSECTIONS[deck_type], lines.index(SECTION))
    end = next((i for i in range(start + 1, len(lines)) if lines[i].startswith("#")), len(lines))
    while lines[end - 1] == "":
        end -= 1
    bullet = ["- " + " ".join(markdown.split())]  # one bullet line, whatever line breaks the model sent
    lines[end:end] = [""] + bullet if end == start + 1 else bullet
    path.write_text("\n".join(lines) + "\n")


def _run(*cmd):
    r = subprocess.run(list(cmd), cwd=REPO, capture_output=True, text=True)
    if r.returncode:
        raise SystemExit(f"Failed: {' '.join(map(str, cmd))}\n{r.stderr}")
    return r.stdout.strip()


def open_pr(c, deck_type, table):
    """c: a qualifying cluster whose row_ids are fetched, unused rows, plus "first" and "last" (their dates).

    Rows are marked only once a PR exists: a branch an earlier run pushed gets its PR opened now if it has none.
    """
    ids = sorted(c["row_ids"])
    branch = f"feedback/{deck_type}-{ids[0]}"  # from data only: the deck type and an integer id
    path, sub = PLAYBOOK / f"{c['target']}.md", SUBSECTIONS[deck_type]
    title = f"Learned from feedback: {c['target']} ({deck_type})"
    base = _run("git", "rev-parse", "--abbrev-ref", "HEAD")
    if _run("git", "ls-remote", "--heads", "origin", branch):  # pushed by an earlier run
        has_pr = json.loads(_run("gh", "pr", "list", "--head", branch, "--state", "all", "--json", "number"))
    else:
        has_pr, original = False, path.read_text()
        append(path, deck_type, c["markdown"])
        if subprocess.run(["npx", "vitest", "run", "test/app.test.ts", "-t", "get_playbook"], cwd=REPO / "server").returncode:
            path.write_text(original)
            print(f"{branch}: the chunk breaks the playbook tests; skipped, {path.name} restored")
            return None
        _run("git", "switch", "-c", branch)
        _run("git", "commit", "-m", title, "--", str(path))
        _run("git", "push", "origin", branch)
        _run("git", "switch", base)
    if not has_pr:
        body = "\n".join([
            f"Chapter: playbook/{path.name}", f"Deck type: {deck_type}",
            f"Feedback: {len(ids)} rows, first {c['first']}, last {c['last']}", f"Row ids: {', '.join(map(str, ids))}",
            "", f"Appended under {SECTION} > {sub.removeprefix('### ')}:", "", "- " + " ".join(c["markdown"].split()),
            "", "---", "The feedback text itself is never posted here. Read the rows before merging:", "",
            f"cd server && npx wrangler d1 execute eightytwenty-feedback --remote --command "
            f"\"SELECT * FROM {table} WHERE id IN ({', '.join(map(str, ids))})\""])
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "body.md").write_text(body + "\n")
            print(_run("gh", "pr", "create", "--base", base, "--head", branch, "--title", title,
                       "--body-file", Path(d) / "body.md"))
    # json_each: one bound param for any number of ids (D1 allows at most 100 per query)
    query(f"UPDATE {table} SET used_in_pr = ? WHERE id IN (SELECT value FROM json_each(?))", [branch, json.dumps(ids)])
    return branch


def run(dry_run=False):
    allowed = {p.stem for p in PLAYBOOK.glob("*.md")} - EXCLUDED
    chapters = {s: (PLAYBOOK / f"{s}.md").read_text() for s in sorted(allowed)}
    for deck_type, table in TABLES.items():
        rows = fetch(table)
        print(f"{table}: {len(rows)} unused rows")
        if len(rows) < MIN_ROWS:
            continue
        by_id = {r["id"]: r for r in rows}
        for c in cluster(rows, deck_type, chapters):
            if not qualifies(c, by_id, allowed):  # by_id shrinks as clusters use rows: no row lands in two PRs
                continue
            ids = sorted(set(c["row_ids"]) & by_id.keys())
            dates = sorted(by_id.pop(i)["created_at"][:10] for i in ids)
            c = c | {"row_ids": ids, "first": dates[0], "last": dates[-1]}
            if dry_run:
                print(f"Would open: {c['target']} ({deck_type}), rows {', '.join(map(str, ids))}: {c['markdown']}")
            elif branch := open_pr(c, deck_type, table):
                print(f"{branch}: PR open, rows {', '.join(map(str, ids))} marked")
