import csv
import json

import pytest

import core
import run_eval

QUESTION = {"id": "QX", "category": "problem-only", "status": "draft", "question": "q",
            "expected_ids": ["EQ15", "EQ19"], "acceptable_ids": ["EQ10"], "unacceptable_ids": ["EQ01"],
            "expected_not_available": ["micro.?CT", "GPC"], "expected_accessories": {"EQ15": ["load cell", "platen"]},
            "expect_clarifying": False}


def structured(recs, **extra) -> dict:
    return core.read_answer("structured", json.dumps({"recommendations": recs, **extra}))


# --- score ---

def test_score_structured():
    result = structured([
        {"instrument_id": "EQ15", "accessories_to_confirm": ["a 1 kN load cell"]},
        {"instrument_id": "EQ01"}, {"instrument_id": "EQ10"}, {"instrument_id": "EQ12"}],
        summary="Micro-CT would be ideal but is not listed.")
    s = run_eval.score(QUESTION, result)
    assert (s["expected_hits"], s["expected_total"], s["recall"]) == (1, 2, 0.5)
    assert (s["unacceptable_hits"], s["unacceptable_ids"]) == (1, "EQ01")
    assert s["unclassified_ids"] == "EQ12"  # EQ10 is acceptable, so not unclassified
    assert (s["na_hits"], s["na_total"]) == (1, 2)  # found in the summary, not only in not_available
    assert (s["accessory_hits"], s["accessory_total"]) == (1, 2)
    assert s["clarifying_ok"] is True
    assert s["contacts_ok"] is None


def test_score_accessories_only_for_found_instruments():
    s = run_eval.score(QUESTION, structured([{"instrument_id": "EQ19"}]))
    assert s["accessory_total"] == 0


def test_score_naive_contacts():
    known = core.equipment_by_id()
    raw = f"Instron 5967, contact {known['EQ15']['contact']}. Rheometer.\nRecommended: EQ15, EQ19"
    s = run_eval.score(QUESTION, core.read_answer("naive", raw))
    assert (s["contacts_ok"], s["contacts_total"]) == (1, 2)


def test_score_flags_expected_instruments_only_mentioned():
    raw = "No microscope can do this; the Instron 5967 or the hybrid rheometer could.\nRecommended: none"
    s = run_eval.score(QUESTION, core.read_answer("naive", raw))
    assert s["expected_hits"] == 0
    assert s["expected_only_mentioned"] == "EQ15 EQ19"


@pytest.mark.parametrize("raw, asked", [
    ("What is your sample made of?", True),
    ("More information is needed regarding your sample.\n\nRecommended: none", True),
    ("None of the instruments are suitable.\n\nRecommended: none", False),
    ("Is this OK? Use the DSC.\nRecommended: EQ18", False),  # recommends something, so not a clarifying answer
])
def test_naive_clarifying_heuristic(raw, asked):
    assert run_eval.asked_clarifying(core.read_answer("naive", raw)) is asked


def test_score_clarifying():
    vague = {**QUESTION, "expected_ids": [], "expect_clarifying": True}
    asked = structured([], clarifying_question="Which material?")
    assert run_eval.score(vague, asked)["clarifying_ok"] is True
    assert run_eval.score(QUESTION, asked)["clarifying_ok"] is False
    assert run_eval.score(vague, core.read_answer("naive", "What is your sample made of?"))["asked_clarifying"]


def test_score_skips_errors():
    result = {**core.new_result("naive"), "error": "boom"}
    assert all(v is None for v in run_eval.score(QUESTION, result).values())


# --- consistency ---

def test_consistency():
    a, b = frozenset({"EQ15"}), frozenset({"EQ15", "EQ19"})
    c = run_eval.consistency([a, a, b])
    assert c["stable_runs"] == "2/3"
    assert c["mean_jaccard"] == pytest.approx((1 + 0.5 + 0.5) / 3, abs=1e-3)
    assert c["id_frequency"] == "EQ15:3 EQ19:1"
    assert run_eval.consistency([frozenset(), frozenset()])["mean_jaccard"] == 1.0


# --- retry ---

def test_retry_only_transient_errors(monkeypatch):
    calls = []

    def flaky(question):
        calls.append(question)
        return {**core.new_result("naive"), "error": "ServerError: 503 UNAVAILABLE" if len(calls) < 2 else None}

    monkeypatch.setitem(run_eval.RUNNERS, "naive", flaky)
    assert run_eval.run_with_retry("naive", "q", wait=0)["error"] is None
    assert len(calls) == 2

    calls.clear()
    monkeypatch.setitem(run_eval.RUNNERS, "naive", lambda q: calls.append(q) or {**core.new_result("naive"), "error": "ValueError: bad"})
    run_eval.run_with_retry("naive", "q", wait=0)
    assert len(calls) == 1


# --- end to end with the mock model, then re-score the saved CSV ---

def test_run_then_rescore_round_trip(tmp_path):
    questions = run_eval.select_questions(run_eval.load_questions(), ["Q1", "Q2", "Q16"], None)
    rows = run_eval.run(questions, ["structured", "naive"], runs=2)
    assert len(rows) == 3 * 2 * 2 and not any(r["error"] for r in rows)
    q1 = [r for r in rows if r["question_id"] == "Q1"]
    assert all(r["recall"] == 1.0 and r["unacceptable_hits"] == 0 for r in q1)

    out = tmp_path / "run_test.csv"
    run_eval.write_outputs(rows, out)
    with (tmp_path / "run_test_summary.csv").open(encoding="utf-8-sig") as f:
        summary = list(csv.DictReader(f))
    q1_structured = next(s for s in summary if s["question_id"] == "Q1" and s["mode"] == "structured")
    assert q1_structured["stable_runs"] == "2/2"
    assert {s["scope"] for s in summary} == {"question", "draft", "all"}

    rescored = run_eval.rescore(out, run_eval.load_questions())
    key = ("question_id", "mode", "run", "instrument_ids", "recall", "na_hits", "clarifying_ok")
    assert [tuple(str(r[k]) for k in key) for r in rescored] == [tuple(str(r[k]) for k in key) for r in rows]


@pytest.mark.parametrize("pattern, text", [
    (r"\bGPC\b|\bSEC\b|size.exclusion", "GPC / SEC / size exclusion"),
    ("micro.?CT|µCT", "micro CT / µCT"),
    ("X.?ray diffract|\\bXRD\\b", "X ray diffract / XRD"),
])
def test_readable_patterns(pattern, text):
    assert run_eval.readable(pattern) == text


def test_review_sheet_names_instruments():
    text = run_eval.review_sheet(run_eval.load_questions()[:2])
    assert "## Q1" in text and "Hybrid rheometer" in text and "EQ19" not in text


# --- demo backup recording ---

def test_record_demo_saves_answers_and_keeps_failed_ones(tmp_path, monkeypatch):
    path = tmp_path / "demo.json"
    questions = run_eval.select_questions(run_eval.load_questions(), ["Q1", "Q2"], None)
    run_eval.record_demo(questions, ["structured", "naive"], path)
    saved = json.loads(path.read_text(encoding="utf-8"))["answers"]
    assert len(saved) == 4
    assert core.demo_answer("naive", questions[0]["question"], path)["instrument_ids"] == ["EQ17", "EQ18", "EQ19"]

    monkeypatch.setenv("MOCK_FAIL", "400:99")  # every call fails now: nothing is lost
    run_eval.record_demo(questions, ["structured"], path)
    assert json.loads(path.read_text(encoding="utf-8"))["answers"] == saved


def test_summary_has_cost_and_repair_rate():
    rows = [{"mode": "structured", "error": "", "repaired": "True", "cost_usd": "0.01", "json_ok": "True",
             **{c: "" for c in ("recall", "unacceptable_hits", "clarifying_ok", "seconds", "output_tokens",
                                "na_hits", "na_total", "accessory_hits", "accessory_total",
                                "contacts_ok", "contacts_total")}},
            {"mode": "structured", "error": "ServerError: 503", "repaired": "", "cost_usd": "0.02", "json_ok": ""}]
    summary = run_eval.summarize_group(rows)
    assert summary["repaired_rate"] == 1.0 and summary["total_cost_usd"] == pytest.approx(0.03)
