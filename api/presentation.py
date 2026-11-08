"""What the web interface receives: an allowlist of fields from each checked answer, with audience labels.

Nothing passes through from a raw result or the knowledge files unless it is named here. Review status,
reviewer fields, an instrument's dataset notes, question-file metadata and raw model JSON never leave
the server. Free text written by the model (summary, reasons) is kept, with a light scrub of wording
about the instrument notes' internal status.
"""

import re

import core
import knowledge

MODE_LABELS = {"annotated": "Equipment Finder", "naive": "General AI (no guidance)", "structured": "Rules only"}
DEFAULT_MODE = "annotated"
DEMO_INSTRUMENT = "Demo instrument"
CAPABILITIES_NOTE = "Capabilities: typical for this model"
FICTIONAL_CONTACTS = "Demo data: contact names are fictional."

# Example questions for the start screen. Each has a saved answer, so they also work offline.
EXAMPLES = [
    {"field": "Rheology",
     "question": "My polymer remains unexpectedly viscous during extrusion at elevated temperatures. "
                 "What measurements could help me understand why?"},
    {"field": "Mechanics",
     "question": "I want to determine the compressive stiffness of a porous polymer scaffold. "
                 "What equipment could I use?"},
    {"field": "Imaging",
     "question": "I need to examine the internal structure of a porous specimen without destroying it. "
                 "What characterization methods are available?"},
]

# Wording the model sometimes copies from its instructions about the instrument notes.
_SCRUB = [
    (re.compile(r"\s*\((?:[^()]*\b(?:draft|not yet reviewed|unreviewed)\b[^()]*)\)", re.I), ""),
    (re.compile(r"\bdraft (instrument )?notes\b", re.I), "instrument notes"),
    (re.compile(r",?\s*(?:which are |that are )?not yet reviewed\b", re.I), ""),
]


def clean_text(text) -> str:
    text = str(text or "")
    for pattern, replacement in _SCRUB:
        text = pattern.sub(replacement, text)
    return text.strip()


def _clean_list(items) -> list[str]:
    return [clean_text(item) for item in items or [] if clean_text(item)]


def friendly_error(error: str | None) -> str | None:
    """The page shows a short message; the full error stays in the server log."""
    if not error:
        return None
    if error.startswith(("This session has reached", "Today's model budget", "Offline mode")):
        return error
    if "JSON" in error or "Decode" in error:
        return "The answer came back in an unexpected format. Please try again."
    return "The answering service could not be reached. Please try again in a moment."


def _card(rec: dict) -> dict:
    tid = rec.get("technique_id", "")
    annotated = "fit" in rec
    return {
        "id": rec["id"],
        "name": rec["instrument"],
        "manufacturer": rec["manufacturer"],
        "model": rec["model"],
        "location": rec["location"],
        "contact": rec["contact"],
        "demo_instrument": bool(rec.get("fictional_test_instrument")),
        "role": rec.get("role", "primary"),
        "technique": clean_text(rec.get("technique")),
        "property": knowledge.property_label(rec["property_id"]) if rec.get("property_id") else "",
        "why": clean_text(rec.get("why")),
        "fit": rec.get("fit") or None,
        "fit_reason": clean_text(rec.get("fit_reason")),
        "destructive_level": rec.get("destructive_level") or None,
        "destructive": clean_text(rec.get("destructive")),
        "dead_end": clean_text(rec.get("dead_end")),
        "installed": list(knowledge.installed_for(rec["id"], tid)) if tid else list(rec.get("installed_accessories", [])),
        "to_confirm": _clean_list(rec.get("accessories_to_confirm")),
        "workflow": _clean_list(rec.get("workflow")),
        "cautions": _clean_list(rec.get("cautions")),
        "capabilities_note": CAPABILITIES_NOTE if annotated else "",
    }


def _plan(result: dict, primary: list[dict]) -> dict | None:
    """Need -> technique -> instrument, from the first primary recommendation."""
    if not primary:
        return None
    first = primary[0]
    needs = result.get("measurement_needs") or []
    return {"need": first["property"] or clean_text(needs[0] if needs else ""),
            "technique": first["technique"], "instrument": first["name"], "instrument_id": first["id"]}


def _seconds(result: dict) -> float | None:
    seconds = (result.get("usage") or {}).get("seconds")
    return round(seconds, 1) if isinstance(seconds, (int, float)) else None


def _structured(result: dict) -> dict:
    cards = [_card(rec) for rec in result.get("recommendations", [])]
    primary = [c for c in cards if c["role"] == "primary"]
    return {
        "summary": clean_text(result.get("summary")),
        "clarifying_question": clean_text(result.get("clarifying_question")) or None,
        "measurement_needs": _clean_list(result.get("measurement_needs")),
        "objective_met": bool(result.get("objective_met")),
        "plan": _plan(result, primary),
        "primary": primary,
        "complementary": [c for c in cards if c["role"] != "primary"],
        # An item the checks found on a listed instrument is the model's mistake; it is not shown.
        "not_available": [{"technique": clean_text(n.get("technique")), "why_useful": clean_text(n.get("why_useful"))}
                          for n in result.get("not_available", []) if not n.get("available_on")],
        "removed_count": len(result.get("removed", [])),
    }


_RECOMMENDED = re.compile(r"^\W*recommended\W*:.*$", re.I | re.M)


def naive_gaps(text: str, instrument_ids: list[str]) -> list[str]:
    """What a general answer leaves out, compared with Equipment Finder's checked answer."""
    known = core.equipment_by_id()
    lower = text.lower()
    gaps = []
    named = [known[i] for i in instrument_ids if i in known]
    no_contact = [e for e in named if e["contact"].split(" (")[0].lower() not in lower]
    if not named:
        gaps.append("Names no specific instrument on campus")
    elif no_contact:
        gaps.append(f"No contact for {len(no_contact)} of {len(named)} instruments it names")
    if "confirm" not in lower:
        gaps.append("Doesn't say which accessories to confirm before booking")
    if "installed" not in lower:
        gaps.append("Doesn't separate installed setup from what still has to be checked")
    return gaps


def _naive(result: dict) -> dict:
    text = _RECOMMENDED.sub("", result.get("raw") or "").strip()
    return {"text": clean_text(text), "gaps": naive_gaps(text, result.get("instrument_ids", []))}


def sanitize(result: dict) -> dict:
    """The answer as the interface shows it."""
    mode = result["mode"]
    payload = {"mode": mode, "mode_label": MODE_LABELS[mode], "error": friendly_error(result.get("error")),
               "seconds": _seconds(result)}
    if payload["error"]:
        return payload
    payload.update(_structured(result) if mode in core.JSON_MODES else _naive(result))
    return payload


def source_label(result: dict) -> str:
    return {"demo_backup": "saved", "cache": "cache"}.get(result.get("source"), "live")


def equipment() -> list[dict]:
    return [{"id": e["id"], "name": e["instrument"], "manufacturer": e["manufacturer"], "model": e["model"],
             "location": e["location"], "contact": e["contact"],
             "demo_instrument": bool(e["fictional_test_instrument"]),
             "installed": list(e["installed_accessories"]),
             "techniques": [knowledge.technique_name(t) for t in knowledge.techniques_of(e["id"])]}
            for e in core.load_equipment()]
