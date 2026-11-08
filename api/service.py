"""Answering for the web interface, mirroring app.py: cache -> limits -> live call -> saved-answer
fallback -> logging. Plain Python (no FastAPI), so it can be tested directly.

State lives in this process's memory, like the Streamlit app's: the answer cache, today's spending, model
calls per browser session and the logged rows that feedback refers to.
"""

import threading
from collections import OrderedDict
from typing import Callable

import answer_graph
import core
import llm
import runtime
import store
from api import presentation

RUNNERS = {"structured": core.run_structured, "annotated": core.run_annotated, "naive": core.run_naive}
OFFLINE_MESSAGE = "Offline mode: only the example questions can be answered right now."
STAGES = ("reading", "matching", "checking", "done")

cache = runtime.AnswerCache()
budget = runtime.DailyBudget()
_lock = threading.Lock()
_session_calls: dict[str, int] = {}
_rows: OrderedDict = OrderedDict()  # answer_id -> logged row, for feedback
MAX_ROWS = 2000


def reset() -> None:
    """Forget all in-memory state (for tests)."""
    cache.clear()
    with _lock:
        _session_calls.clear()
        _rows.clear()


def live_available() -> bool:
    return not runtime.flag("DEMO_OFFLINE")


def cache_key(mode: str, question: str) -> tuple:
    """Same key as the Streamlit app: a new model, prompt or dataset never reuses an old answer."""
    return (mode, core.normalize_question(question), llm.provider(), llm.model_name(),
            core.prompt_version(mode), core.dataset_version())


def saved_or_error(mode: str, question: str, reason: str) -> dict:
    saved = core.demo_answer(mode, question)
    if saved:
        saved["notice"] = reason
        return saved
    result = core.new_result(mode)
    result["error"] = reason
    return result


def _reserve_call(session_id: str) -> str | None:
    """Count one model call for this session, or say why it is not allowed."""
    with _lock:
        calls = _session_calls.get(session_id, 0)
        blocked = runtime.limit_reason(calls, 1, budget.spent())
        if not blocked:
            _session_calls[session_id] = calls + 1
        return blocked


def _run(mode: str, question: str, on_stage: Callable[[str], None]) -> dict:
    if mode == "naive":
        result = RUNNERS[mode](question)
        on_stage("checking")
        return result
    return RUNNERS[mode](question, on_model_answer=lambda: on_stage("checking"))


def get_answer(mode: str, question: str, session_id: str, on_stage: Callable[[str], None]) -> dict:
    """One answer, from the cache, the model or the saved answers (in that order)."""
    if not live_available():
        return saved_or_error(mode, question, OFFLINE_MESSAGE)
    hit = cache.get(cache_key(mode, question))
    if hit:
        return {**hit, "source": "cache"}
    blocked = _reserve_call(session_id)
    if blocked:
        return saved_or_error(mode, question, blocked)
    on_stage("matching")
    result = _run(mode, question, on_stage)
    budget.add((result.get("usage") or {}).get("cost_usd") or 0.0)
    if not result["error"]:
        cache.put(cache_key(mode, question), result)
    elif runtime.flag("DEMO_BACKUP", default=True) and core.demo_answer(mode, question):
        result = saved_or_error(mode, question, result["error"])
    return result


def log_answer(question: str, result: dict, session_id: str, extra: dict) -> dict:
    row = store.answer_row(question, result, source="web", session_id=session_id,
                           from_example=question in {e["question"] for e in presentation.EXAMPLES})
    row.update(extra)  # added keys come after the existing columns
    store.save("answers", row)
    with _lock:
        _rows[row["answer_id"]] = row
        while len(_rows) > MAX_ROWS:
            _rows.popitem(last=False)
    return row


def standalone_question(question: str, previous: list[str]) -> str:
    """A follow-up rewritten to stand on its own; the first question (or offline mode) goes straight through."""
    if not previous or not live_available():
        return question
    return core.rewrite_followup(question, previous)


def ask(question: str, mode: str, session_id: str, conversation_id: str = "", previous: list[str] | None = None,
        on_stage: Callable[[str], None] = lambda stage: None) -> dict:
    """Answer and log one question; return the payload the interface receives.

    previous: the earlier standalone questions of this conversation. A follow-up is rewritten to stand on
    its own, and the rewritten question is what gets answered (and shown as "Answering: ...").
    """
    previous = previous or []
    on_stage("reading")
    answered = standalone_question(question, previous)
    result = get_answer(mode, answered, session_id, on_stage)
    if result.get("error"):
        print(f"Answer error ({mode}): {result['error']}")
    row = log_answer(answered, result, session_id, {
        "conversation_id": conversation_id, "turn": len(previous) + 1,
        "original_question": question if answered != question else ""})
    on_stage("done")
    return {
        "answer_id": row["answer_id"],
        "question": question,
        "standalone_question": answered,
        "rewritten": answered != question,
        "source": presentation.source_label(result),
        "result": presentation.sanitize(result),
        "graph_dot": answer_graph.build_dot(result) or None,
    }


def feedback(answer_id: str, overall: str, comment: str, instrument_ratings: dict[str, str]) -> bool:
    with _lock:
        row = _rows.get(answer_id)
    if row is None:
        return False
    known = core.equipment_by_id()
    ratings = {eq_id: rating for eq_id, rating in instrument_ratings.items() if eq_id in known}
    store.save("feedback", store.feedback_row(row, "", overall, comment.strip(), ratings, [], "", ""))
    return True
