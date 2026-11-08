"""Checks on the generated-question plan (scripts/generate_questions.py): its answer keys follow the same
rules as test_questions.json, and the saved plan is what the code builds from the current knowledge layer."""

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import generate_questions as gq  # noqa: E402

import knowledge  # noqa: E402
import run_eval  # noqa: E402

ITEMS, _ = gq.build_plan()


def test_plan_has_no_problems():
    assert gq.plan_problems(ITEMS) == []


def test_plan_is_deterministic():
    again, _ = gq.build_plan()
    assert again == ITEMS


def test_plan_covers_every_category_and_rule():
    assert {q["category"] for q in ITEMS} == set(run_eval.CATEGORIES)
    assert 90 <= len(ITEMS) <= 110


def test_every_property_is_used():
    used = {q["derived_from"].get("property") for q in ITEMS}
    assert set(knowledge.vocabulary()["properties"]) <= used


@pytest.mark.parametrize("q", ITEMS, ids=lambda q: q["id"])
def test_brief_avoids_forbidden_terms(q):
    assert not [t for t in q["forbidden_terms"] if gq.contains_term(q["brief"], t)]


def test_saved_plan_matches_the_knowledge_layer():
    plan = json.loads(gq.PLAN_PATH.read_text(encoding="utf-8"))
    assert plan["knowledge_version"] == knowledge.knowledge_version(), "knowledge changed: rerun the plan command"
    assert plan["items"] == ITEMS, "the rules changed: rerun `python scripts/generate_questions.py plan`"


# --- the written questions (test_questions_generated.json) ---

PLAN = json.loads(gq.PLAN_PATH.read_text(encoding="utf-8"))
QUESTIONS = json.loads(gq.QUESTIONS_PATH.read_text(encoding="utf-8"))
CURATED = json.loads(gq.CURATED_PATH.read_text(encoding="utf-8"))


def test_written_questions_pass_check():
    assert gq.question_problems(QUESTIONS, PLAN, CURATED) == []


def _with(index: int, **changes) -> list[dict]:
    questions = [dict(q) for q in QUESTIONS]
    questions[index].update(changes)
    return questions


def test_check_catches_a_changed_answer_key():
    problems = gq.question_problems(_with(0, expected_ids=["EQ01"]), PLAN, CURATED)
    assert any("expected_ids differs from the plan" in p for p in problems)


def test_check_catches_a_forbidden_term():
    term = PLAN["items"][0]["forbidden_terms"][0]
    problems = gq.question_problems(_with(0, question=f"Can I use the {term} for this?"), PLAN, CURATED)
    assert any("forbidden term" in p for p in problems)


def test_check_catches_duplicates_and_curated_paraphrases():
    problems = gq.question_problems(_with(1, question=QUESTIONS[0]["question"]), PLAN, CURATED)
    assert any("near-duplicate" in p for p in problems)
    problems = gq.question_problems(_with(0, question=CURATED[1]["question"]), PLAN, CURATED)
    assert any("too close to curated" in p for p in problems)


def test_check_catches_missing_items_and_stale_knowledge():
    problems = gq.question_problems(QUESTIONS[1:], {**PLAN, "knowledge_version": "old"}, CURATED)
    assert any("not in the questions" in p for p in problems)
    assert any("knowledge version" in p for p in problems)
