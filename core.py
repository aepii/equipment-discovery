"""Load the dataset, build prompts, call the LLM, parse JSON and check answers against the dataset."""

import hashlib
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Iterator

import openpyxl

from llm import complete_with_meta, stream_with_meta

DATA_PATH = Path(__file__).parent / "data" / "dataset.xlsx"
DEMO_ANSWERS_PATH = Path(__file__).parent / "data" / "demo_answers.json"
SHEET = "Equipment list"
FIELDS = ["instrument", "manufacturer", "model", "notes", "location", "contact"]


# --- dataset ---

@lru_cache(maxsize=1)
def load_equipment(path: Path = DATA_PATH) -> tuple[dict, ...]:
    """Read the equipment sheet. Each row gets a stable ID in row order: EQ01 ... EQ20."""
    sheet = openpyxl.load_workbook(path, read_only=True)[SHEET]
    rows = [r for r in sheet.iter_rows(min_row=2, values_only=True) if r and r[0]]
    equipment = []
    for i, row in enumerate(rows, start=1):
        item = {"id": f"EQ{i:02d}"}
        for field, value in zip(FIELDS, row):
            item[field] = str(value).strip() if value is not None else ""
        equipment.append(item)
    return tuple(equipment)


def equipment_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in load_equipment()}


def format_equipment_list(include_contacts: bool = False) -> str:
    """One line per instrument for the prompt.

    Structured mode leaves contacts out (code adds them from the ID); naive mode includes them
    so the model has to copy them itself, like an informal ChatGPT test.
    """
    lines = []
    for e in load_equipment():
        line = f"{e['id']} | {e['instrument']} | {e['manufacturer']} {e['model']} | {e['location']}"
        if include_contacts:
            line += f" | Contact: {e['contact']}"
        if e["notes"]:
            line += f" | Notes: {e['notes']}"
        lines.append(line)
    return "\n".join(lines)


def instrument_ids_in_text(text: str) -> list[str]:
    """IDs of instruments named in free text (naive answers): by ID, model, full name or abbreviation."""
    return [eq_id for eq_id, pattern in _instrument_patterns().items() if pattern.search(text)]


_RECOMMENDED_LINE = re.compile(r"^\W*recommended\W*:(.*)$", re.IGNORECASE | re.MULTILINE)


def recommended_line_ids(text: str) -> list[str] | None:
    """IDs on the naive answer's last "Recommended:" line, as written (may include unknown IDs).

    Returns None if the answer has no such line.
    """
    lines = _RECOMMENDED_LINE.findall(text)
    if not lines:
        return None
    ids = [m.upper() for m in re.findall(r"\bEQ\d+\b", lines[-1], re.IGNORECASE)]
    return list(dict.fromkeys(ids))


@lru_cache(maxsize=1)
def _instrument_patterns() -> dict[str, re.Pattern]:
    patterns = {}
    for e in load_equipment():
        names = [e["id"], e["model"], e["instrument"]]
        names += re.findall(r"\(([A-Z]{2,})\)", e["instrument"])  # e.g. TGA, DSC, ESEM
        alternatives = "|".join(re.escape(n) for n in names if n)
        patterns[e["id"]] = re.compile(rf"\b(?:{alternatives})\b", re.IGNORECASE)
    return patterns


# --- versions, so logged answers can be traced to the prompt, data and code that produced them ---

def _short_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:8]


def prompt_version(mode: str) -> str:
    prompts = {"structured": STRUCTURED_SYSTEM, "naive": NAIVE_SYSTEM + NAIVE_REQUEST}
    return _short_hash(prompts[mode].encode())


@lru_cache(maxsize=1)
def dataset_version() -> str:
    return _short_hash(DATA_PATH.read_bytes())


@lru_cache(maxsize=1)
def git_commit() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=DATA_PATH.parent,
                             capture_output=True, text=True, timeout=5)
        return out.stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


# --- prompts ---

STRUCTURED_SYSTEM = """You help researchers at UMKC find research equipment.
The researcher describes a scientific or measurement problem in plain language. They may not know
which technique or instrument they need.

Rules:
1. Work from the researcher's problem: decide what needs to be measured, then which techniques
   measure it, then which listed instruments can perform those techniques. Do not match on keywords
   in instrument names alone.
2. Recommend ONLY instruments from the equipment list, referenced by their ID (e.g. "EQ15").
   Never invent instruments or IDs.
3. The list does NOT record installed accessories, fixtures or configurations. Never assume they
   are installed. In "accessories_to_confirm", name the accessories the measurement typically needs
   (e.g. a suitable load cell and compression platens) so the researcher can confirm them.
4. If a well-suited technique is not available on any listed instrument (e.g. micro-CT), list it
   in "not_available" and say why it would be useful.
5. Point out limitations honestly (e.g. a method that is destructive or only works on certain samples).
6. If the question is too vague to answer, set "clarifying_question" and return no recommendations.
7. Do not give locations or contact names; the application adds them.

Return ONLY a JSON object with exactly this shape:
{
  "measurement_needs": ["what needs to be measured"],
  "recommendations": [
    {"instrument_id": "EQ17", "technique": "...", "why": "one or two sentences",
     "accessories_to_confirm": ["..."]}
  ],
  "not_available": [{"technique": "...", "why_useful": "..."}],
  "clarifying_question": null,
  "summary": "two or three sentences for the researcher"
}"""

NAIVE_SYSTEM = "You are a helpful assistant."

# Naive mode asks for location and contact in plain words, so its answers are comparable with
# structured mode (where code fills them in from the ID). The final "Recommended:" line only fixes the
# format, so the evaluation can tell recommended instruments from instruments merely mentioned
# (e.g. "TEM is destructive, so it is not suitable").
NAIVE_REQUEST = """For each instrument you suggest, include its location and contact.
End your answer with one line "Recommended: <IDs>" listing the IDs of the instruments you recommend
(e.g. "Recommended: EQ03, EQ12"), or "Recommended: none"."""


def build_user_prompt(question: str, mode: str = "structured") -> str:
    naive = mode == "naive"
    prompt = f"Equipment list:\n{format_equipment_list(include_contacts=naive)}\n\nQuestion: {question.strip()}"
    if naive:
        prompt += f"\n\n{NAIVE_REQUEST}"
    return prompt


# --- parsing and checking ---

def parse_json(text: str) -> dict:
    """Parse the model's JSON, tolerating ```json fences or text around the object."""
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            raise ValueError("The model did not return JSON.")
        data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("The model's JSON is not an object.")
    return data


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


def _list_of(parsed: dict, key: str) -> list:
    value = parsed.get(key)
    return value if isinstance(value, list) else []


def validate_structured(parsed: dict) -> list[str]:
    """Problems with the shape of a structured answer (empty list if none). Unknown instrument IDs are
    not a shape problem: check_recommendations removes them, with a notice."""
    problems = [f'"{key}" is missing' for key in ("recommendations", "summary") if key not in parsed]
    if "summary" in parsed and not isinstance(parsed["summary"], str):
        problems.append('"summary" must be a string')
    if parsed.get("clarifying_question") is not None and not isinstance(parsed["clarifying_question"], str):
        problems.append('"clarifying_question" must be a string or null')
    if "measurement_needs" in parsed and not _is_str_list(parsed["measurement_needs"]):
        problems.append('"measurement_needs" must be a list of strings')
    for key in ("recommendations", "not_available"):
        if key in parsed and not isinstance(parsed[key], list):
            problems.append(f'"{key}" must be a list')
    for i, rec in enumerate(_list_of(parsed, "recommendations"), start=1):
        if not isinstance(rec, dict):
            problems.append(f"recommendation {i} must be an object")
            continue
        for field in ("instrument_id", "technique", "why"):
            if not isinstance(rec.get(field), str):
                problems.append(f'recommendation {i}: "{field}" must be a string')
        if not _is_str_list(rec.get("accessories_to_confirm", [])):
            problems.append(f'recommendation {i}: "accessories_to_confirm" must be a list of strings')
    for i, item in enumerate(_list_of(parsed, "not_available"), start=1):
        if not (isinstance(item, dict) and isinstance(item.get("technique"), str)):
            problems.append(f'not_available {i} must be an object with a "technique" string')
    return problems


def structured_problems(raw: str) -> list[str]:
    """Why a raw structured answer can't be used as is: not JSON, or the wrong shape."""
    try:
        return validate_structured(parse_json(raw))
    except ValueError as exc:  # json.JSONDecodeError is a ValueError
        return [str(exc)]


def check_recommendations(recommendations: list) -> tuple[list[dict], list[str]]:
    """Keep only recommendations whose ID is in the dataset and fill in the dataset fields.

    Returns (checked recommendations, removed IDs).
    """
    known = equipment_by_id()
    checked, removed = [], []
    for rec in recommendations or []:
        if not isinstance(rec, dict):
            continue
        eq_id = str(rec.get("instrument_id", "")).strip().upper()
        if eq_id not in known:
            removed.append(eq_id or "(missing ID)")
            continue
        checked.append({
            **known[eq_id],
            "technique": rec.get("technique", ""),
            "why": rec.get("why", ""),
            "accessories_to_confirm": list(rec.get("accessories_to_confirm") or []),
        })
    return checked, removed


# --- read an answer (also used to re-score saved answers without calling the model) ---

def new_result(mode: str, raw: str = "") -> dict:
    return {"mode": mode, "raw": raw, "error": None, "usage": {}, "json_ok": None,
            "recommendations": [], "removed": [], "instrument_ids": [], "mentioned_ids": [],
            "ids_source": "", "not_available": [], "clarifying_question": None,
            "repaired": False, "first_raw": "", "schema_problems": [], "source": "live", "demo": None}


def read_structured(result: dict) -> dict:
    """Fill a structured result from its raw JSON: check IDs against the dataset, fill in fields."""
    try:
        parsed = parse_json(result["raw"])
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["json_ok"] = False if result["raw"] else None
        return result
    result["json_ok"] = True
    result["schema_problems"] = validate_structured(parsed)
    result["recommendations"], result["removed"] = check_recommendations(parsed.get("recommendations"))
    result["instrument_ids"] = [rec["id"] for rec in result["recommendations"]]
    result["ids_source"] = "json"
    result["measurement_needs"] = list(parsed.get("measurement_needs") or [])
    result["not_available"] = [n for n in parsed.get("not_available") or [] if isinstance(n, dict)]
    result["clarifying_question"] = parsed.get("clarifying_question")
    result["summary"] = parsed.get("summary", "")
    return result


def read_naive(result: dict) -> dict:
    """Find the instruments in a naive answer: from its "Recommended:" line if present, else by mention."""
    known = equipment_by_id()
    result["mentioned_ids"] = instrument_ids_in_text(result["raw"])
    listed = recommended_line_ids(result["raw"])
    if listed is None:
        result["instrument_ids"], result["ids_source"] = result["mentioned_ids"], "mentions"
    else:
        result["instrument_ids"] = [eq_id for eq_id in known if eq_id in listed]
        result["removed"] = [eq_id for eq_id in listed if eq_id not in known]
        result["ids_source"] = "recommended_line"
    return result


def read_answer(mode: str, raw: str) -> dict:
    result = new_result(mode, raw)
    return read_structured(result) if mode == "structured" else read_naive(result)


# --- run one question ---

REPAIR_REQUEST = """Your previous answer could not be used: {problems}.
Return the same answer as ONLY a JSON object with the shape given in the instructions.
Keep the content; fix only the format.

Previous answer:
{raw}"""


def _call(result: dict, system: str, user: str, json_mode: bool) -> None:
    """Call the model and store its text and usage (tokens, seconds, cost) on the result."""
    meta = complete_with_meta(system, user, json_mode=json_mode)
    result["raw"] = meta.pop("text")
    result["usage"] = meta


def add_usage(first: dict, second: dict) -> dict:
    """Usage of two calls together (an answer and its repair). A count unknown in either stays unknown."""
    total = dict(second)
    for key in ("input_tokens", "output_tokens", "thinking_tokens", "seconds", "cost_usd", "attempts"):
        a, b = first.get(key), second.get(key)
        total[key] = None if a is None or b is None else round(a + b, 6)
    total["fallback_used"] = bool(first.get("fallback_used") or second.get("fallback_used"))
    return total


def _repair(result: dict, question: str, problems: list[str]) -> None:
    """Ask the model once to fix the format of its answer. The first answer is kept in first_raw and
    result["repaired"] is set, so first-try JSON validity can still be measured."""
    first_raw, first_usage = result["raw"], result["usage"]
    user = build_user_prompt(question, "structured") + "\n\n" + REPAIR_REQUEST.format(
        problems="; ".join(problems), raw=first_raw)
    _call(result, STRUCTURED_SYSTEM, user, json_mode=True)
    result.update(repaired=True, first_raw=first_raw, usage=add_usage(first_usage, result["usage"]))


def run_structured(question: str, repair: bool = True) -> dict:
    """Structured mode: rules + JSON schema; code checks and fills in each recommendation.

    If the answer is not JSON of the right shape and repair is on, the model gets one chance to fix it.
    """
    result = new_result("structured")
    try:
        _call(result, STRUCTURED_SYSTEM, build_user_prompt(question, "structured"), json_mode=True)
    except Exception as exc:  # API errors are shown in the page, not raised
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    problems = structured_problems(result["raw"])
    if problems and repair:
        try:
            _repair(result, question, problems)
        except Exception:  # the repair call failed; read the first answer as it is
            pass
    return read_structured(result)


def run_naive(question: str) -> dict:
    """Naive mode: equipment list + question, no rules, free text answer."""
    result = new_result("naive")
    try:
        _call(result, NAIVE_SYSTEM, build_user_prompt(question, "naive"), json_mode=False)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    return read_naive(result)


def stream_naive(question: str, result: dict) -> Iterator[str]:
    """Naive mode, streamed: yields the text as it arrives. When done, result is filled like run_naive's."""
    result.update(new_result("naive"))
    chunks, meta = [], {}
    try:
        for chunk in stream_with_meta(NAIVE_SYSTEM, build_user_prompt(question, "naive"), meta):
            chunks.append(chunk)
            yield chunk
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["raw"], result["usage"] = "".join(chunks), meta
    read_naive(result)


# --- saved answers: a backup for the live demo when the model can't be reached ---

def normalize_question(question: str) -> str:
    """Same text up to case and spacing -> same key (for the answer cache and the demo backup)."""
    return " ".join(question.lower().split())


@lru_cache(maxsize=4)
def load_demo_answers(path: Path = DEMO_ANSWERS_PATH) -> dict:
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def demo_answer(mode: str, question: str, path: Path = DEMO_ANSWERS_PATH) -> dict | None:
    """The saved answer for this question and mode, read and checked like a live one, or None.

    The file holds raw model output, so unknown IDs are still removed and contact and location still
    come from the current dataset. result["demo"] says when and with which model it was recorded, and
    whether the prompt or dataset has changed since ("stale").
    """
    saved = load_demo_answers(path)
    key = normalize_question(question)
    entry = next((a for a in saved.get("answers", [])
                  if a["mode"] == mode and normalize_question(a["question"]) == key), None)
    if entry is None:
        return None
    result = read_answer(mode, entry["raw"])
    result["usage"] = dict(entry.get("usage") or {})
    result["source"] = "demo_backup"
    result["demo"] = {
        "recorded_at": entry.get("recorded_at", ""),
        "model": entry.get("model", ""),
        "stale": entry.get("prompt_version") != prompt_version(mode)
                 or entry.get("dataset_version") != dataset_version(),
    }
    return result
