"""Load the dataset, build prompts, call the LLM, parse JSON and check answers against the dataset."""

import hashlib
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import openpyxl

from llm import complete_with_meta

DATA_PATH = Path(__file__).parent / "data" / "dataset.xlsx"
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
# structured mode (where code fills them in from the ID).
NAIVE_REQUEST = "For each instrument you suggest, include its location and contact."


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


# --- run one question ---

def _call(result: dict, system: str, question: str, json_mode: bool) -> None:
    """Call the model and store its text and usage (tokens, seconds) on the result."""
    user = build_user_prompt(question, result["mode"])
    meta = complete_with_meta(system, user, json_mode=json_mode)
    result["raw"] = meta.pop("text")
    result["usage"] = meta


def run_structured(question: str) -> dict:
    """Structured mode: rules + JSON schema; code checks and fills in each recommendation."""
    result = {"mode": "structured", "raw": "", "error": None, "usage": {}, "json_ok": None,
              "recommendations": [], "removed": [], "instrument_ids": []}
    try:
        _call(result, STRUCTURED_SYSTEM, question, json_mode=True)
        parsed = parse_json(result["raw"])
    except Exception as exc:  # API or parsing errors are shown in the page, not raised
        result["error"] = f"{type(exc).__name__}: {exc}"
        result["json_ok"] = False if result["raw"] else None
        return result
    result["json_ok"] = True
    result["recommendations"], result["removed"] = check_recommendations(parsed.get("recommendations"))
    result["instrument_ids"] = [rec["id"] for rec in result["recommendations"]]
    result["measurement_needs"] = list(parsed.get("measurement_needs") or [])
    result["not_available"] = [n for n in parsed.get("not_available") or [] if isinstance(n, dict)]
    result["clarifying_question"] = parsed.get("clarifying_question")
    result["summary"] = parsed.get("summary", "")
    return result


def run_naive(question: str) -> dict:
    """Naive mode: equipment list + question, no rules, free text answer."""
    result = {"mode": "naive", "raw": "", "error": None, "usage": {}, "instrument_ids": []}
    try:
        _call(result, NAIVE_SYSTEM, question, json_mode=False)
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {exc}"
    result["instrument_ids"] = instrument_ids_in_text(result["raw"])
    return result
