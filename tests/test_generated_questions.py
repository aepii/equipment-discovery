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


# --- cross-checks: compare, facts, curated overlap ---

def test_every_curated_question_is_mapped_or_skipped_with_a_reason():
    ids = {q["id"] for q in CURATED}
    assert ids == set(gq.CURATED_INPUTS) | set(gq.CURATED_SKIPPED)
    assert all(gq.CURATED_SKIPPED.values())


def test_compare_finds_agreement_and_conflicts():
    rows = {r["id"]: r for r in gq.comparisons(CURATED)}
    assert rows["Q4"]["differs"] == [] and rows["Q10"]["differs"] == []
    assert any(d["kind"] == "conflict" for d in rows["Q3"]["ids"])
    report = gq.comparison_report(list(rows.values()))
    assert report.index("### Q3") < report.index("### Q1:")  # conflicts first
    assert "Stefan-sourced or reviewed" in report


def test_workflow_with_a_missing_prep_step_flags_it():
    key = gq.key_workflow("sputter_coating", "environmental_sem", "surface_morphology")
    assert key["expected_ids"] == ["EQ10"]
    assert gq.missing_techniques_named(key["expected_not_available"]) == ["sputter_coating"]


def test_facts_report_lists_every_instrument_and_marks_rows_to_check_first():
    report = gq.facts_report(ITEMS)
    assert all(f"| {eq} |" in report for eq in knowledge.annotations())
    assert "★" in report and "**none listed**" in report


def test_check_rejects_a_paraphrase_of_a_curated_question_with_the_same_inputs():
    vague = next(i for i, q in enumerate(QUESTIONS) if q["id"] == "G096")
    text = "Do you have anything for testing materials?"  # a paraphrase of Q16, not a copy
    assert gq.SAME_INPUTS_PARAPHRASE <= gq.similarity(text, CURATED[15]["question"]) < gq.CURATED_PARAPHRASE
    problems = gq.question_problems(_with(vague, question=text), PLAN, CURATED)
    assert any("same rule inputs" in p for p in problems)
