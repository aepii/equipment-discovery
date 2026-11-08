"""The presentation interface never shows internal project wording, and gets only allowlisted fields."""

import json
import re
from pathlib import Path

import pytest

import answer_graph
import core
from api import presentation

FORBIDDEN = ["stefan", "lohfeld", "expert", "mentor", "faculty", "reviewed", "draft", "review",
             "test question", "poster", "streamlit"]
_FORBIDDEN = re.compile(r"\b(" + "|".join(re.escape(w) for w in FORBIDDEN) + r")", re.I)
DIST = Path(__file__).parent.parent / "web" / "dist"
# Library code in the bundle, never shown: the HTML <video poster> attribute in react-markdown's tables.
BUNDLE_IGNORE = re.compile(r"\bposter:(?=null|\[)")


def forbidden_in(text: str) -> list[str]:
    return sorted({m.group(1).lower() for m in _FORBIDDEN.finditer(text)})


def saved_answers() -> list[tuple[str, str]]:
    return [(a["mode"], a["question"]) for a in core.load_demo_answers()["answers"]]


@pytest.mark.parametrize("mode,question", saved_answers())
def test_saved_answers_are_clean(mode, question):
    result = core.demo_answer(mode, question)
    payload = json.dumps(presentation.sanitize(result), ensure_ascii=False)
    graph = answer_graph.build_dot(result) + json.dumps(answer_graph.build_graph(result))
    assert forbidden_in(payload + graph) == []


def test_examples_equipment_and_footer_are_clean():
    text = json.dumps([presentation.EXAMPLES, presentation.equipment(), presentation.FICTIONAL_CONTACTS,
                       presentation.MODE_LABELS])
    assert forbidden_in(text) == []


def test_every_example_has_a_saved_answer_in_both_shown_modes():
    for example in presentation.EXAMPLES:
        for mode in ("annotated", "naive"):
            assert core.demo_answer(mode, example["question"]), (mode, example["question"])


def test_card_fields_are_an_allowlist():
    result = core.demo_answer("annotated", presentation.EXAMPLES[0]["question"])
    card = presentation.sanitize(result)["primary"][0]
    assert set(card) == {"id", "name", "manufacturer", "model", "location", "contact", "demo_instrument", "role",
                         "technique", "property", "why", "fit", "fit_reason", "destructive_level", "destructive",
                         "dead_end", "installed", "to_confirm", "workflow", "cautions", "capabilities_note"}
    assert "notes" not in card and "notes_status" not in card


def test_payload_drops_raw_output():
    result = core.demo_answer("annotated", presentation.EXAMPLES[1]["question"])
    payload = presentation.sanitize(result)
    assert "raw" not in payload and "usage" not in payload and "demo" not in payload


def test_clean_text_removes_note_status_wording():
    assert forbidden_in(presentation.clean_text(
        "Per the draft notes (not yet reviewed), the DSC fits. Draft instrument notes say so.")) == []


def test_demo_instruments_are_labelled_without_notes():
    demo = [e for e in presentation.equipment() if e["demo_instrument"]]
    assert demo and all("notes" not in e for e in demo)


def test_naive_gaps_and_recommended_line_removed():
    result = core.demo_answer("naive", presentation.EXAMPLES[1]["question"])
    payload = presentation.sanitize(result)
    assert "Recommended:" not in payload["text"]
    assert isinstance(payload["gaps"], list)


def test_errors_are_friendly():
    assert "ProviderError" not in presentation.friendly_error("ProviderError: Mock error 429")
    limit = "This session has reached its limit of 5 model calls."
    assert presentation.friendly_error(limit) == limit


@pytest.mark.skipif(not DIST.is_dir(), reason="frontend not built")
def test_built_frontend_is_clean():
    found = {}
    for path in DIST.rglob("*"):
        if path.suffix in (".js", ".html", ".css", ".json", ".txt", ".svg"):
            words = forbidden_in(BUNDLE_IGNORE.sub("", path.read_text(encoding="utf-8", errors="ignore")))
            if words:
                found[str(path.relative_to(DIST))] = words
    assert found == {}
