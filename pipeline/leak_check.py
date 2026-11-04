"""Stage 4: leak check. Fails closed: only records that pass every automated check AND a recorded judge verdict
are promoted to library/records/ + library/wireframes/; anything else is withheld (and removed if promoted before).

Free-text fields (purpose, why_it_works, description, text patterns) must not contain digits, share a 3-word
sequence with the slide's original text, or contain names (spaCy NER, plus any name found in the slide text).
Numeric and enum DNA fields are exempt. The wireframe draws only from the DNA, so it inherits this check.
"""
import json
import re
import shutil
import unicodedata
from functools import cache
from pathlib import Path

import spacy

from pipeline import build

NAME_LABELS = {"PERSON", "ORG", "GPE", "LOC", "NORP", "FAC", "PRODUCT", "EVENT", "WORK_OF_ART", "LAW"}
DESIGN_TERMS = {"kpi", "kpis", "swot", "gantt", "harvey", "roi", "cagr", "mece"}  # design vocabulary NER mislabels
TEMPLATE = (Path(__file__).parent / "templates" / "judge.txt").read_text()


@cache
def _nlp():
    return spacy.load("en_core_web_sm")


def _words(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", text)


def source_names(source):
    """Lower-case tokens of every named entity spaCy finds in the slide's own text."""
    return {t.lower_ for e in _nlp()(source).ents if e.label_ in NAME_LABELS
            for t in e if t.is_alpha and len(t) >= 3 and not t.is_stop}


def problems_in(text, source, names):
    found = []
    if re.search(r"\d", text):
        found.append("digit")
    src, words = _words(source), _words(text)
    grams = {tuple(src[i:i + 3]) for i in range(len(src) - 2)}
    shared = [" ".join(words[i:i + 3]) for i in range(len(words) - 2) if tuple(words[i:i + 3]) in grams]
    if shared:
        found.append(f"shared words with slide text: {shared[0]!r}")
    for e in _nlp()(text).ents:
        if e.label_ in NAME_LABELS and not {t.lower_ for t in e if t.is_alpha} <= DESIGN_TERMS:
            found.append(f"name ({e.label_}): {e.text!r}")
    hits = sorted(names & set(words))
    if hits:
        found.append(f"name from slide text: {hits[0]!r}")
    return found


def check(dna, source):
    problems = []
    try:
        build.check_schema(dna)
    except Exception as e:  # fail closed on any schema problem
        return [f"schema: {e}"]
    names = source_names(source)
    fields = {k: dna[k] for k in ("purpose", "why_it_works", "description")}
    fields |= {f"regions/{r['i']}/pattern": r["text"]["pattern"] for r in dna["regions"] if r["text"] and r["text"]["pattern"]}
    for key, text in fields.items():
        problems += [f"{key}: {p}" for p in problems_in(text, source, names)]
    return problems


def _verdict(path):
    if not path.exists():
        return "pending"
    try:
        v = json.loads(path.read_text())
        return "pass" if v["identified"] is False else "fail"
    except (ValueError, KeyError, TypeError):
        return "fail"


def run(deck_id, library):
    lib = Path(library)
    work, judge = lib / "work" / deck_id, lib / "judge" / deck_id
    (judge / "verdicts").mkdir(parents=True, exist_ok=True)
    (lib / "records").mkdir(exist_ok=True)
    (lib / "wireframes").mkdir(exist_ok=True)
    report = {}
    for f in sorted((work / "build").glob("*.json")):
        dna, rid = json.loads(f.read_text()), f.stem
        source = (work / "text" / f"slide-{dna['slide']:02d}.txt").read_text()
        problems = check(dna, source)
        r = report[rid] = {"auto": "fail" if problems else "pass", "problems": problems, "judge": "pending"}
        if problems:
            for p in (judge / f"{rid}.json", judge / f"{rid}.png"):
                p.unlink(missing_ok=True)
        else:
            shutil.copyfile(f, judge / f"{rid}.json")
            shutil.copyfile(f.with_suffix(".png"), judge / f"{rid}.png")
            r["judge"] = _verdict(judge / "verdicts" / f"{rid}.json")
        published = (lib / "records" / f"{rid}.json", lib / "wireframes" / f"{rid}.png")
        if r["auto"] == "pass" and r["judge"] == "pass":
            shutil.copyfile(f, published[0])
            shutil.copyfile(f.with_suffix(".png"), published[1])
        else:
            for p in published:
                p.unlink(missing_ok=True)
    ids = [rid for rid, r in report.items() if r["auto"] == "pass"]
    (judge / "JUDGE.txt").write_text(TEMPLATE.format(deck_id=deck_id, ids=", ".join(ids) or "none"))
    (work / "leak-report.json").write_text(json.dumps(report, indent=1))
    return report
