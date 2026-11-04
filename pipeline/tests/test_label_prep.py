import json
import re
from pathlib import Path

import pytest

from pipeline import extract, label_prep
from pipeline.tests.conftest import fixture_labels

PLAYBOOK = Path(__file__).resolve().parents[2] / "playbook" / "archetypes.md"


@pytest.fixture
def work(deck, lib):
    deck_id = extract.run(deck, lib, render=False)
    label_prep.run(deck_id, lib)
    return lib / "work" / deck_id


def _slide(work, n):
    return json.loads((work / f"slide-{n:02d}.json").read_text())


def test_archetype_enum_matches_playbook_ids():
    ids = re.findall(r"^\| `([a-z-]+)` \|", PLAYBOOK.read_text(), re.M)
    assert len(ids) == 17
    assert label_prep.SCHEMA["properties"]["archetype"]["enum"] == ids


def test_industry_is_a_fixed_list_of_at_most_15():
    assert 2 <= len(label_prep.SCHEMA["properties"]["industry"]["enum"]) <= 15


def test_writes_one_fixed_prompt_per_slide(work):
    prompts = sorted(work.glob("slide-*.prompt.txt"))
    assert [p.name for p in prompts] == ["slide-01.prompt.txt", "slide-02.prompt.txt"]
    text = prompts[1].read_text()
    for needed in ("slide-02.png", "slide-02.json", "labels/slide-02.json", "situational-analysis", "why_it_works",
                   "text_patterns", "claim + mechanism + number"):
        assert needed in text
    # Fixed template: the two prompts differ only in the slide number.
    assert prompts[0].read_text().replace("slide-01", "slide-02") == text
    assert (work / "labels").is_dir()


def test_valid_labels_pass(work):
    label_prep.validate(fixture_labels(_slide(work, 2)), _slide(work, 2))


@pytest.mark.parametrize("mutate, message", [
    (lambda l: l.update(archetype="hero-slide"), "archetype"),
    (lambda l: l.update(industry="aerospace-defense-and-space"), "industry"),
    (lambda l: l.update(client="Somebody"), "client"),
    (lambda l: l["regions"].pop("0"), "region"),
    (lambda l: l["regions"].update({"99": "body"}), "region"),
    (lambda l: l["text_patterns"].append({"region": 99, "pattern": "short claim", "words": 3}), "non-text region"),
])
def test_invalid_labels_fail(work, mutate, message):
    labels = fixture_labels(_slide(work, 2))
    mutate(labels)
    with pytest.raises(ValueError, match=message):
        label_prep.validate(labels, _slide(work, 2))
