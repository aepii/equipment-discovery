"""JSON validation and repair, streamed naive answers, the demo backup, the answer cache and limits."""

import json

import pytest

import core
import llm
import runtime

GOOD = {"measurement_needs": ["x"], "recommendations": [
    {"instrument_id": "EQ15", "technique": "compression", "why": "w", "accessories_to_confirm": ["platens"]}],
    "not_available": [{"technique": "micro-CT", "why_useful": "u"}], "clarifying_question": None, "summary": "s"}


# --- validation ---

def test_valid_answer_has_no_problems():
    assert core.validate_structured(GOOD) == []
    assert core.validate_structured({"recommendations": [], "summary": "s"}) == []


def test_unknown_ids_are_not_a_shape_problem():
    answer = {**GOOD, "recommendations": [{**GOOD["recommendations"][0], "instrument_id": "EQ99"}]}
    assert core.validate_structured(answer) == []


@pytest.mark.parametrize("change, problem", [
    ({"summary": None}, '"summary" must be a string'),
    ({"recommendations": {"EQ15": "x"}}, '"recommendations" must be a list'),
    ({"recommendations": ["EQ15"]}, "recommendation 1 must be an object"),
    ({"recommendations": [{"instrument_id": 15, "technique": "t", "why": "w"}]}, '"instrument_id" must be a string'),
    ({"recommendations": [{"instrument_id": "EQ15", "technique": "t", "why": "w", "accessories_to_confirm": "x"}]},
     '"accessories_to_confirm" must be a list of strings'),
    ({"not_available": ["micro-CT"]}, "not_available 1"),
    ({"clarifying_question": ["?"]}, '"clarifying_question"'),
])
def test_shape_problems_are_found(change, problem):
    assert any(problem in p for p in core.validate_structured({**GOOD, **change}))


def test_missing_required_keys():
    assert core.validate_structured({}) == ['"recommendations" is missing', '"summary" is missing']


def test_structured_problems_for_text_that_is_not_json():
    assert core.structured_problems("Sorry, I can't help.") == ["The model did not return JSON."]
    assert core.structured_problems(json.dumps(GOOD)) == []


# --- repair ---

def fake_model(monkeypatch, answers: list[str]) -> list[str]:
    """Replace the model with one that returns these texts in turn; returns the user prompts it got."""
    prompts = []

    def complete_with_meta(system, user, json_mode=False):
        prompts.append(user)
        return {"text": answers[len(prompts) - 1], "input_tokens": 100, "output_tokens": 10,
                "thinking_tokens": None, "seconds": 1.0, "cost_usd": 0.01, "attempts": 1,
                "model_used": "m", "fallback_used": False}

    monkeypatch.setattr(core, "complete_with_meta", complete_with_meta)
    return prompts


def test_broken_json_is_repaired_once(monkeypatch):
    prompts = fake_model(monkeypatch, ['{"recommendations": [', json.dumps(GOOD)])
    result = core.run_structured("q")
    assert len(prompts) == 2 and "could not be used" in prompts[1] and '{"recommendations": [' in prompts[1]
    assert result["repaired"] and result["first_raw"] == '{"recommendations": ['
    assert result["error"] is None and result["instrument_ids"] == ["EQ15"]
    assert result["usage"]["input_tokens"] == 200 and result["usage"]["cost_usd"] == pytest.approx(0.02)
    assert result["usage"]["attempts"] == 2


def test_repair_that_fails_again_keeps_the_error(monkeypatch):
    fake_model(monkeypatch, ["not json", "still not json"])
    result = core.run_structured("q")
    assert result["repaired"] and result["json_ok"] is False and result["error"]


def test_no_repair_when_turned_off_or_not_needed(monkeypatch):
    prompts = fake_model(monkeypatch, ["not json"])
    assert not core.run_structured("q", repair=False)["repaired"] and len(prompts) == 1
    prompts = fake_model(monkeypatch, [json.dumps(GOOD)])
    assert not core.run_structured("q")["repaired"] and len(prompts) == 1


def test_add_usage_keeps_unknown_counts_unknown():
    total = core.add_usage({"input_tokens": 1, "output_tokens": None}, {"input_tokens": 2, "output_tokens": 5})
    assert total["input_tokens"] == 3 and total["output_tokens"] is None


# --- streamed naive answers ---

def test_stream_naive_matches_run_naive():
    result = {}
    text = "".join(core.stream_naive("My polymer remains unexpectedly viscous.", result))
    plain = core.run_naive("My polymer remains unexpectedly viscous.")
    assert text == plain["raw"] == result["raw"]
    assert result["instrument_ids"] == plain["instrument_ids"] == ["EQ17", "EQ18", "EQ19"]


def test_stream_naive_error_is_kept_not_raised(monkeypatch):
    monkeypatch.setenv("MOCK_FAIL", "400:1")
    result = {}
    assert list(core.stream_naive("viscous", result)) == []
    assert "400" in result["error"] and result["instrument_ids"] == []


# --- demo backup ---

def write_demo(tmp_path, **entry_changes):
    path = tmp_path / "demo.json"
    entry = {"mode": "structured", "question": "Is  the Instron there?", "raw": json.dumps(
        {**GOOD, "recommendations": GOOD["recommendations"] + [{"instrument_id": "EQ99", "technique": "t", "why": "w"}]}),
        "usage": {"output_tokens": 10}, "model": "gemini-x", "recorded_at": "2026-11-01T10:00:00+00:00",
        "prompt_version": core.prompt_version("structured"), "dataset_version": core.dataset_version(),
        **entry_changes}
    path.write_text(json.dumps({"answers": [entry]}), encoding="utf-8")
    core.load_demo_answers.cache_clear()
    return path


def test_demo_answer_is_checked_like_a_live_one(tmp_path):
    path = write_demo(tmp_path)
    result = core.demo_answer("structured", "is the instron THERE?", path)
    assert result["source"] == "demo_backup" and result["instrument_ids"] == ["EQ15"]
    assert result["removed"] == ["EQ99"]
    assert result["recommendations"][0]["contact"] == core.equipment_by_id()["EQ15"]["contact"]
    assert result["demo"] == {"recorded_at": "2026-11-01T10:00:00+00:00", "model": "gemini-x", "stale": False}


def test_demo_answer_missing_or_stale(tmp_path):
    path = write_demo(tmp_path, prompt_version="old")
    assert core.demo_answer("naive", "Is the Instron there?", path) is None
    assert core.demo_answer("structured", "Something else", path) is None
    assert core.demo_answer("structured", "Is the Instron there?", path)["demo"]["stale"]


def test_no_demo_file_means_no_backup(tmp_path):
    assert core.demo_answer("structured", "q", tmp_path / "missing.json") is None


# --- answer cache ---

def test_cache_returns_copies_and_drops_oldest():
    cache = runtime.AnswerCache(max_entries=2)
    cache.put("a", {"ids": ["EQ15"]})
    got = cache.get("a")
    got["ids"].append("EQ99")
    assert cache.get("a") == {"ids": ["EQ15"]}
    cache.put("b", {})
    cache.get("a")  # a is now the most recently used
    cache.put("c", {})
    assert cache.get("b") is None and cache.get("a") is not None and len(cache) == 2


def test_normalize_question():
    assert core.normalize_question("  Hello\n  World ") == core.normalize_question("hello world")


# --- limits ---

def test_session_call_limit(monkeypatch):
    monkeypatch.setenv("MAX_CALLS_PER_SESSION", "3")
    assert runtime.limit_reason(1, 2, 0.0) is None
    assert "limit of 3 model calls" in runtime.limit_reason(2, 2, 0.0)


def test_daily_budget(monkeypatch):
    assert runtime.limit_reason(100, 2, 99.0) is None  # no limits set
    monkeypatch.setenv("DAILY_BUDGET_USD", "2")
    budget = runtime.DailyBudget()
    budget.add(1.5)
    budget.add(None)
    assert budget.spent() == 1.5 and runtime.limit_reason(0, 1, budget.spent()) is None
    budget.add(0.5)
    assert "budget" in runtime.limit_reason(0, 1, budget.spent())


def test_flag_defaults(monkeypatch):
    assert runtime.flag("DEMO_BACKUP", default=True)
    monkeypatch.setenv("DEMO_BACKUP", "0")
    assert not runtime.flag("DEMO_BACKUP", default=True)
    monkeypatch.setenv("DEMO_OFFLINE", "yes")
    assert runtime.flag("DEMO_OFFLINE")


def test_mock_delay_is_used(monkeypatch):
    monkeypatch.setenv("MOCK_DELAY_S", "0.2")
    assert llm.complete_with_meta("s", "Question: viscous")["seconds"] >= 0.2
