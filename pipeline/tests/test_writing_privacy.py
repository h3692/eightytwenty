"""The examples in playbook/writing.md are original: none names, quotes or echoes a source deck. Needs the local library
(library/work/*/text), so it skips in CI and runs on the Mac before a release.

An example is any backtick or double-quoted span in writing.md: slide text, before/after pairs and the "write instead"
phrases are all written that way. The 5-word rule covers the whole chapter. Digits are allowed; examples need numbers."""
import re
from functools import cache
from pathlib import Path

import pytest

from pipeline import leak_check

ROOT = Path(__file__).resolve().parents[2]
WORK = ROOT / "library" / "work"
# Standard finance abbreviations the IB register teaches by name. Rare words, so the name rule would flag them.
FINANCE_TERMS = {"ltm", "ntm", "bps", "irr", "moic", "yoy"}
RUN = 5  # words in a row shared with a slide

pytestmark = pytest.mark.skipif(not WORK.is_dir(), reason="no local library (CI)")


def _norm(line):
    return " ".join(line.split()).lower()


@cache
def corpus():
    """(name tokens, 5-word shingles, normalised lines) over the slide text of every deck, names found per deck."""
    names, shingles, lines = set(), set(), set()
    for deck in sorted(p for p in WORK.iterdir() if (p / "text").is_dir()):
        slides = [p.read_text(errors="ignore") for p in sorted((deck / "text").glob("*.txt"))]
        names |= leak_check.source_names("\n".join(slides))
        for s in slides:
            w = leak_check._words(s)
            shingles |= {tuple(w[i:i + RUN]) for i in range(len(w) - RUN + 1)}
            lines |= {_norm(line) for line in s.splitlines() if line.strip()}
    return names, shingles, lines


def examples():
    """Every quoted span, wrapped lines joined and bold markers dropped; chapter references (`polish`) are not examples."""
    chapters = {p.stem for p in (ROOT / "playbook").glob("*.md")}
    text = (ROOT / "playbook" / "writing.md").read_text()
    spans = (" ".join((a or b).replace("**", "").split()) for a, b in re.findall(r"`([^`]+)`|\"([^\"]+)\"", text))
    return [s for s in spans if s.split()[0] not in chapters]


def test_writing_has_examples_to_check():
    assert len(examples()) >= 80


def test_examples_name_nothing_from_the_decks():
    # leak_check's own rule for a name from slide text: rare, or written like a name (capitalised mid-line, all caps)
    names, allowed, found = corpus()[0], leak_check.DESIGN_TERMS | FINANCE_TERMS, []
    for ex in examples():
        doc = leak_check._nlp()(ex)
        as_name = {w for t in doc if leak_check._name_like(t) for w in leak_check._words(t.text)}
        found += [(ex, w) for w in leak_check._words(ex)
                  if w in names and w not in allowed and (w in as_name or not leak_check._common(w))]
    assert not found


def test_chapter_shares_no_five_word_run_with_a_slide():
    # the whole chapter, not only its examples: the avoid list and the prose are checked too
    shingles, w = corpus()[1], leak_check._words((ROOT / "playbook" / "writing.md").read_text())
    assert not [" ".join(w[i:i + RUN]) for i in range(len(w) - RUN + 1) if tuple(w[i:i + RUN]) in shingles]


def test_no_example_is_a_slide_line():
    # a one-word span (a unit like `(%)`, a label like `2026E` or `Sources:`) matches some slide line by chance
    lines = corpus()[2]
    assert not [ex for ex in examples() if len(ex.split()) > 1 and _norm(ex) in lines]
