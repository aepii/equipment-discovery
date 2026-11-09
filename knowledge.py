"""The knowledge layer: technique knowledge base, instrument annotations and controlled vocabulary.

data/vocabulary.json   allowed property ids, kinds, sources, confidence levels and statuses
data/techniques.json   what each technique measures, whether it is destructive, workflow steps
data/annotations.json  which techniques each instrument (EQ01-EQ23) typically performs, accessories, limits

Annotations describe what this TYPE of instrument typically does. They never say an accessory is
installed unless the dataset itself lists it.
"""

import hashlib
import json
from functools import lru_cache
from pathlib import Path

DATA_DIR = Path(__file__).parent / "data"
VOCABULARY_PATH = DATA_DIR / "vocabulary.json"
TECHNIQUES_PATH = DATA_DIR / "techniques.json"
ANNOTATIONS_PATH = DATA_DIR / "annotations.json"
MEASURING_KINDS = ("measurement", "imaging")


# --- loading ---

def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def vocabulary() -> dict:
    return _read(VOCABULARY_PATH)


@lru_cache(maxsize=1)
def techniques() -> dict[str, dict]:
    return _read(TECHNIQUES_PATH)["techniques"]


@lru_cache(maxsize=1)
def annotations() -> dict[str, dict]:
    """Instrument annotations by instrument ID."""
    return {a["id"]: a for a in _read(ANNOTATIONS_PATH)["instruments"]}


def text_bytes(path: Path) -> bytes:
    """A text file's bytes with LF line endings, so a version hash is the same on Windows (where git may
    check files out with CRLF) and on Linux."""
    return path.read_bytes().replace(b"\r\n", b"\n")


def knowledge_version() -> str:
    """Changes whenever any knowledge file changes (for prompt versions, the cache and demo answers)."""
    data = b"".join(text_bytes(p) for p in (VOCABULARY_PATH, TECHNIQUES_PATH, ANNOTATIONS_PATH))
    return hashlib.sha1(data).hexdigest()[:8]


# --- lookups ---

def property_label(prop_id: str) -> str:
    return vocabulary()["properties"].get(prop_id, {}).get("label", prop_id)


def technique_name(tech_id: str) -> str:
    return techniques().get(tech_id, {}).get("name", tech_id)


def techniques_of(eq_id: str) -> dict[str, dict]:
    """The techniques an instrument typically performs: {technique id: {source, confidence}}."""
    entries = annotations().get(eq_id, {}).get("techniques", [])
    return {t["technique"]: t for t in entries}


def instruments_for(tech_id: str) -> list[str]:
    """IDs of the instruments that typically perform a technique (empty: not available in the dataset)."""
    return [eq_id for eq_id in annotations() if tech_id in techniques_of(eq_id)]


def unavailable_techniques() -> list[str]:
    """Measuring or imaging techniques that no listed instrument performs (e.g. micro-CT)."""
    return [tid for tid, t in techniques().items() if t["kind"] in MEASURING_KINDS and not instruments_for(tid)]


def destructive_for(tech_id: str, prop: str = "") -> str:
    """How destructive a technique is when it is used for one property: yes / no / depends / aliquot / ...
    destructive_by_property settles a 'depends' per property (TEM: 'yes' for sectioned tissue, 'aliquot' for
    a drop of nanoparticles on a grid)."""
    t = techniques().get(tech_id, {})
    return t.get("destructive_by_property", {}).get(prop, t.get("destructive", ""))


def _conditions(eq_id: str, tech_id: str, prop: str) -> list[dict]:
    """Conditions on the technique (any instrument) and on this instrument's link to it, for one property."""
    found = techniques().get(tech_id, {}).get("conditions", []) + techniques_of(eq_id).get(tech_id, {}).get("conditions", [])
    return [c for c in found if c.get("property", "*") in ("*", prop)]


EFFECT_ORDER = ("excluded", "partial", "full")  # the first one that applies wins


def link_level(eq_id: str, tech_id: str, prop: str, sample_conditions=()) -> tuple[str | None, str]:
    """How a technique on an instrument gives a property for a sample with these conditions.

    Returns (level, why): level is "full", "partial", "excluded" (a condition rules it out) or None (the
    technique does not give the property at all); why is the partial or condition reason ("" for full).
    Without conditions this is just measures (full) or partial.
    """
    t = techniques().get(tech_id, {})
    if prop in t.get("measures", []):
        level, why = "full", ""
    elif prop in t.get("partial", {}):
        level, why = "partial", t["partial"][prop]
    else:
        return None, ""
    applying = [c for c in _conditions(eq_id, tech_id, prop) if c["when"] in sample_conditions]
    for effect in EFFECT_ORDER:
        hit = next((c for c in applying if c["effect"] == effect), None)
        if hit:
            return effect, hit.get("why", "") if effect != "full" else ""
    return level, why


def sample_condition_ids(values) -> list[str]:
    """The known sample-condition IDs among values (unknown ones are dropped)."""
    known = vocabulary().get("sample_conditions", {})
    return [v for v in dict.fromkeys(str(x).strip() for x in values or []) if v in known]


def accessories_for(eq_id: str, tech_id: str) -> list[str]:
    """Accessories still to confirm for one instrument and technique."""
    return [a["item"] for a in annotations().get(eq_id, {}).get("accessories", [])
            if tech_id in a["for"] and a["status"] == "to_confirm"]


def installed_for(eq_id: str, tech_id: str) -> list[str]:
    """Accessories for one instrument and technique that are installed (listed in the dataset or confirmed)."""
    return [a["item"] for a in annotations().get(eq_id, {}).get("accessories", [])
            if tech_id in a["for"] and a["status"] in ("listed_in_dataset", "confirmed")]


def _step(tech_id: str, when: str = "") -> dict:
    """One workflow step: available on listed instruments, a bench step (no instrument needed) or missing."""
    t = techniques().get(tech_id, {})
    instruments = instruments_for(tech_id)
    status = "available" if instruments else "bench_step" if t.get("kind") == "bench_step" else "missing"
    # A step "when" something applies may be needed; only "always" makes it a hard requirement.
    conditional = bool(when) and not when.lower().startswith("always")
    return {"technique": tech_id, "name": technique_name(tech_id), "status": status,
            "instruments": instruments, "when": when, "conditional": conditional}


def workflow_for(tech_id: str) -> dict:
    """The steps around a technique: "requires" (what must or may come first, with its condition) and
    "leads_to" (what the result is used for), each labeled available / bench_step / missing."""
    t = techniques().get(tech_id, {})
    return {"requires": [_step(s["technique"], s.get("when", "")) for s in t.get("requires_before", [])],
            "leads_to": [_step(s) for s in t.get("leads_to", [])]}


def review_status(eq_id: str) -> str:
    return annotations().get(eq_id, {}).get("review", {}).get("status", "")


# --- checking the files against each other and against the dataset ---

def _check_enum(problems: list, where: str, field: str, value, allowed) -> None:
    if value not in allowed:
        problems.append(f"{where}: {field} '{value}' is not one of {sorted(allowed)}")


def _check_conditions(problems: list, where: str, conditions, vocab: dict, linked: set | None = None) -> None:
    """Conditions name a known sample condition and effect, and a property the technique links to (or '*')."""
    for c in conditions or []:
        _check_enum(problems, where, "condition", c.get("when"), vocab.get("sample_conditions", {}))
        _check_enum(problems, where, "condition effect", c.get("effect"), vocab.get("condition_effects", {}))
        prop = c.get("property", "*")
        if prop != "*" and linked is not None and prop not in linked:
            problems.append(f"{where}: condition for '{prop}', which the technique neither measures nor partly measures")
        if not c.get("why"):
            problems.append(f"{where}: condition '{c.get('when')}' has no 'why'")


def _check_corrections(problems: list, where: str, corrections) -> None:
    """Each correction says what changed, where it comes from, and that the expert still has to confirm it."""
    for c in corrections or []:
        for field in ("change", "source"):
            if not str(c.get(field, "")).strip():
                problems.append(f"{where}: correction without '{field}'")
        if not isinstance(c.get("needs_confirmation"), bool):
            problems.append(f"{where}: correction needs 'needs_confirmation' true or false")


def validate(equipment: list[dict], vocab: dict | None = None, techs: dict | None = None,
             annots: list[dict] | None = None) -> list[str]:
    """Problems in the knowledge files (empty list if none). Pass the parts to check other data, e.g. a draft."""
    vocab = vocab if vocab is not None else vocabulary()
    techs = techs if techs is not None else techniques()
    annots = annots if annots is not None else list(annotations().values())
    props, sources, levels = set(vocab["properties"]), set(vocab["sources"]), set(vocab["confidence"])
    problems = []

    for tid, t in techs.items():
        where = f"technique {tid}"
        for field in ("name", "kind", "measures", "destructive", "requires_before", "leads_to"):
            if field not in t:
                problems.append(f"{where}: '{field}' is missing")
        _check_enum(problems, where, "kind", t.get("kind"), vocab["technique_kinds"])
        _check_enum(problems, where, "destructive", t.get("destructive"), vocab["destructive"])
        _check_enum(problems, where, "source", t.get("source"), sources)
        _check_enum(problems, where, "confidence", t.get("confidence"), levels)
        linked = set(t.get("measures", [])) | set(t.get("partial", {}))
        for prop in list(t.get("measures", [])) + list(t.get("partial", {})):
            if prop not in props:
                problems.append(f"{where}: property '{prop}' is not in the vocabulary")
        for prop, level in t.get("destructive_by_property", {}).items():
            if prop not in linked:
                problems.append(f"{where}: destructive_by_property for '{prop}', which it does not measure")
            _check_enum(problems, where, f"destructive for {prop}", level, vocab["destructive"])
        _check_conditions(problems, where, t.get("conditions"), vocab, linked)
        _check_corrections(problems, where, t.get("corrections"))
        steps = [s["technique"] for s in t.get("requires_before", [])] + list(t.get("leads_to", []))
        for step in steps:
            if step not in techs:
                problems.append(f"{where}: workflow step '{step}' is not a known technique")

    known = {e["id"]: e for e in equipment}
    seen = [a.get("id") for a in annots]
    for eq_id in known:
        if eq_id not in seen:
            problems.append(f"{eq_id} has no annotation")
    for eq_id in {i for i in seen if seen.count(i) > 1}:
        problems.append(f"{eq_id} is annotated more than once")
    for a in annots:
        where = f"annotation {a.get('id')}"
        if a.get("id") not in known:
            problems.append(f"{where}: not an instrument in the dataset")
            continue
        if a.get("instrument") != known[a["id"]]["instrument"]:
            problems.append(f"{where}: name '{a.get('instrument')}' does not match the dataset "
                            f"('{known[a['id']]['instrument']}')")
        if not a.get("techniques"):
            problems.append(f"{where}: no techniques")
        own = set()
        for t in a.get("techniques", []):
            own.add(t.get("technique"))
            if t.get("technique") not in techs:
                problems.append(f"{where}: technique '{t.get('technique')}' is not in techniques.json")
            _check_enum(problems, where, "source", t.get("source"), sources)
            _check_enum(problems, where, "confidence", t.get("confidence"), levels)
            tech = techs.get(t.get("technique"), {})
            _check_conditions(problems, where, t.get("conditions"), vocab,
                              set(tech.get("measures", [])) | set(tech.get("partial", {})))
        _check_corrections(problems, where, a.get("corrections"))
        for acc in a.get("accessories", []):
            _check_enum(problems, where, "accessory status", acc.get("status"), vocab["accessory_status"])
            _check_enum(problems, where, "source", acc.get("source"), sources)
            if acc.get("status") == "listed_in_dataset" and acc.get("source") != "dataset":
                problems.append(f"{where}: '{acc.get('item')}' is listed_in_dataset but its source is not the dataset")
            for tid in acc.get("for", []):
                if tid not in own:
                    problems.append(f"{where}: accessory '{acc.get('item')}' is for '{tid}', "
                                    "which this instrument does not perform")
        for field in ("typical_samples", "limitations"):
            if not isinstance(a.get(field), list):
                problems.append(f"{where}: '{field}' must be a list")
        _check_enum(problems, where, "review status", a.get("review", {}).get("status"), vocab["review_status"])
    return problems


# --- text for the prompt ---

DESTRUCTIVE_TEXT = {"aliquot": "only a small separate portion is used up", "not_applicable": "not applicable"}


def destructive_text(level: str) -> str:
    return DESTRUCTIVE_TEXT.get(level, level.replace("_", " "))


def _condition_text(c: dict) -> str:
    """"if opaque_sample: not possible for Internal 3D structure (why)"."""
    effect = {"excluded": "not possible", "partial": "only partly", "full": "fully"}[c["effect"]]
    prop = c.get("property", "*")
    target = f" for {property_label(prop)} [{prop}]" if prop != "*" else ""
    return f"if {c['when']}: {effect}{target} ({c['why']})"


def _technique_line(tid: str, entry: dict | None = None) -> str:
    """One technique for the annotated prompt; property IDs in square brackets (the model names one per
    recommendation as "property_id", so code can tell a full measurement from a partial one)."""
    t = techniques()[tid]
    measures = "; ".join(f"{property_label(p)} [{p}]" for p in t["measures"]) or "nothing (prepares or makes samples)"
    partial = "; ".join(f"{property_label(p)} [{p}] ({why})" for p, why in t.get("partial", {}).items())
    line = f"{tid} = {t['name']}. Measures: {measures}"
    if partial:
        line += f". Partly: {partial}"
    line += f". Destructive: {destructive_text(t['destructive'])}" + (
        f" ({t['destructive_note']})" if t.get("destructive_note") else "")
    by_property = "; ".join(f"for {property_label(p)} [{p}]: {destructive_text(level)}"
                            for p, level in t.get("destructive_by_property", {}).items())
    if by_property:
        line += f" ({by_property})"
    conditions = t.get("conditions", []) + (entry or {}).get("conditions", [])
    if conditions:
        line += ". Depends on the sample: " + "; ".join(_condition_text(c) for c in conditions)
    if entry and entry["confidence"] == "low":
        line += ". [Only with optional hardware not listed in the dataset]"
    return line


def format_annotated_equipment(equipment: list[dict]) -> str:
    """The equipment list with each instrument's draft annotations, for the annotated-mode prompt."""
    blocks = []
    for e in equipment:
        a = annotations().get(e["id"])
        lines = [f"{e['id']} | {e['instrument']} | {e['manufacturer']} {e['model']}"]
        installed = e.get("installed_accessories", [])
        if installed:
            lines.append(f"  Installed accessories: {'; '.join(installed)}")
        if e["notes"] and not e.get("fictional_test_instrument"):  # see core.prompt_notes
            lines.append(f"  Dataset notes: {e['notes']}")
        if a:
            lines.append("  Typical techniques:")
            lines += [f"    - {_technique_line(tid, entry)}" for tid, entry in techniques_of(e["id"]).items()]
            lines.append(f"  Typical samples: {'; '.join(a['typical_samples'])}")
            lines.append(f"  Limitations: {'; '.join(a['limitations'])}")
            listed = [x["item"] for x in a["accessories"]
                      if x["status"] == "listed_in_dataset" and x["item"] not in installed]
            confirm = [f"{x['item']} (for {', '.join(x['for'])})" for x in a["accessories"]
                       if x["status"] == "to_confirm"]
            if listed:
                lines.append(f"  Installed per the dataset: {'; '.join(listed)}")
            if confirm:
                lines.append(f"  Accessories to confirm with the contact: {'; '.join(confirm)}")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def format_unavailable_techniques() -> str:
    """Techniques no listed instrument performs, so the model can name them in not_available."""
    return "\n".join(f"- {_technique_line(tid)}" for tid in unavailable_techniques())


def format_sample_conditions() -> str:
    """The sample conditions the model may report, so code can test the conditional links."""
    return "\n".join(f"- {cid}: {text}" for cid, text in vocabulary().get("sample_conditions", {}).items())
