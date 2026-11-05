"""Stage 4: leak check. Fails closed: only records that pass every automated check AND a recorded judge verdict
are promoted to library/records/ + library/wireframes/; anything else is withheld (and removed if promoted before).
A record's picture is its slide's mockup (library/mockups/<deck>/slide-NN.png, built from layouts/<deck>/slide-NN.v3.json);
a slide without a v3 layout or mockup, or with a mockup older than its layout, is never published, and its mockup .pptx
must pass the placeholder whitelist. Blank and near-duplicate slides (pipeline.dedupe) are withdrawn, never judged.

A deck flow (work/<deck>/flow-record.json, decks of flow.MIN_SLIDES+ slides) is checked the same way against the text of
EVERY slide of the deck, judged with the whole deck, and published to library/flows/ only if at least MIN_SHARE of
its slides are published too (blank and duplicate slides not counted).

Free-text fields (purpose, why_it_works, description, text patterns) must not contain digits, share a 3-word
sequence with the slide's original text, contain names (spaCy NER, plus any name found in the slide text), or
name a brand identity (HUES, BRAND_WORDS, BRAND_PHRASES, a web domain), whatever DESIGN_TERMS says.
Numeric and enum DNA fields are exempt. The wireframe draws only from the DNA, so it inherits this check.

NER and title-case slides mistake ordinary words for names, so a word only counts as a name when it is rare
(wordfreq zipf < COMMON_ZIPF and not in DESIGN_TERMS) or our text writes it like one (capitalised mid-sentence,
or all caps), so a common-word name opening a sentence is left to the judge. Standard framework names
(FRAMEWORKS, exact phrases) and the fixed headings of our own description template are exempt from the
shared-words rule.
"""
import html
import io
import json
import re
import shutil
import unicodedata
import zipfile
from functools import cache
from itertools import chain
from pathlib import Path

import spacy
from pptx import Presentation
from wordfreq import zipf_frequency

from pipeline import build, dedupe, flow, mockup

NAME_LABELS = {"PERSON", "ORG", "GPE", "LOC", "NORP", "FAC", "PRODUCT", "EVENT", "WORK_OF_ART", "LAW"}
# design and labelling vocabulary that NER mislabels and the frequency list rates rare
DESIGN_TERMS = {"kpi", "kpis", "swot", "gantt", "harvey", "roi", "cagr", "mece", "chevron", "chevrons", "mosaic",
                "screenshot", "screenshots", "label", "labels", "callout", "callouts", "icon", "icons", "tile", "tiles",
                "card", "cards", "banner", "banners", "timeline", "timelines", "funnel", "funnels", "matrix",
                "waterfall", "swimlane", "swimlanes", "donut", "doughnut", "italic", "breakeven", "infographic",
                "summarise", "summarises", "summarize", "summarizes",
                # common case-competition terms
                "financials", "deliverables", "storyboard", "faq", "roadmap", "persona", "agenda", "appendix",
                "takeaway", "benchmark", "playbook", "scorecard", "dashboard", "wireframe", "mockup", "pillar",
                "pillars", "workstream", "workstreams", "milestone", "milestones", "synergy", "synergies", "npv",
                "ebitda", "tam", "sam", "som", "b2b", "b2c", "d2c", "sku", "skus", "go", "to", "market", "gtm"}
COMMON_ZIPF = 3.5  # wordfreq zipf: 3.5 is about once per 300k words; below it a word may be a name
FRAMEWORKS = sorted((p.split() for p in (  # standard framework names, as _words() sees them; exact phrases only
    "strengths weaknesses opportunities threats", "strengths weaknesses opportunities and threats",
    "porter s five forces", "porters five forces", "threat of new entrants", "threat of substitutes",
    "bargaining power of suppliers", "bargaining power of buyers", "bargaining power of customers",
    "value chain analysis", "product price place promotion", "product price place and promotion",
    "tam sam som", "go to market", "total addressable market", "serviceable addressable market",
    "serviceable available market", "serviceable obtainable market", "stars cash cows question marks dogs", "stars cash cows dogs",
    "growth share matrix", "market penetration market development product development diversification",
    "market penetration market development product development and diversification",
    "political economic social technological legal environmental",
    "political economic social technological environmental legal",
    "political economic social technological")), key=len, reverse=True)
# brand identity re-identifies a deck from prose alone: specific hues, brand marks and what an illustration depicts.
# Banned whatever DESIGN_TERMS says; roles (primary, accent, dark, mid-grey ...) and generic placement words
# ("logo top right", "illustration", "photo", "icon", "image", "map", "headshot slots") stay allowed.
HUES = {"red", "orange", "yellow", "green", "blue", "purple", "pink", "magenta", "coral", "teal", "navy", "turquoise",
        "maroon", "gold", "golden", "silver", "beige", "brown", "olive", "lime", "cyan", "violet", "indigo", "crimson",
        "scarlet", "amber", "peach", "mint", "lavender", "burgundy", "fuchsia", "aqua", "khaki", "ochre", "mustard",
        "saffron", "emerald", "ruby", "sapphire", "salmon", "lilac", "mauve", "cobalt", "azure", "vermilion"}
BRAND_WORDS = {"mascot", "mascots", "wordmark", "wordmarks", "lockup", "lockups", "logomark", "logomarks", "monogram",
               "monograms", "emblem", "emblems", "sponsor", "sponsors", "sponsored", "crest", "crests", "watermark",
               "watermarks", "signature", "signatures", "swoosh", "portrait", "portraits", "affiliation",
               "affiliations", "affiliated", "domain", "domains", "url", "urls", "www", "http", "https",
               # what an illustration depicts
               "botanical", "floral", "flower", "flowers", "foliage", "leaf", "character", "characters",
               "animal", "animals", "cat", "bird", "birds", "lion", "tiger", "elephant", "bear", "owl", "fox", "horse",
               "fish", "butterfly", "bee", "rabbit", "panda", "monkey", "eagle", "dragon", "unicorn", "penguin",
               "deer", "wolf", "shark", "dolphin", "whale", "landmark", "landmarks", "monument", "skyline",
               "cityscape", "mountain", "mountains"}
BRAND_WORDS |= HUES | {h + s for h in HUES for s in ("s", "ish", h[-1] + "ish")} | {h[:-1] + "ish" for h in HUES}
BRAND_PHRASES = [("world", "map")] + [("brand", w) for w in ("art", "artwork", "illustration", "illustrations",
                                                             "motif", "motifs", "swoosh", "mark", "marks", "graphic",
                                                             "graphics", "pattern", "character", "mascot")]
DOMAIN = re.compile(r"\b[a-z0-9-]+(?:\.[a-z0-9-]+)*\.(?:com|org|net|io|co|edu|gov|ai|app|ca|uk|in|au)\b", re.I)
TEMPLATE = (Path(__file__).parent / "templates" / "judge.txt").read_text()
MIN_SHARE = 0.6  # of a deck's slides that must be published before its flow is
MASTER_PARTS = ("ppt/slideMasters/", "ppt/slideLayouts/")  # the only parts the stock boilerplate may sit in


@cache
def _nlp():
    return spacy.load("en_core_web_sm")


def _words(text):
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.findall(r"[a-z0-9]+", text)


def _fixed_lists():
    """Our own fixed lists as _words() phrases: label, flow and layout enums, the archetype table's ids and slide jobs."""
    schema = {n: json.loads((Path(__file__).parent / "schema" / f"{n}.json").read_text())
              for n in ("labels.v1", "flow.v1", "layout.v3")}
    labels = schema["labels.v1"]
    lists = [labels["properties"][k]["enum"] for k in ("archetype", "argument_shape", "insight_device", "data_type")]
    lists += [labels["$defs"]["role"]["enum"], schema["flow.v1"]["properties"]["sections"]["items"]["enum"],
              schema["layout.v3"]["$defs"]["component"]["properties"]["kind"]["enum"]]
    table = (Path(__file__).parent.parent / "playbook" / "archetypes.md").read_text()
    lists += re.findall(r"^\| `([a-z-]+)` \| ([^|]+) \|", table, re.M)
    return [_words(v) for v in chain(*lists)]


def _template_phrases():
    """The fixed scaffold of build.describe ("Why it works:" ...) as _words() phrases: the text between its fields."""
    blank = "\0"
    dna = dict.fromkeys(("archetype", "argument_shape", "insight_device", "data_type", "industry", "purpose",
                         "why_it_works"), blank) | {"regions": [{"role": blank, "text": {"pattern": blank}}]}
    return [_words(part) for part in build.describe(dna).split(blank)]


DESIGN_TERMS |= {w for p in _fixed_lists() for w in p}
# our own multi-word ids ("how it works") and description headings ("why it works") are not slide copy; shorter
# ones would mask single ordinary words
FRAMEWORKS = sorted(FRAMEWORKS + [p for p in _fixed_lists() + _template_phrases() if len(p) >= 3], key=len,
                    reverse=True)


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
    if re.search(r"\d", re.sub(r"\w+", lambda m: "" if m[0].lower() in DESIGN_TERMS else m[0], text)):  # B2B
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
    brand = {w for w in words if w in BRAND_WORDS} | {" ".join(p) for p in zip(words, words[1:]) if p in BRAND_PHRASES}
    brand |= {m.lower() for m in DOMAIN.findall(text)}
    if brand:
        found.append(f"brand identity: {', '.join(sorted(brand))}")
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


def check_flow(record, source):
    """Problems in a deck-flow record; source is the text of every slide in the deck, so a name or phrase from any
    slide fails it. why_the_flow_works is its only free text: everything else is fixed lists and computed."""
    try:
        if set(record) != flow.RECORD_KEYS:
            raise ValueError(f"fields {sorted(set(record) ^ flow.RECORD_KEYS)}")
        flow.validate({"sections": [s["section"] for s in record["steps"]], "arc": record["arc"],
                       "why_the_flow_works": record["why_the_flow_works"]}, len(record["steps"]))
    except Exception as e:  # fail closed on any schema problem
        return [f"schema: {e}"]
    return [f"why_the_flow_works: {p}"
            for p in problems_in(record["why_the_flow_works"], source, source_names(source))]


@cache
def _stock_app():
    out = io.BytesIO()
    Presentation().save(out)
    with zipfile.ZipFile(out) as z:
        return z.read("docProps/app.xml")


@cache
def _stock_text():
    """Text runs of the stock python-pptx master and layouts every mockup carries ("Click to edit ...")."""
    out = io.BytesIO()
    Presentation().save(out)
    return frozenset(t for _, t in _texts(out.getvalue())[0])


def _texts(blob):
    """Every text run in a .pptx as (part name, text), and every cached chart value and embedded workbook string."""
    runs, values = [], []
    with zipfile.ZipFile(io.BytesIO(blob)) as z:
        for name in z.namelist():
            if name.endswith(".xlsx"):
                inner_runs, inner_values = _texts(z.read(name))
                values += [t for _, t in inner_runs] + inner_values
            elif name.endswith(".xml"):
                xml = z.read(name).decode()
                runs += [(name, html.unescape(t)) for t in re.findall(r"<a:t(?:\s[^>]*)?>([^<]*)</a:t>", xml)]
                values += map(html.unescape, re.findall(r"<(?:c:v|t)(?:\s[^>]*)?>([^<]*)</(?:c:v|t)>", xml))
    return runs, values


def mockup_problems(path):
    """A mockup .pptx holds fixed placeholder copy only: every text run is placeholder vocabulary (or the stock
    master's boilerplate, inside the master and layout parts only), chart data is numbers, the core properties are
    empty, the app properties are the stock defaults and there is no image."""
    try:
        blob = Path(path).read_bytes()
        runs, values = _texts(blob)
        props = Presentation(io.BytesIO(blob)).core_properties
        with zipfile.ZipFile(io.BytesIO(blob)) as z:
            images = [n for n in z.namelist() if re.search(r"\.(jpe?g|png|gif|bmp|tiff?|emf|wmf|svg|wdp)$", n, re.I)]
            images += ["image content type"] * ("image/" in z.read("[Content_Types].xml").decode())
            app = z.read("docProps/app.xml")
    except Exception as e:  # fail closed on anything unreadable
        return [f"unreadable: {e}"]
    problems = list(dict.fromkeys(f"text outside the placeholder vocabulary: {t!r}" for part, t in runs
                                  if t not in mockup.VOCAB and not (t in _stock_text() and part.startswith(MASTER_PARTS))))
    problems += [f"text outside the placeholder vocabulary: {v!r}" for v in dict.fromkeys(values)
                 if not re.fullmatch(r"-?\d+(\.\d+)?", v)]
    named = [k for k in ("author", "category", "comments", "content_status", "identifier", "keywords", "language",
                         "last_modified_by", "subject", "title", "version") if getattr(props, k)]
    if named:
        problems.append(f"core properties not anonymous: {', '.join(named)}")
    if app != _stock_app():  # Company, Manager, HyperlinkBase, TitlesOfParts ... as python-pptx ships them
        problems.append("app properties not the stock defaults (docProps/app.xml)")
    problems += [f"image: {n}" for n in images]
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
    report, skip = {}, dedupe.excluded(deck_id, lib)
    for f in sorted((work / "build").glob("*.json")):
        dna, rid = json.loads(f.read_text()), f.stem
        if rid in skip:  # blank or a near-duplicate: withdrawn, never judged
            report[rid] = {"auto": "excluded", "problems": [skip[rid]], "judge": "excluded", "published": False,
                           "excluded": skip[rid]}
            for p in (judge / f"{rid}.json", judge / f"{rid}.png", lib / "records" / f"{rid}.json",
                      lib / "wireframes" / f"{rid}.png"):
                p.unlink(missing_ok=True)
            continue
        nn = f"slide-{dna['slide']:02d}"
        source = (work / "text" / f"{nn}.txt").read_text()
        pic, pptx = (lib / "mockups" / deck_id / f"{nn}{ext}" for ext in (".png", ".pptx"))
        layout = lib / "layouts" / deck_id / f"{nn}.v3.json"
        problems = check(dna, source)
        if not layout.exists():
            problems.append(f"no v3 layout: write layouts/{deck_id}/{nn}.v3.json, then run mockup")
        elif not (pic.exists() and pptx.exists()):
            problems.append("no mockup: run mockup")
        elif min(pic.stat().st_mtime, pptx.stat().st_mtime) < layout.stat().st_mtime:
            problems.append("stale mockup: its v3 layout changed after it was built, run mockup")
        else:
            problems += [f"mockup: {p}" for p in mockup_problems(pptx)]
        r = report[rid] = {"auto": "fail" if problems else "pass", "problems": problems, "judge": "pending"}
        if problems:
            for p in (judge / f"{rid}.json", judge / f"{rid}.png"):
                p.unlink(missing_ok=True)
        else:
            shutil.copyfile(f, judge / f"{rid}.json")
            shutil.copyfile(pic, judge / f"{rid}.png")
            r["judge"] = _verdict(judge / "verdicts" / f"{rid}.json")
        published = (lib / "records" / f"{rid}.json", lib / "wireframes" / f"{rid}.png")
        r["published"] = r["auto"] == "pass" and r["judge"] == "pass"
        if r["published"]:
            shutil.copyfile(f, published[0])
            shutil.copyfile(pic, published[1])
        else:
            for p in published:
                p.unlink(missing_ok=True)
    ids = [rid for rid, r in report.items() if r["auto"] == "pass"]
    visible = sorted(work.glob("slide-??.json"))
    record, published = work / "flow-record.json", lib / "flows" / f"{deck_id}.json"
    shown = sum(r["published"] for r in report.values())  # slides of this deck published
    (judge / "flow.json").unlink(missing_ok=True)
    if len(visible) >= flow.MIN_SLIDES:
        if record.exists():
            deck_text = "\n".join((work / "text" / f"{f.stem}.txt").read_text() for f in visible)
            problems = check_flow(json.loads(record.read_text()), deck_text)
        else:
            problems = ["no flow record: run flow-prep, follow its worksheet, then flow-build"]
        r = report["flow"] = {"auto": "fail" if problems else "pass", "problems": problems, "judge": "pending"}
        if not problems:
            shutil.copyfile(record, judge / "flow.json")
            r["judge"] = _verdict(judge / "verdicts" / "flow.json")
        kept = max(len(visible) - len(skip), 1)  # blank and duplicate slides are never published, so never counted
        r["published"] = r["auto"] == "pass" and r["judge"] == "pass" and shown / kept >= MIN_SHARE
        if r["auto"] == "pass" and r["judge"] == "pass" and not r["published"]:
            problems.append(f"withheld: {shown} of {kept} slides published, a flow needs {MIN_SHARE:.0%}")
    if report.get("flow", {}).get("published"):
        published.parent.mkdir(exist_ok=True)
        shutil.copyfile(record, published)
    else:
        published.unlink(missing_ok=True)
    flow_line = ("Deck flow: flow.json, judged with the whole deck; verdict in verdicts/flow.json"
                 if (judge / "flow.json").exists() else "Deck flow: none")
    (judge / "JUDGE.txt").write_text(TEMPLATE.format(deck_id=deck_id, ids=", ".join(ids) or "none", flow=flow_line))
    (work / "leak-report.json").write_text(json.dumps(report, indent=1))
    return report
