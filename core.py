"""Load the dataset, build prompts, call the LLM, parse JSON and check answers against the dataset."""

import hashlib
import json
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Callable, Iterator

import openpyxl

import knowledge
from llm import complete, complete_with_meta, stream_with_meta

DATA_PATH = Path(__file__).parent / "data" / "dataset.xlsx"
TEST_INSTRUMENTS_PATH = Path(__file__).parent / "data" / "test_instruments.json"
DEMO_ANSWERS_PATH = Path(__file__).parent / "data" / "demo_answers.json"
SHEET = "Equipment list"
FIELDS = ["instrument", "manufacturer", "model", "notes", "location", "contact"]
# Modes whose answer is JSON in the structured schema. "annotated" = structured + instrument annotations.
JSON_MODES = ("structured", "annotated")
# A recommendation's role: "primary" = the instrument can itself perform the measurement that answers
# the question; "supplementary" = useful context, preparation or a partial view only.
ROLES = ("primary", "supplementary")


# --- dataset ---

@lru_cache(maxsize=1)
def load_equipment(path: Path = DATA_PATH, test_path: Path = TEST_INSTRUMENTS_PATH) -> tuple[dict, ...]:
    """The equipment sheet (stable IDs in row order: EQ01 ... EQ20), then the fictional test instruments
    from test_path (EQ21, EQ22, ... in file order).

    Every instrument has "installed_accessories" (a list; empty for the dataset rows, which don't record
    them) and "fictional_test_instrument".
    """
    sheet = openpyxl.load_workbook(path, read_only=True)[SHEET]
    rows = [r for r in sheet.iter_rows(min_row=2, values_only=True) if r and r[0]]
    equipment = []
    for i, row in enumerate(rows, start=1):
        item = {"id": f"EQ{i:02d}"}
        for field, value in zip(FIELDS, row):
            item[field] = str(value).strip() if value is not None else ""
        equipment.append({**item, "installed_accessories": [], "fictional_test_instrument": False})
    extras = json.loads(test_path.read_text(encoding="utf-8"))["instruments"] if test_path.exists() else []
    for extra in extras:
        equipment.append({"id": f"EQ{len(equipment) + 1:02d}",
                          **{field: str(extra.get(field) or "").strip() for field in FIELDS},
                          "installed_accessories": list(extra.get("installed_accessories", [])),
                          "fictional_test_instrument": bool(extra.get("fictional_test_instrument"))})
    return tuple(equipment)


def equipment_by_id() -> dict[str, dict]:
    return {item["id"]: item for item in load_equipment()}


def prompt_notes(item: dict) -> str:
    """The notes the model sees. A fictional test instrument's notes only say that it is fictional, which
    would let the model treat it differently from the real ones, so they are left out of prompts."""
    return "" if item.get("fictional_test_instrument") else item["notes"]


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
        if e["installed_accessories"]:
            line += f" | Installed accessories: {'; '.join(e['installed_accessories'])}"
        if prompt_notes(e):
            line += f" | Notes: {prompt_notes(e)}"
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
    """A name shared with an earlier instrument stays with that one (e.g. "Hybrid rheometer" is EQ19;
    the test instrument EQ21 has the same name), so the later one is found by its ID or model only."""
    patterns, claimed = {}, set()
    for e in load_equipment():
        names = [e["model"], e["instrument"]]
        names += re.findall(r"\(([A-Z]{2,})\)", e["instrument"])  # e.g. TGA, DSC, ESEM
        names = [e["id"]] + [n for n in names if n and n.lower() not in claimed]
        claimed.update(n.lower() for n in names)
        alternatives = "|".join(re.escape(n) for n in names if n)
        patterns[e["id"]] = re.compile(rf"\b(?:{alternatives})\b", re.IGNORECASE)
    return patterns


# --- versions, so logged answers can be traced to the prompt, data and code that produced them ---

def _short_hash(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()[:8]


def prompt_version(mode: str) -> str:
    """Annotated mode's version also changes when the knowledge files change (they are part of its prompt)."""
    prompts = {"structured": STRUCTURED_SYSTEM, "naive": NAIVE_SYSTEM + NAIVE_REQUEST,
               "annotated": ANNOTATED_SYSTEM + knowledge.knowledge_version()}
    return _short_hash(prompts[mode].encode())


@lru_cache(maxsize=1)
def dataset_version() -> str:
    test_instruments = TEST_INSTRUMENTS_PATH.read_bytes() if TEST_INSTRUMENTS_PATH.exists() else b""
    return _short_hash(DATA_PATH.read_bytes() + test_instruments)


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
3. The list records installed accessories only where an instrument says "Installed accessories: ...";
   those count as confirmed. Never assume any other accessory, fixture or configuration is installed.
   In "accessories_to_confirm", name the other accessories the measurement typically needs (e.g. a
   suitable load cell and compression platens) so the researcher can confirm them. Prefer an
   instrument whose installed configuration fits the measurement over an identical model whose
   configuration is unknown.
4. If a well-suited technique is not available on any listed instrument (e.g. micro-CT), list it
   in "not_available" and say why it would be useful.
5. Point out limitations honestly (e.g. a method that is destructive or only works on certain samples).
6. If the question is too vague to answer, set "clarifying_question" and return no recommendations.
7. Do not give locations or contact names; the application adds them.
8. Give every recommendation a "role":
   - "primary": this instrument can itself perform the measurement that answers the question.
   - "supplementary": it gives useful context, sample preparation or a partial or qualitative view,
     but it cannot meet the stated objective on its own.
   Never mark an instrument primary just because it is the closest available option. Set
   "objective_met" to true only if at least one recommendation is primary. If none is primary, the
   summary must first say plainly that no listed instrument can perform the requested measurement,
   name the right technique under "not_available", and only then mention supplementary instruments.

Return ONLY a JSON object with exactly this shape:
{
  "measurement_needs": ["what needs to be measured"],
  "objective_met": true,
  "recommendations": [
    {"instrument_id": "EQ17", "role": "primary", "technique": "...", "why": "one or two sentences",
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


# Annotated mode: the structured rules, plus draft notes per instrument from the knowledge layer and a
# reference list of techniques no listed instrument performs. The model also names technique IDs, so
# code can check each recommendation against the instrument's notes.
ANNOTATED_SYSTEM = STRUCTURED_SYSTEM.split("\n\nReturn ONLY")[0] + """
9. Each instrument comes with draft notes: its typical techniques (with IDs such as
   "compression_testing"), what they measure, whether they are destructive, typical samples,
   limitations and accessories to confirm. The notes describe what this TYPE of instrument typically
   does and are not yet reviewed. Use them, but do not treat accessories as installed unless the list
   says "Installed accessories" or "Installed per the dataset". Techniques marked "only with optional hardware" need confirming.
10. Instruments whose techniques measure nothing (printers, mills, sectioning) only make or prepare
   samples. Recommend them only when the researcher needs that step.
11. "Techniques not available on any listed instrument" supports rule 4. Whenever one of them is the
   standard method for the problem, or would answer it better than the listed instruments, list it in
   "not_available" with its ID, even if you also recommend a partial option. You may also name a
   technique that is not on the list, with "technique_id": null.
12. For each recommendation give "property_id": the ID (in square brackets in the notes) of the main
   property this technique would measure for the question, or null if none fits.

Return ONLY a JSON object with exactly this shape:
{
  "measurement_needs": ["what needs to be measured"],
  "objective_met": true,
  "recommendations": [
    {"instrument_id": "EQ17", "role": "primary", "technique_id": "thermogravimetric_analysis",
     "property_id": "thermal_stability", "technique": "...",
     "why": "one or two sentences", "accessories_to_confirm": ["..."]}
  ],
  "not_available": [{"technique_id": "micro_computed_tomography", "technique": "...", "why_useful": "..."}],
  "clarifying_question": null,
  "summary": "two or three sentences for the researcher"
}"""

SYSTEMS = {"structured": STRUCTURED_SYSTEM, "annotated": ANNOTATED_SYSTEM}


def build_user_prompt(question: str, mode: str = "structured") -> str:
    if mode == "annotated":
        return (f"Equipment list with draft notes:\n\n{knowledge.format_annotated_equipment(load_equipment())}"
                f"\n\nTechniques not available on any listed instrument:\n{knowledge.format_unavailable_techniques()}"
                f"\n\nQuestion: {question.strip()}")
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
    if parsed.get("objective_met") is not None and not isinstance(parsed["objective_met"], bool):
        problems.append('"objective_met" must be true or false')
    for i, rec in enumerate(_list_of(parsed, "recommendations"), start=1):
        if not isinstance(rec, dict):
            problems.append(f"recommendation {i} must be an object")
            continue
        for field in ("instrument_id", "technique", "why"):
            if not isinstance(rec.get(field), str):
                problems.append(f'recommendation {i}: "{field}" must be a string')
        if rec.get("role") not in ROLES:
            problems.append(f'recommendation {i}: "role" must be "primary" or "supplementary"')
        if not _is_str_list(rec.get("accessories_to_confirm", [])):
            problems.append(f'recommendation {i}: "accessories_to_confirm" must be a list of strings')
        for field in ("technique_id", "property_id"):
            if not isinstance(rec.get(field), (str, type(None))):
                problems.append(f'recommendation {i}: "{field}" must be a string or null')
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

    A missing or invalid role counts as primary (validate_structured reports it as a schema problem).
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
        role = rec.get("role")
        checked.append({
            **known[eq_id],
            "role": role if role in ROLES else "primary",
            "technique": rec.get("technique", ""),
            "why": rec.get("why", ""),
            "accessories_to_confirm": list(rec.get("accessories_to_confirm") or []),
        })
    return checked, removed


def check_against_annotations(rec: dict, technique_id) -> dict:
    """Annotated mode: compare a checked recommendation with the instrument's notes.

    Adds technique_id, the technique's destructiveness, the notes' review status and cautions (e.g. a
    technique the notes don't list for this instrument). If the model named no accessories, the notes'
    accessories to confirm for that technique are filled in.
    """
    tid = str(technique_id or "").strip()
    own = knowledge.techniques_of(rec["id"])
    rec.update(technique_id=tid, destructive="", destructive_level="", cautions=[],
               notes_status=knowledge.review_status(rec["id"]))
    if not tid:
        rec["cautions"].append("No technique ID given, so this was not checked against the instrument notes.")
    elif tid not in knowledge.techniques():
        rec["cautions"].append(f"Unknown technique ID '{tid}'; not checked against the instrument notes.")
    elif tid not in own:
        rec["cautions"].append(f"{knowledge.technique_name(tid)} is not among this instrument's typical "
                               "techniques in the instrument notes; confirm with the contact that it can be done.")
    else:
        technique = knowledge.techniques()[tid]
        rec["destructive_level"] = technique["destructive"]
        rec["destructive"] = technique["destructive"].replace("_", " ") + (
            f" ({technique['destructive_note']})" if technique.get("destructive_note") else "")
        if own[tid]["confidence"] == "low":
            rec["cautions"].append("This technique needs optional hardware that the dataset does not list.")
        if not rec["accessories_to_confirm"]:
            rec["accessories_to_confirm"] = knowledge.accessories_for(rec["id"], tid)
    return rec


PREPARING_KINDS = ("sample_preparation", "fabrication")  # measure nothing; only useful before another step


def _either(items: list[str]) -> str:
    """"A", "A or B", "A, B or C"."""
    return " or ".join([", ".join(items[:-1]), items[-1]]) if len(items) > 1 else "".join(items)


def _who(eq_ids: list[str]) -> str:
    """"Ultramicrotome (EQ16), Jamie Collins (SOP)" for up to two instruments, from the dataset."""
    known = equipment_by_id()
    return "; ".join(f"{known[i]['instrument']} ({i}), {known[i]['contact']}" for i in eq_ids[:2])


def _step_line(step: dict) -> str:
    where = {"available": _who(step["instruments"]),
             "bench_step": "a lab bench step, no instrument needed",
             "missing": "not available in the dataset"}[step["status"]]
    need = "May need" if step["conditional"] else "Needs"
    when = f" ({step['when']})" if step["when"] and step["conditional"] else ""
    return f"{need} {step['name']} first{when}: {where}."


def check_workflow(rec: dict, recommendations: list[dict]) -> dict:
    """Annotated mode, after check_against_annotations: the steps around the recommended technique.

    Adds "workflow" (lines for the card: prerequisites with instrument and contact; for preparation and
    fabrication, what the result is used for) and "dead_end" (a reason, or ""). A dead end is a
    preparation or fabrication step whose follow-up is not available or not among the recommended
    instruments, or a step whose unconditional prerequisite is missing. A dead end is never primary.
    """
    tid = rec.get("technique_id", "")
    rec.update(workflow=[], dead_end="")
    if tid not in knowledge.techniques_of(rec["id"]):
        return rec
    flow = knowledge.workflow_for(tid)
    rec["workflow"] = [_step_line(step) for step in flow["requires"]]
    blocking = [s for s in flow["requires"] if s["status"] == "missing" and not s["conditional"]]
    if blocking:
        rec["dead_end"] = (f"Dead end: {blocking[0]['name']} must come first, "
                           "which is not available in the dataset.")
    elif knowledge.techniques()[tid]["kind"] in PREPARING_KINDS and flow["leads_to"]:
        others = {r["id"] for r in recommendations if r is not rec}
        followed = [s for s in flow["leads_to"] if set(s["instruments"]) & others]
        missing = [s["name"] for s in flow["leads_to"] if s["status"] == "missing"]
        available = [f"{s['name']} ({', '.join(s['instruments'])})" for s in flow["leads_to"] if s["instruments"]]
        rec["workflow"].append("Leads to: " + "; ".join(available + [f"{m} (not available)" for m in missing]) + ".")
        if not followed:
            rec["dead_end"] = (f"Dead end: this step is only useful if {_either(missing)} follows, which is not "
                               "available in the dataset." if missing else
                               f"Dead end here: this step is only useful if {_either(available)} follows, "
                               "and none of those instruments is recommended in this answer.")
    if rec["dead_end"]:
        rec["role"] = "supplementary"
    return rec


FIT_LEVELS = ("high", "medium", "low")


def _listing(items: list[str], limit: int = 3) -> str:
    more = f" and {len(items) - limit} more" if len(items) > limit else ""
    return ", ".join(items[:limit]) + more


def assign_fit(rec: dict) -> dict:
    """Annotated mode: the fit level (high / medium / low) and a one-sentence reason, from facts in the
    knowledge files and the dataset, never from the model. Runs after check_against_annotations (and the
    workflow check). The first rule that matches wins."""
    def fit(level: str, reason: str) -> dict:
        rec.update(fit=level, fit_reason=reason)
        return rec

    tid, eq_id = rec.get("technique_id", ""), rec["id"]
    own = knowledge.techniques_of(eq_id)
    if rec.get("dead_end"):  # first: a dead end is also made supplementary, but this reason is more specific
        return fit("low", rec["dead_end"])
    if rec.get("role") == "supplementary":
        return fit("low", "Complementary only: cannot perform the main measurement.")
    if not tid:
        return fit("low", "No technique given, so the fit could not be checked against the instrument notes.")
    if tid not in knowledge.techniques():
        return fit("low", f"Unknown technique '{tid}': not checked against the instrument notes.")
    name = knowledge.technique_name(tid)
    if tid not in own:
        return fit("low", f"{name} is not among this instrument's typical techniques.")
    if own[tid]["confidence"] == "low":
        hardware = _listing(knowledge.accessories_for(eq_id, tid)) or "extra hardware"
        return fit("low", f"Needs optional hardware ({hardware}) not listed in the dataset.")
    technique = knowledge.techniques()[tid]
    prop = rec.get("property_id", "")
    if prop in technique.get("partial", {}) and prop not in technique["measures"]:
        return fit("low", f"Partial: {technique['partial'][prop]}.")
    # An installed accessory for this technique settles the configuration question; smaller items
    # (e.g. geometries) are still listed to confirm in the card's details.
    installed = knowledge.installed_for(eq_id, tid)
    if installed:
        return fit("high", f"Standard technique; {_listing(installed)} installed.")
    if rec["accessories_to_confirm"]:
        return fit("medium", f"Confirm with the contact: {_listing(rec['accessories_to_confirm'])}.")
    return fit("high", "Standard technique; no accessories to confirm.")


def fit_levels(result: dict) -> str:
    """For the log: "EQ15:medium;EQ18:low" (annotated mode; empty otherwise)."""
    return ";".join(f"{r['id']}:{r['fit']}" for r in result.get("recommendations", []) if r.get("fit"))


def check_not_available(items: list) -> list[dict]:
    """Annotated mode: flag "not available" techniques that a listed instrument does perform."""
    checked = []
    for item in items:
        tid = str(item.get("technique_id") or "").strip()
        checked.append({**item, "available_on": knowledge.instruments_for(tid) if tid else []})
    return checked


# --- read an answer (also used to re-score saved answers without calling the model) ---

def new_result(mode: str, raw: str = "") -> dict:
    return {"mode": mode, "raw": raw, "error": None, "usage": {}, "json_ok": None,
            "recommendations": [], "removed": [], "instrument_ids": [], "mentioned_ids": [],
            "primary_ids": [], "supplementary_ids": [], "objective_met": None,
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
    recommendations = parsed.get("recommendations")
    result["recommendations"], result["removed"] = check_recommendations(recommendations)
    result["instrument_ids"] = [rec["id"] for rec in result["recommendations"]]
    result["ids_source"] = "json"
    result["measurement_needs"] = list(parsed.get("measurement_needs") or [])
    result["not_available"] = [n for n in parsed.get("not_available") or [] if isinstance(n, dict)]
    if result["mode"] == "annotated":
        given = {str(r.get("instrument_id", "")).strip().upper(): r
                 for r in recommendations or [] if isinstance(r, dict)}
        for rec in result["recommendations"]:
            check_against_annotations(rec, given[rec["id"]].get("technique_id"))
            rec["property_id"] = str(given[rec["id"]].get("property_id") or "").strip()
        for rec in result["recommendations"]:  # after all are checked: the workflow looks at the others
            check_workflow(rec, result["recommendations"])
            assign_fit(rec)
        result["not_available"] = check_not_available(result["not_available"])
    # Roles are read last: the workflow check can turn a dead end into a supplementary recommendation.
    result["primary_ids"] = [r["id"] for r in result["recommendations"] if r["role"] == "primary"]
    result["supplementary_ids"] = [r["id"] for r in result["recommendations"] if r["role"] == "supplementary"]
    # Met only if some instrument is primary; the model can also say false itself.
    result["objective_met"] = bool(result["primary_ids"]) and parsed.get("objective_met") is not False
    result["clarifying_question"] = parsed.get("clarifying_question")
    result["summary"] = parsed.get("summary", "")
    return result


def read_naive(result: dict) -> dict:
    """Find the instruments in a naive answer: from its "Recommended:" line if present, else by mention.

    Naive mode has no roles (it is the unguided baseline), so every recommended instrument counts as primary.
    """
    known = equipment_by_id()
    result["mentioned_ids"] = instrument_ids_in_text(result["raw"])
    listed = recommended_line_ids(result["raw"])
    if listed is None:
        result["instrument_ids"], result["ids_source"] = result["mentioned_ids"], "mentions"
    else:
        result["instrument_ids"] = [eq_id for eq_id in known if eq_id in listed]
        result["removed"] = [eq_id for eq_id in listed if eq_id not in known]
        result["ids_source"] = "recommended_line"
    result["primary_ids"], result["supplementary_ids"] = list(result["instrument_ids"]), []
    result["objective_met"] = bool(result["instrument_ids"]) if not result["error"] else None
    return result


def read_answer(mode: str, raw: str) -> dict:
    result = new_result(mode, raw)
    return read_structured(result) if mode in JSON_MODES else read_naive(result)


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
    first_raw, first_usage, mode = result["raw"], result["usage"], result["mode"]
    user = build_user_prompt(question, mode) + "\n\n" + REPAIR_REQUEST.format(
        problems="; ".join(problems), raw=first_raw)
    _call(result, SYSTEMS[mode], user, json_mode=True)
    result.update(repaired=True, first_raw=first_raw, usage=add_usage(first_usage, result["usage"]))


def run_structured(question: str, repair: bool = True, mode: str = "structured",
                   on_model_answer: Callable[[], None] | None = None) -> dict:
    """Structured mode: rules + JSON schema; code checks and fills in each recommendation.
    With mode="annotated", the prompt also has the instrument notes and code checks against them.

    If the answer is not JSON of the right shape and repair is on, the model gets one chance to fix it.
    on_model_answer is called when the model's answer arrives, before the checks (for progress display).
    """
    result = new_result(mode)
    try:
        _call(result, SYSTEMS[mode], build_user_prompt(question, mode), json_mode=True)
    except Exception as exc:  # API errors are shown in the page, not raised
        result["error"] = f"{type(exc).__name__}: {exc}"
        return result
    if on_model_answer:
        on_model_answer()
    problems = structured_problems(result["raw"])
    if problems and repair:
        try:
            _repair(result, question, problems)
        except Exception:  # the repair call failed; read the first answer as it is
            pass
    return read_structured(result)


def run_annotated(question: str, repair: bool = True, on_model_answer: Callable[[], None] | None = None) -> dict:
    """Structured + annotations mode."""
    return run_structured(question, repair, mode="annotated", on_model_answer=on_model_answer)


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


# --- follow-up questions (web interface) ---

REWRITE_SYSTEM = """You rewrite a researcher's follow-up question so it can be understood without the conversation.
Use the earlier questions only to fill in what the follow-up leaves out (such as the material, sample,
property or goal). Keep the researcher's wording where you can. If the follow-up already stands on its
own, return it unchanged. Do not answer it, add facts or suggest equipment.

Return ONLY a JSON object: {"standalone_question": "..."}"""
MAX_PREVIOUS = 5


def rewrite_followup(question: str, previous: list[str]) -> str:
    """The follow-up as a question that stands on its own, using the earlier (standalone) questions.

    One small model call; the question comes back unchanged if there is no earlier question or the
    call or its JSON fails.
    """
    previous = [p.strip() for p in previous if p and p.strip()][-MAX_PREVIOUS:]
    if not previous:
        return question
    earlier = "\n".join(f"{i}. {p}" for i, p in enumerate(previous, start=1))
    user = f"Earlier questions, oldest first:\n{earlier}\n\nFollow-up: {question.strip()}"
    try:
        parsed = parse_json(complete(REWRITE_SYSTEM, user, json_mode=True))
    except Exception as exc:  # the original question still gets an answer
        print(f"Follow-up rewrite failed: {type(exc).__name__}: {exc}")
        return question
    rewritten = parsed.get("standalone_question")
    return rewritten.strip() if isinstance(rewritten, str) and rewritten.strip() else question


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
