"""Log answers and feedback for evaluation: to a Google Sheet when configured, else to results/log.jsonl.

Config (env / Streamlit secrets): GOOGLE_SHEET_ID, plus either GOOGLE_SERVICE_ACCOUNT_JSON (the key
file's contents) or GOOGLE_SERVICE_ACCOUNT_FILE (a path to the key file). The sheet must be shared with
the service account's email as Editor. Tabs "answers" and "feedback" are created on first use.
"""

import json
import os
import threading
import uuid
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path

import core
import llm

LOCAL_LOG = Path(__file__).parent / "results" / "log.jsonl"
CELL_LIMIT = 45000  # Google Sheets allows 50,000 characters per cell

ANSWER_COLUMNS = [
    "answer_id", "timestamp", "source", "session_id", "rater", "from_example",
    "mode", "provider", "model", "prompt_version", "dataset_version", "git_commit",
    "seconds", "input_tokens", "output_tokens", "thinking_tokens",
    "json_ok", "clarifying_question", "instrument_ids", "removed_ids", "not_available", "error",
    "question", "raw_output",
]
FEEDBACK_COLUMNS = [
    "timestamp", "answer_id", "session_id", "rater", "mode", "question",
    "overall", "comment", "instrument_ratings", "missing_ids", "not_available_ok", "not_available_comment",
]
TABS = {"answers": ANSWER_COLUMNS, "feedback": FEEDBACK_COLUMNS}

_lock = threading.Lock()
_headers: dict[str, list[str]] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --- rows ---

def answer_row(question: str, result: dict, source: str = "app", session_id: str = "",
               rater: str = "", from_example: bool = False) -> dict:
    """One row per model answer, with everything needed to compare versions later."""
    usage = result.get("usage") or {}
    return {
        "answer_id": uuid.uuid4().hex[:12],
        "timestamp": _now(),
        "source": source,
        "session_id": session_id,
        "rater": rater,
        "from_example": from_example,
        "mode": result["mode"],
        "provider": llm.provider(),
        "model": llm.model_name(),
        "prompt_version": core.prompt_version(result["mode"]),
        "dataset_version": core.dataset_version(),
        "git_commit": core.git_commit(),
        "seconds": usage.get("seconds"),
        "input_tokens": usage.get("input_tokens"),
        "output_tokens": usage.get("output_tokens"),
        "thinking_tokens": usage.get("thinking_tokens"),
        "json_ok": result.get("json_ok"),
        "clarifying_question": result.get("clarifying_question") or "",
        "instrument_ids": " ".join(result.get("instrument_ids", [])),
        "removed_ids": " ".join(result.get("removed", [])),
        "not_available": "; ".join(n.get("technique", "") for n in result.get("not_available", [])),
        "error": result.get("error") or "",
        "question": question,
        "raw_output": result.get("raw", ""),
    }


def feedback_row(answer: dict, rater: str, overall: str, comment: str, instrument_ratings: dict[str, str],
                 missing_ids: list[str], not_available_ok: str, not_available_comment: str) -> dict:
    """One row per feedback submission. Mode and question are repeated so the tab reads on its own."""
    return {
        "timestamp": _now(),
        "answer_id": answer["answer_id"],
        "session_id": answer["session_id"],
        "rater": rater,
        "mode": answer["mode"],
        "question": answer["question"],
        "overall": overall,
        "comment": comment,
        "instrument_ratings": "; ".join(f"{eq_id} {rating}" for eq_id, rating in instrument_ratings.items()),
        "missing_ids": " ".join(missing_ids),
        "not_available_ok": not_available_ok,
        "not_available_comment": not_available_comment,
    }


# --- saving ---

def sheet_configured() -> bool:
    has_key = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") or os.getenv("GOOGLE_SERVICE_ACCOUNT_FILE")
    return bool(os.getenv("GOOGLE_SHEET_ID") and has_key)


def destination() -> str:
    return "Google Sheet" if sheet_configured() else f"local file ({LOCAL_LOG.parent.name}/{LOCAL_LOG.name})"


def save(tab: str, row: dict, background: bool = True) -> None:
    """Append a row to a tab. In the app this runs in a background thread so nobody waits on it."""
    if background:
        threading.Thread(target=_save, args=(tab, row), daemon=True).start()
    else:
        _save(tab, row)


def _save(tab: str, row: dict) -> None:
    try:
        with _lock:
            if sheet_configured():
                _append_to_sheet(tab, row)
            else:
                _append_local(tab, row)
    except Exception as exc:  # logging must never break the app; the error shows in the server log
        print(f"Could not save a row to '{tab}': {type(exc).__name__}: {exc}")


def _append_local(tab: str, row: dict) -> None:
    LOCAL_LOG.parent.mkdir(exist_ok=True)
    with LOCAL_LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"tab": tab, **row}, ensure_ascii=False) + "\n")


@lru_cache(maxsize=1)
def _spreadsheet():
    import gspread

    info = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON")
    if info:
        client = gspread.service_account_from_dict(json.loads(info))
    else:
        client = gspread.service_account(filename=os.environ["GOOGLE_SERVICE_ACCOUNT_FILE"])
    return client.open_by_key(os.environ["GOOGLE_SHEET_ID"])


@lru_cache(maxsize=None)
def _worksheet(tab: str):
    import gspread

    book = _spreadsheet()
    try:
        return book.worksheet(tab)
    except gspread.WorksheetNotFound:
        return book.add_worksheet(title=tab, rows=1000, cols=len(TABS[tab]))


def _append_to_sheet(tab: str, row: dict) -> None:
    """Append in the sheet's own column order; new columns are added to the header, never reordered."""
    sheet = _worksheet(tab)
    if tab not in _headers:
        _headers[tab] = sheet.row_values(1)
    header = _headers[tab]
    new_columns = [c for c in row if c not in header]
    if new_columns:
        header += new_columns
        if len(header) > sheet.col_count:
            sheet.add_cols(len(header) - sheet.col_count)
        sheet.update(range_name="A1", values=[header])
    values = [_cell(row.get(column)) for column in header]
    # RAW: a question starting with "=" is stored as text, never run as a formula.
    sheet.append_row(values, value_input_option="RAW", table_range="A1")


def _cell(value):
    if value is None:
        return ""
    if isinstance(value, str) and len(value) > CELL_LIMIT:
        return value[:CELL_LIMIT] + " [truncated]"
    return value
