"""Checks on test_questions.json, so a typo in an ID or regex fails here and not halfway through a run."""

import re
from collections import Counter

import pytest

import core
import run_eval

QUESTIONS = run_eval.load_questions()
KNOWN = set(core.equipment_by_id())
REQUIRED = {"id", "category", "status", "question", "expected_ids", "acceptable_ids", "unacceptable_ids",
            "expected_not_available", "expected_accessories", "expect_clarifying", "notes"}


def test_size_and_unique_ids():
    ids = [q["id"] for q in QUESTIONS]
    assert len(ids) >= 15
    assert len(set(ids)) == len(ids)


def test_every_category_has_at_least_two_questions():
    counts = Counter(q["category"] for q in QUESTIONS)
    assert set(counts) == set(run_eval.CATEGORIES)
    assert min(counts.values()) >= 2


@pytest.mark.parametrize("q", QUESTIONS, ids=lambda q: q["id"])
def test_question_is_well_formed(q):
    assert REQUIRED <= set(q)
    assert q["status"] in ("draft", "reviewed")
    expected, acceptable, unacceptable = (set(q[k]) for k in ("expected_ids", "acceptable_ids", "unacceptable_ids"))
    assert expected | acceptable | unacceptable <= KNOWN
    assert not (expected & acceptable or expected & unacceptable or acceptable & unacceptable)
    assert set(q["expected_accessories"]) <= expected | acceptable
    for pattern in q["expected_not_available"] + [p for ps in q["expected_accessories"].values() for p in ps]:
        re.compile(pattern)
    if q["expect_clarifying"]:
        assert not expected, "a vague question should expect a clarifying question, not instruments"
