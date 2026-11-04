"""Stage 4: leak check. Fails closed: only records that pass every automated check AND a recorded judge verdict
are promoted to library/records/ + library/wireframes/; anything else is withheld (and removed if promoted before).

Free-text fields (purpose, why_it_works, description, text patterns) must not contain digits, share a 3-word
sequence with the slide's original text, or contain names (spaCy NER, plus any name found in the slide text).
Numeric and enum DNA fields are exempt. The wireframe draws only from the DNA, so it inherits this check.

NER and title-case slides mistake ordinary words for names, so a word only counts as a name when it is rare
(wordfreq zipf < COMMON_ZIPF and not in DESIGN_TERMS) or our text writes it like one (capitalised mid-sentence,
or all caps), so a common-word name opening a sentence is left to the judge. Standard framework names
(FRAMEWORKS, exact phrases) are exempt from the shared-words rule.
"""
import json
import re
import shutil
import unicodedata
from functools import cache
from pathlib import Path

import spacy
from wordfreq import zipf_frequency

from pipeline import build

NAME_LABELS = {"PERSON", "ORG", "GPE", "LOC", "NORP", "FAC", "PRODUCT", "EVENT", "WORK_OF_ART", "LAW"}
# design and labelling vocabulary that NER mislabels and the frequency list rates rare
DESIGN_TERMS = {"kpi", "kpis", "swot", "gantt", "harvey", "roi", "cagr", "mece", "chevron", "chevrons", "mosaic",
                "screenshot", "screenshots", "label", "labels", "callout", "callouts", "icon", "icons", "tile", "tiles",
                "card", "cards", "banner", "banners", "timeline", "timelines", "funnel", "funnels", "matrix",
                "waterfall", "swimlane", "swimlanes", "donut", "doughnut", "italic", "breakeven", "infographic",
                "summarise", "summarises", "summarize", "summarizes"}
COMMON_ZIPF = 3.5  # wordfreq zipf: 3.5 is about once per 300k words; below it a word may be a name
FRAMEWORKS = sorted((p.split() for p in (  # standard framework names, as _words() sees them; exact phrases only
    "strengths weaknesses opportunities threats", "strengths weaknesses opportunities and threats",
    "porter s five forces", "porters five forces", "threat of new entrants", "threat of substitutes",
    "bargaining power of suppliers", "bargaining power of buyers", "bargaining power of customers",
    "value chain analysis", "product price place promotion", "product price place and promotion",
    "tam sam som", "total addressable market", "serviceable addressable market", "serviceable available market",
    "serviceable obtainable market", "stars cash cows question marks dogs", "stars cash cows dogs",
    "growth share matrix", "market penetration market development product development diversification",
    "market penetration market development product development and diversification",
    "political economic social technological legal environmental",
    "political economic social technological environmental legal",
    "political economic social technological")), key=len, reverse=True)
TEMPLATE = (Path(__file__).parent / "templates" / "judge.txt").read_text()


@cache
def _nlp():
    return spacy.load("en_core_web_sm")


def _words(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", text)


def _common(word):
    return word in DESIGN_TERMS or zipf_frequency(word, "en") >= COMMON_ZIPF


def _name_like(t):
    """Written like a name: all caps, or capitalised where no sentence or line starts."""
    prev = t.doc[t.i - 1] if t.i else None
    start = prev is None or prev.is_space or prev.text in ".!?:;"
    return t.is_alpha and ((t.is_upper and len(t) > 1) or (t.text[0].isupper() and not start))


def _mask_frameworks(words):
    words = list(words)
    for p in FRAMEWORKS:
        for i in range(len(words) - len(p) + 1):
            if words[i:i + len(p)] == p:
                words[i:i + len(p)] = [None] * len(p)  # None breaks every 3-gram that touches the phrase
    return words


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
    masked = _mask_frameworks(words)
    shared = [" ".join(masked[i:i + 3]) for i in range(len(masked) - 2) if tuple(masked[i:i + 3]) in grams]
    if shared:
        found.append(f"shared words with slide text: {shared[0]!r}")
    doc = _nlp()(text)
    for e in doc.ents:
        if e.label_ in NAME_LABELS and not all(t.lower_ in DESIGN_TERMS or (_common(t.lower_) and not _name_like(t))
                                               for t in e if t.is_alpha):
            found.append(f"name ({e.label_}): {e.text!r}")
    written_as_name = {w for t in doc if _name_like(t) for w in _words(t.text)}
    hits = sorted(w for w in names & set(words) if w not in DESIGN_TERMS and (w in written_as_name or not _common(w)))
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
